"""Assert the portable dual-Panda target asset used by the reselection spike."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import numpy as np
import pinocchio as pin


SCHEMA = "m_minus_1.panda_asset_assertions.v1"
URDF_RELATIVE = Path("urdf/panda_bimanual.urdf")
EXPECTED_SIDES = ("panda_1", "panda_2")
EXPECTED_TCP = ("panda_1_hand_tcp", "panda_2_hand_tcp")
EXPECTED_MOUNTS = {
    "panda_1_link0": np.array([0.0, -0.5, 1.0]),
    "panda_2_link0": np.array([0.0, 0.5, 1.0]),
}


def tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_absolute_reference(filename: str) -> bool:
    return (
        PurePosixPath(filename).is_absolute()
        or PureWindowsPath(filename).is_absolute()
        or bool(PureWindowsPath(filename).drive)
    )


def parse_urdf(urdf_path: Path) -> ET.Element:
    try:
        root = ET.parse(urdf_path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError("URDF is not valid XML") from exc
    if tag(root) != "robot":
        raise ValueError("URDF root is not robot")
    return root


def assert_manifest(
    asset_dir: Path,
    urdf_path: Path,
    srdf_path: Path,
    references: set[str],
    checks: dict[str, bool],
    failures: list[str],
) -> dict[str, Any]:
    path = asset_dir / "asset_manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        checks["manifest_valid"] = False
        failures.append("manifest: missing or invalid JSON")
        return {}
    checks["manifest_valid"] = True
    checks["manifest_schema"] = manifest.get("schema_version") == "m_minus_1.panda_assets.v1"
    if not checks["manifest_schema"]:
        failures.append("manifest: unexpected schema version")
    checks["manifest_role"] = manifest.get("asset_role") == "target_reselection_spike_only"
    if not checks["manifest_role"]:
        failures.append("manifest: asset role is not target_reselection_spike_only")
    manifest_references = manifest.get("mesh_paths")
    checks["manifest_mesh_inventory"] = isinstance(manifest_references, list) and set(manifest_references) == references
    if not checks["manifest_mesh_inventory"]:
        failures.append("manifest: mesh inventory does not match URDF")
    checks["manifest_mesh_count"] = manifest.get("mesh_count") == len(references)
    if not checks["manifest_mesh_count"]:
        failures.append("manifest: mesh count does not match URDF")
    checks["manifest_urdf_hash"] = manifest.get("generated_urdf_sha256") == sha256_file(urdf_path)
    if not checks["manifest_urdf_hash"]:
        failures.append("manifest: generated URDF hash mismatch")
    checks["manifest_srdf_hash"] = (
        manifest.get("srdf_path") == "srdf/panda_bimanual.srdf"
        and manifest.get("srdf_sha256") == sha256_file(srdf_path)
    )
    if not checks["manifest_srdf_hash"]:
        failures.append("manifest: SRDF path or hash mismatch")
    return manifest


def assert_meshes(
    root: ET.Element,
    asset_dir: Path,
    checks: dict[str, bool],
    failures: list[str],
) -> set[str]:
    references: set[str] = set()
    collision_count = 0
    for element in root.iter():
        if tag(element) != "mesh":
            continue
        filename = element.get("filename")
        if not filename:
            failures.append("mesh: filename is missing")
            continue
        references.add(filename)
        normalized = filename.replace("\\", "/")
        relative = PurePosixPath(normalized)
        if "://" in normalized or is_absolute_reference(normalized):
            failures.append(f"mesh: non-portable reference {normalized}")
        if ".." in relative.parts or not normalized.startswith("meshes/"):
            failures.append(f"mesh: reference escapes meshes tree {normalized}")
            continue
        resolved = (asset_dir / Path(*relative.parts)).resolve()
        try:
            resolved.relative_to(asset_dir.resolve())
        except ValueError:
            failures.append(f"mesh: reference resolves outside asset {normalized}")
            continue
        if not resolved.is_file():
            failures.append(f"mesh: bundled file is missing {normalized}")

    for element in root.iter():
        if tag(element) == "collision":
            collision_count += sum(1 for child in element if tag(child) == "geometry")
    checks["mesh_references_portable"] = not any(failure.startswith("mesh:") for failure in failures)
    checks["mesh_files_present"] = checks["mesh_references_portable"] and all(
        (asset_dir / Path(*PurePosixPath(reference).parts)).is_file()
        for reference in references
    )
    checks["collision_geometry_present"] = collision_count > 0
    if not checks["mesh_references_portable"]:
        failures.append("mesh: one or more references are not portable")
    if not checks["mesh_files_present"]:
        failures.append("mesh: one or more bundled files are missing")
    if not checks["collision_geometry_present"]:
        failures.append("collision: URDF has no collision geometry")
    return references


def assert_structure(
    root: ET.Element,
    model: pin.Model,
    geometry: pin.GeometryModel,
    checks: dict[str, bool],
    failures: list[str],
) -> None:
    links = {
        element.get("name")
        for element in root.iter()
        if tag(element) == "link" and element.get("name")
    }
    joints = {
        element.get("name"): element
        for element in root.iter()
        if tag(element) == "joint" and element.get("name")
    }
    checks["base_is_geometry_free"] = not any(
        tag(child) in {"visual", "collision"}
        for element in root.iter()
        if tag(element) == "link" and element.get("name") == "base"
        for child in element
    )
    if not checks["base_is_geometry_free"]:
        failures.append("base: environment geometry survived the target build")

    checks["model_dimension"] = model.nq == 18 and model.nv == 18
    if not checks["model_dimension"]:
        failures.append(f"model: expected nq=nv=18, got {model.nq}/{model.nv}")

    required_names = set(
        f"{side}_joint{index}"
        for side in EXPECTED_SIDES
        for index in range(1, 8)
    )
    required_names.update(
        f"{side}_finger_joint{index}"
        for side in EXPECTED_SIDES
        for index in (1, 2)
    )
    checks["required_model_joints_present"] = all(model.getJointId(name) != 0 for name in required_names)
    if not checks["required_model_joints_present"]:
        failures.append("model: required Panda joints or TCP frames are missing")

    finger_checks = []
    for side in EXPECTED_SIDES:
        for index in (1, 2):
            name = f"{side}_finger_joint{index}"
            joint = joints.get(name)
            limit = joint.find("limit") if joint is not None else None
            finger_checks.append(
                joint is not None
                and joint.get("type") == "prismatic"
                and limit is not None
                and math.isclose(float(limit.get("lower", "nan")), 0.0, abs_tol=1e-9)
                and math.isclose(float(limit.get("upper", "nan")), 0.04, abs_tol=1e-9)
            )
    checks["finger_joints_prismatic_and_bounded"] = all(finger_checks)
    if not checks["finger_joints_prismatic_and_bounded"]:
        failures.append("finger: expected prismatic [0, 0.04] joints are missing")
    checks["finger_mimic_declared"] = all(
        joints.get(f"{side}_finger_joint2", ET.Element("missing")).find("mimic") is not None
        for side in EXPECTED_SIDES
    )
    if not checks["finger_mimic_declared"]:
        failures.append("finger: joint2 mimic declaration is missing")

    checks["tcp_frames_present"] = all(model.getFrameId(name) != model.nframes for name in EXPECTED_TCP)
    if not checks["tcp_frames_present"]:
        failures.append("tcp: hand_tcp frame is missing")
    checks["collision_objects_present"] = len(geometry.geometryObjects) > 0
    checks["collision_pairs_can_be_generated"] = len(geometry.collisionPairs) > 0
    if not checks["collision_objects_present"] or not checks["collision_pairs_can_be_generated"]:
        failures.append("collision: Pinocchio geometry or collision pairs are missing")


def assert_mounts(
    model: pin.Model,
    checks: dict[str, bool],
    failures: list[str],
) -> None:
    data = model.createData()
    q = pin.neutral(model)
    pin.forwardKinematics(model, data, q)
    pin.updateFramePlacements(model, data)
    observed = {}
    for link_name, expected in EXPECTED_MOUNTS.items():
        frame_id = model.getFrameId(link_name)
        observed[link_name] = data.oMf[frame_id].translation.copy()
    checks["dual_base_mounts_match_official_example"] = all(
        np.allclose(observed[name], expected, atol=1e-9)
        for name, expected in EXPECTED_MOUNTS.items()
    )
    if not checks["dual_base_mounts_match_official_example"]:
        failures.append("base: generated arm mounts do not match the recorded dual-example transforms")


def build_report(asset_dir: Path) -> dict[str, Any]:
    asset_dir = asset_dir.resolve()
    checks: dict[str, bool] = {}
    failures: list[str] = []
    urdf_path = asset_dir / URDF_RELATIVE
    srdf_path = asset_dir / "srdf" / "panda_bimanual.srdf"
    if not urdf_path.is_file():
        return {
            "schema_version": SCHEMA,
            "status": "FAIL",
            "checks": {"urdf_present": False},
            "failures": ["URDF is missing"],
            "absolute_paths_emitted": False,
        }
    checks["urdf_present"] = True
    if not srdf_path.is_file():
        checks["srdf_present"] = False
        failures.append("SRDF is missing")
        return {
            "schema_version": SCHEMA,
            "status": "FAIL",
            "checks": checks,
            "failures": failures,
            "absolute_paths_emitted": False,
        }
    checks["srdf_present"] = True
    try:
        root = parse_urdf(urdf_path)
        model = pin.buildModelFromUrdf(str(urdf_path))
        geometry = pin.buildGeomFromUrdf(
            model,
            str(urdf_path),
            pin.GeometryType.COLLISION,
            package_dirs=[str(asset_dir)],
        )
        geometry.addAllCollisionPairs()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        checks["pinocchio_load"] = False
        failures.append(f"Pinocchio load failed ({type(exc).__name__})")
        return {
            "schema_version": SCHEMA,
            "status": "FAIL",
            "checks": checks,
            "failures": failures,
            "absolute_paths_emitted": False,
        }
    checks["pinocchio_load"] = True
    references = assert_meshes(root, asset_dir, checks, failures)
    manifest = assert_manifest(asset_dir, urdf_path, srdf_path, references, checks, failures)
    assert_structure(root, model, geometry, checks, failures)
    assert_mounts(model, checks, failures)
    try:
        srdf_root = ET.parse(srdf_path).getroot()
        entries = [element for element in srdf_root.iter() if tag(element) == "disable_collisions"]
        checks["srdf_valid"] = tag(srdf_root) == "robot" and len(entries) == 68
        if not checks["srdf_valid"]:
            failures.append("SRDF: expected robot root and 68 collision-policy entries")
    except (OSError, ET.ParseError):
        checks["srdf_valid"] = False
        failures.append("SRDF: invalid XML")
    return {
        "schema_version": SCHEMA,
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failures": failures,
        "metrics": {
            "model_nq": model.nq,
            "model_nv": model.nv,
            "collision_object_count": len(geometry.geometryObjects),
            "collision_pair_count": len(geometry.collisionPairs),
            "mesh_count": len(references),
            "srdf_entry_count": 68 if checks.get("srdf_valid") else None,
            "asset_role": manifest.get("asset_role"),
        },
        "absolute_paths_emitted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-dir", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.asset_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
