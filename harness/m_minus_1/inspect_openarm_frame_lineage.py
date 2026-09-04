"""Build a value-free preflight for the OpenArm source-to-target frame line.

The M-1 diagnostics can compare frame hypotheses, but they cannot turn an
inferred hypothesis into a physical frame claim.  This standalone harness
records which source and target evidence is actually present, without reading
dataset rows or emitting private values.  It is intentionally a preflight:
an ``APPROVED`` mapping or a source URDF still needs an explicit calibration
validation before a recipe may be promoted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import yaml

SCHEMA = "m_minus_1.openarm_frame_lineage.v1"
TARGET_SIDES = ("left", "right")
TARGET_FRAME_SUFFIXES = ("link7", "hand_tcp")
SOURCE_END_LINKS = ("Larm08_link", "Rarm08_link")


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def load_yaml(path: Path, label: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"{label} is not valid YAML") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a YAML mapping")
    return value


def local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def is_absolute_path(value: str) -> bool:
    return (
        PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
        or bool(PureWindowsPath(value).drive)
    )


def safe_asset_file(asset_dir: Path, relative: str) -> Path | None:
    if not relative or is_absolute_path(relative):
        return None
    parts = PurePosixPath(relative.replace("\\", "/")).parts
    if ".." in parts:
        return None
    path = (asset_dir / Path(*parts)).resolve()
    try:
        path.relative_to(asset_dir.resolve())
    except ValueError:
        return None
    return path


def parse_urdf(path: Path) -> ET.Element | None:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None
    return root if local_tag(root) == "robot" else None


def _mapping_payload(raw: dict[str, Any]) -> dict[str, Any]:
    payload = raw.get("mapping", raw)
    if not isinstance(payload, dict):
        raise ValueError("mapping candidate payload must be an object")
    return payload


def inspect_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    streams = mapping.get("streams")
    if not isinstance(streams, list):
        streams = []
    position_units: list[str | None] = []
    position_frames: list[str | None] = []
    orientation_orders: list[str | None] = []
    orientation_frames: list[str | None] = []
    stream_names: list[str] = []
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        name = stream.get("name")
        if isinstance(name, str):
            stream_names.append(name)
        fields = stream.get("fields")
        if not isinstance(fields, dict):
            continue
        position = fields.get("position")
        orientation = fields.get("orientation")
        if isinstance(position, dict):
            position_units.append(position.get("unit"))
            position_frames.append(position.get("frame"))
        if isinstance(orientation, dict):
            orientation_orders.append(orientation.get("quaternion_order"))
            orientation_frames.append(orientation.get("frame"))
    coordinate_frame = mapping.get("coordinate_frame")
    metadata = mapping.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    slot_semantics = str(metadata.get("slot_semantics", ""))
    return {
        "dataset_alias": mapping.get("dataset_alias"),
        "source_revision": mapping.get("source_revision"),
        "coordinate_frame": coordinate_frame,
        "stream_count": len(stream_names),
        "stream_names_are_explicit": bool(stream_names)
        and all(not name.endswith(("slot_0", "slot_1")) for name in stream_names),
        "source_frame_declared": isinstance(coordinate_frame, str)
        and bool(coordinate_frame.strip())
        and coordinate_frame != "UNRESOLVED"
        and bool(position_frames)
        and all(frame == coordinate_frame for frame in position_frames)
        and bool(orientation_frames)
        and all(frame == coordinate_frame for frame in orientation_frames),
        "source_position_unit_declared": bool(position_units)
        and all(unit == "m" for unit in position_units),
        "source_orientation_order_declared": bool(orientation_orders)
        and all(order == "wxyz" for order in orientation_orders),
        "source_slot_labels_declared": bool(slot_semantics)
        and "unresolved" not in slot_semantics.lower(),
        "candidate_status": metadata.get("candidate_status"),
    }


def _fixed_joint_origin(joint: ET.Element) -> tuple[float, float, float] | None:
    origin = next((item for item in joint if local_tag(item) == "origin"), None)
    if origin is None:
        return None
    values = origin.get("xyz", "").split()
    if len(values) != 3:
        return None
    try:
        vector = tuple(float(value) for value in values)
    except ValueError:
        return None
    return vector if all(math.isfinite(value) for value in vector) else None


def inspect_target_asset(asset_dir: Path) -> dict[str, Any]:
    manifest_path = asset_dir / "asset_manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            manifest = load_json(manifest_path, "OpenArm asset manifest")
        except ValueError:
            manifest = {}
    raw_urdf = manifest.get("generated_urdf_path", "urdf/openarm_bimanual_v10.urdf")
    urdf_path = safe_asset_file(asset_dir, str(raw_urdf))
    root = parse_urdf(urdf_path) if urdf_path is not None else None
    links = {
        element.get("name")
        for element in root.iter()
        if local_tag(element) == "link" and element.get("name")
    } if root is not None else set()
    joints = {
        element.get("name"): element
        for element in root.iter()
        if local_tag(element) == "joint" and element.get("name")
    } if root is not None else {}
    expected_frames = {
        f"openarm_{side}_{suffix}"
        for side in TARGET_SIDES
        for suffix in TARGET_FRAME_SUFFIXES
    }
    chain_z: dict[str, float | None] = {}
    for side in TARGET_SIDES:
        hand_origin = _fixed_joint_origin(joints.get(f"{side}_openarm_hand_joint")) \
            if joints.get(f"{side}_openarm_hand_joint") is not None else None
        tcp_joint_name = f"openarm_{side}_hand_tcp_joint"
        tcp_origin = _fixed_joint_origin(joints.get(tcp_joint_name)) \
            if joints.get(tcp_joint_name) is not None else None
        if hand_origin is None or tcp_origin is None:
            chain_z[side] = None
        else:
            chain_z[side] = round(hand_origin[2] + tcp_origin[2], 7)
    declared_hash = manifest.get("generated_urdf_sha256")
    actual_hash = sha256_file(urdf_path) if urdf_path is not None else None
    source_meshes_relative = True
    if root is not None:
        for mesh in root.iter():
            if local_tag(mesh) != "mesh":
                continue
            filename = mesh.get("filename", "")
            source_meshes_relative &= (
                bool(filename)
                and not is_absolute_path(filename)
                and ".." not in PurePosixPath(filename.replace("\\", "/")).parts
            )
    return {
        "manifest_present": manifest_path.is_file(),
        "urdf_present": urdf_path is not None and urdf_path.is_file(),
        "urdf_parseable": root is not None,
        "urdf_hash_matches_manifest": bool(declared_hash)
        and actual_hash is not None
        and str(declared_hash).lower() == actual_hash.lower(),
        "target_frames_present": expected_frames.issubset(links),
        "target_tcp_chain_explicit": all(value is not None for value in chain_z.values()),
        "target_tcp_chain_z_m": chain_z,
        "target_mesh_references_relative": source_meshes_relative,
        "urdf_sha256": actual_hash,
        "manifest_sha256": sha256_file(manifest_path),
    }


def inspect_optional_source(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "provided": False,
            "present": False,
            "parseable": False,
            "expected_end_links_present": False,
            "sha256": None,
        }
    root = parse_urdf(path)
    links = {
        element.get("name")
        for element in root.iter()
        if local_tag(element) == "link" and element.get("name")
    } if root is not None else set()
    return {
        "provided": True,
        "present": path.is_file(),
        "parseable": root is not None,
        "expected_end_links_present": set(SOURCE_END_LINKS).issubset(links),
        "sha256": sha256_file(path),
    }


def inspect_optional_mapping(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"provided": False, "present": False, "parseable": False, "sha256": None}
    try:
        payload = load_json(path, "authorized mapping")
        parseable = bool(payload)
    except ValueError:
        parseable = False
    return {
        "provided": True,
        "present": path.is_file(),
        "parseable": parseable,
        "sha256": sha256_file(path),
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    recipe = load_yaml(args.recipe.resolve(), "recipe")
    mapping_raw = load_json(args.mapping_candidate.resolve(), "mapping candidate")
    mapping = _mapping_payload(mapping_raw)
    mapping_checks = inspect_mapping(mapping)
    target = inspect_target_asset(args.asset_dir.resolve())
    source_urdf = inspect_optional_source(
        args.source_urdf.resolve() if args.source_urdf is not None else None
    )
    authorized_mapping = inspect_optional_mapping(
        args.authorized_mapping.resolve() if args.authorized_mapping is not None else None
    )
    recipe_dataset = recipe.get("dataset", {})
    recipe_robot = recipe.get("robot", {})
    recipe_semantics_unconfirmed = (
        recipe_robot.get("frame_semantics_status") == "unconfirmed"
        and recipe_robot.get("orientation_mapping") == "identity_dataset_native_hypothesis"
    )
    recipe_policy_safe = (
        recipe_dataset.get("held_out_access") == "forbidden_before_m1c"
        or recipe_dataset.get("held_out_policy") == "do_not_read_before_m1c"
        or recipe.get("sampling", {}).get("held_out_access") == "forbidden_before_m1c"
    )
    recipe_manifest = recipe_dataset.get("source_manifest", {})
    recipe_info_hash = recipe_manifest.get("info_json_sha256")
    mapping_source_revision = mapping.get("source_revision")
    source_revision_matches_recipe = (
        mapping_source_revision == recipe_dataset.get("source_revision")
        or (
            isinstance(mapping_source_revision, str)
            and isinstance(recipe_info_hash, str)
            and recipe_info_hash in mapping_source_revision
        )
    )
    target_ready = all(
        target.get(name, False)
        for name in (
            "manifest_present",
            "urdf_present",
            "urdf_parseable",
            "urdf_hash_matches_manifest",
            "target_frames_present",
            "target_tcp_chain_explicit",
            "target_mesh_references_relative",
        )
    )
    source_evidence_present = (
        source_urdf["parseable"] and source_urdf["expected_end_links_present"]
    ) or authorized_mapping["parseable"]
    blocking_reasons: list[str] = []
    if not target_ready:
        blocking_reasons.append("target OpenArm asset evidence is incomplete")
    if not mapping_checks["source_frame_declared"]:
        blocking_reasons.append("source coordinate frame is unresolved")
    if not mapping_checks["source_position_unit_declared"]:
        blocking_reasons.append("source position unit is unresolved")
    if not mapping_checks["source_slot_labels_declared"]:
        blocking_reasons.append("source slot-to-side labels are unresolved")
    if not source_evidence_present:
        blocking_reasons.append("no source URDF or authorized source-to-target mapping is present")
    if recipe_semantics_unconfirmed and not recipe_policy_safe:
        blocking_reasons.append("recipe does not preserve the held-out access policy")

    if not target_ready:
        status = "ASSET_INVALID"
        next_action = "REPAIR_TARGET_ASSET"
    elif source_evidence_present:
        status = "READY_FOR_AUTHORIZED_MAPPING_VALIDATION"
        next_action = "RUN_CALIBRATION_MAPPING_VALIDATION"
    else:
        status = "BLOCKED_SEMANTICS"
        next_action = "OBTAIN_SOURCE_FRAME_EVIDENCE"

    return {
        "schema_version": SCHEMA,
        "status": status,
        "next_action": next_action,
        "dataset_alias": mapping.get("dataset_alias", recipe_dataset.get("alias")),
        "source_revision": mapping.get("source_revision", recipe_dataset.get("source_revision")),
        "checks": {
            **{
                f"mapping_{key}": value
                for key, value in mapping_checks.items()
                if key
                not in {"dataset_alias", "source_revision", "coordinate_frame", "candidate_status"}
            },
            "recipe_semantics_unconfirmed": recipe_semantics_unconfirmed,
            "recipe_held_out_policy_preserved": recipe_policy_safe,
            "target_asset_ready": target_ready,
            "source_urdf_evidence_present": source_evidence_present,
            "dataset_alias_matches_recipe": mapping.get("dataset_alias")
            == recipe_dataset.get("alias"),
            "source_revision_matches_recipe": source_revision_matches_recipe,
        },
        "target_asset": {
            key: value for key, value in target.items()
            if key not in {"urdf_sha256", "manifest_sha256"}
        },
        "source_urdf": source_urdf,
        "authorized_mapping": authorized_mapping,
        "blocking_reasons": blocking_reasons,
        "inputs": {
            "recipe_sha256": sha256_file(args.recipe.resolve()),
            "mapping_candidate_sha256": sha256_file(args.mapping_candidate.resolve()),
            "target_urdf_sha256": target.get("urdf_sha256"),
            "target_manifest_sha256": target.get("manifest_sha256"),
        },
        "privacy": {
            "private_data_read": False,
            "private_pose_values_read": False,
            "held_out_read": False,
            "raw_source_paths_emitted": False,
            "absolute_paths_emitted": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--mapping-candidate", type=Path, required=True)
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--source-urdf", type=Path)
    parser.add_argument("--authorized-mapping", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {args.output}")
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"status": report["status"], "next_action": report["next_action"]},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
