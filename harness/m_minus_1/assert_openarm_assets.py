"""Assert the generated OpenArm asset bundle for the disposable M-1 harness.

This script is intentionally independent of src/. It checks the generated
URDF and its bundled meshes, then exercises the same Pinocchio model used by
the later kinematic harness. Output is machine-readable and omits absolute
paths so that it is safe to attach to a run report.
"""

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

ASSERTION_SCHEMA = "m_minus_1.openarm_asset_assertions.v1"
DEFAULT_URDF = Path("urdf/openarm_bimanual_v10.urdf")
EXPECTED_SIDES = ("left", "right")
EXPECTED_FINGER_LIMIT = (0.0, 0.044)
MIN_FINGER_SPACING_CHANGE_M = 0.001
MIN_COLLISION_SPHERE_RADIUS_M = 0.001


def local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_elements(root: ET.Element, tag: str) -> list[ET.Element]:
    return [element for element in root.iter() if local_tag(element) == tag]


def is_absolute_mesh_reference(filename: str) -> bool:
    return (
        PurePosixPath(filename).is_absolute()
        or PureWindowsPath(filename).is_absolute()
        or bool(PureWindowsPath(filename).drive)
    )


def check_manifest(
    asset_dir: Path,
    urdf_path: Path,
    mesh_references: set[str],
    checks: dict[str, bool],
    failures: list[str],
) -> None:
    manifest_path = asset_dir / "asset_manifest.json"
    if not manifest_path.is_file():
        checks["manifest_present"] = False
        failures.append("manifest: asset_manifest.json is missing")
        return

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        checks["manifest_present"] = True
        checks["manifest_valid_json"] = False
        failures.append("manifest: invalid JSON")
        return

    checks["manifest_present"] = True
    checks["manifest_valid_json"] = True
    if manifest.get("schema_version") != "m_minus_1.openarm_assets.v1":
        checks["manifest_schema"] = False
        failures.append("manifest: unexpected schema version")
    else:
        checks["manifest_schema"] = True

    manifest_paths = manifest.get("mesh_paths")
    if not isinstance(manifest_paths, list) or set(manifest_paths) != mesh_references:
        checks["manifest_mesh_inventory"] = False
        failures.append("manifest: mesh inventory does not match the URDF")
    else:
        checks["manifest_mesh_inventory"] = True

    if manifest.get("mesh_count") != len(mesh_references):
        checks["manifest_mesh_count"] = False
        failures.append("manifest: mesh count does not match the URDF")
    else:
        checks["manifest_mesh_count"] = True

    generated_hash = manifest.get("generated_urdf_sha256")
    try:
        hash_matches = generated_hash == sha256_file(urdf_path)
    except OSError:
        hash_matches = False
    checks["manifest_urdf_hash"] = hash_matches
    if not hash_matches:
        failures.append("manifest: generated URDF hash mismatch")


def check_meshes(
    root: ET.Element,
    urdf_path: Path,
    asset_dir: Path,
    checks: dict[str, bool],
    failures: list[str],
) -> tuple[set[str], int, int]:
    mesh_references: set[str] = set()
    collision_mesh_count = 0
    collision_geometry_count = 0
    collision_sphere_count = 0

    for mesh in iter_elements(root, "mesh"):
        filename = mesh.get("filename")
        if not filename:
            failures.append("mesh: a mesh element has no filename")
            continue
        normalized = filename.replace("\\", "/")
        relative = PurePosixPath(normalized)
        mesh_references.add(normalized)
        if "://" in normalized:
            failures.append("mesh: URI references are not portable")
            continue
        if is_absolute_mesh_reference(normalized):
            failures.append("mesh: absolute references are not portable")
            continue
        if ".." in relative.parts or not normalized.startswith("meshes/"):
            failures.append("mesh: reference escapes the bundled meshes tree")
            continue
        resolved = (asset_dir / Path(*relative.parts)).resolve()
        try:
            resolved.relative_to(asset_dir)
        except ValueError:
            failures.append("mesh: reference resolves outside the asset bundle")
            continue
        if not resolved.is_file():
            failures.append(f"mesh: bundled file is missing ({normalized})")

    for collision in iter_elements(root, "collision"):
        geometry = next(
            (child for child in collision if local_tag(child) == "geometry"),
            None,
        )
        if geometry is None:
            failures.append("collision: a collision element has no geometry")
            continue
        for shape in geometry:
            shape_tag = local_tag(shape)
            if shape_tag == "mesh":
                collision_mesh_count += 1
                collision_geometry_count += 1
            elif shape_tag == "sphere":
                collision_sphere_count += 1
                collision_geometry_count += 1
                try:
                    radius = float(shape.get("radius", "nan"))
                except ValueError:
                    radius = math.nan
                if not math.isfinite(radius) or radius < MIN_COLLISION_SPHERE_RADIUS_M:
                    failures.append("collision: sub-millimeter sphere placeholder found")
            else:
                collision_geometry_count += 1

    checks["mesh_references_relative"] = not any(
        failure.startswith("mesh:") for failure in failures
    )
    checks["mesh_files_present"] = (
        checks["mesh_references_relative"]
        and all(
            (asset_dir / Path(*PurePosixPath(reference).parts)).is_file()
            for reference in mesh_references
            if "://" not in reference
            and not is_absolute_mesh_reference(reference)
            and ".." not in PurePosixPath(reference).parts
        )
    )
    checks["collision_geometry_present"] = collision_geometry_count > 0
    checks["collision_meshes_present"] = collision_mesh_count > 0
    checks["collision_placeholders_absent"] = not any(
        "sub-millimeter sphere placeholder" in failure for failure in failures
    )
    if not checks["collision_geometry_present"]:
        failures.append("collision: no collision geometry found")
    if not checks["collision_meshes_present"]:
        failures.append("collision: no mesh geometry found")

    return mesh_references, collision_mesh_count, collision_sphere_count


def check_fingers_and_tcp(
    root: ET.Element,
    checks: dict[str, bool],
    failures: list[str],
) -> None:
    links = {
        element.get("name")
        for element in iter_elements(root, "link")
        if element.get("name")
    }
    joints = {
        element.get("name"): element
        for element in iter_elements(root, "joint")
        if element.get("name")
    }

    for side in EXPECTED_SIDES:
        finger1_name = f"openarm_{side}_finger_joint1"
        finger2_name = f"openarm_{side}_finger_joint2"
        finger1 = joints.get(finger1_name)
        finger2 = joints.get(finger2_name)
        if finger1 is None or finger2 is None:
            failures.append(f"finger: missing {side} finger joints")
            continue

        for joint_name, joint in ((finger1_name, finger1), (finger2_name, finger2)):
            if joint.get("type") != "prismatic":
                failures.append(f"finger: {joint_name} is not prismatic")
            limit = joint.find("limit")
            if limit is None:
                failures.append(f"finger: {joint_name} has no limits")
                continue
            try:
                lower = float(limit.get("lower", "nan"))
                upper = float(limit.get("upper", "nan"))
            except ValueError:
                lower, upper = math.nan, math.nan
            if not (
                math.isclose(lower, EXPECTED_FINGER_LIMIT[0], abs_tol=1e-9)
                and math.isclose(upper, EXPECTED_FINGER_LIMIT[1], abs_tol=1e-9)
            ):
                failures.append(f"finger: {joint_name} has unexpected limits")

        if finger1.find("mimic") is not None:
            failures.append(f"finger: {finger1_name} must be the independent joint")
        mimic = finger2.find("mimic")
        if mimic is None or mimic.get("joint") != finger1_name:
            failures.append(f"finger: {finger2_name} does not mimic {finger1_name}")

        tcp_link = f"openarm_{side}_hand_tcp"
        tcp_joint = f"openarm_{side}_hand_tcp_joint"
        if tcp_link not in links:
            failures.append(f"tcp: missing {tcp_link}")
        joint = joints.get(tcp_joint)
        if joint is None:
            failures.append(f"tcp: missing {tcp_joint}")
        else:
            parent = joint.find("parent")
            child = joint.find("child")
            if (
                joint.get("type") != "fixed"
                or parent is None
                or child is None
                or child.get("link") != tcp_link
            ):
                failures.append(f"tcp: {tcp_joint} is not a fixed TCP link")

    checks["finger_joint_contract"] = not any(
        failure.startswith("finger:") for failure in failures
    )
    checks["tcp_contract"] = not any(
        failure.startswith("tcp:") for failure in failures
    )


def check_pinocchio(
    urdf_path: Path,
    asset_dir: Path,
    checks: dict[str, bool],
    failures: list[str],
    metrics: dict[str, Any],
) -> None:
    try:
        model = pin.buildModelFromUrdf(str(urdf_path))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        checks["pinocchio_model_load"] = False
        failures.append(f"pinocchio: model load failed ({type(exc).__name__})")
        return

    checks["pinocchio_model_load"] = True
    metrics["pinocchio_nq"] = int(model.nq)
    metrics["pinocchio_nv"] = int(model.nv)
    arm_joint_count = sum(
        name.startswith(("openarm_left_joint", "openarm_right_joint"))
        for name in model.names
    )
    metrics["pinocchio_arm_joint_count"] = arm_joint_count
    checks["pinocchio_arm_joint_count"] = arm_joint_count == 14
    if not checks["pinocchio_arm_joint_count"]:
        failures.append("pinocchio: expected 14 revolute arm joints")

    expected_model_joints = [
        f"openarm_{side}_finger_joint{index}"
        for side in EXPECTED_SIDES
        for index in (1, 2)
    ]
    missing_model_joints = [
        name for name in expected_model_joints if name not in model.names
    ]
    checks["pinocchio_finger_joints"] = not missing_model_joints
    if missing_model_joints:
        failures.append("pinocchio: finger joints missing from the model")

    try:
        geometry_model = pin.buildGeomFromUrdf(
            model,
            str(urdf_path),
            pin.GeometryType.COLLISION,
            package_dirs=[str(asset_dir)],
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        checks["pinocchio_collision_load"] = False
        failures.append(
            f"pinocchio: collision geometry load failed ({type(exc).__name__})"
        )
    else:
        collision_objects = len(geometry_model.geometryObjects)
        metrics["pinocchio_collision_object_count"] = collision_objects
        checks["pinocchio_collision_load"] = collision_objects > 0
        if collision_objects == 0:
            failures.append("pinocchio: no collision objects were loaded")

    if not checks["pinocchio_finger_joints"]:
        return

    try:
        data = model.createData()
        frame_ids = {
            side: (
                model.getFrameId(f"openarm_{side}_left_finger"),
                model.getFrameId(f"openarm_{side}_right_finger"),
            )
            for side in EXPECTED_SIDES
        }
        q_by_endpoint: dict[float, np.ndarray] = {}
        for endpoint in EXPECTED_FINGER_LIMIT:
            q = pin.neutral(model)
            for side in EXPECTED_SIDES:
                for index in (1, 2):
                    joint_id = model.getJointId(
                        f"openarm_{side}_finger_joint{index}"
                    )
                    q_index = int(model.idx_qs[joint_id])
                    q[q_index] = endpoint
            q_by_endpoint[endpoint] = q

        spacings: dict[str, list[float]] = {}
        for endpoint, q in q_by_endpoint.items():
            pin.forwardKinematics(model, data, q)
            pin.updateFramePlacements(model, data)
            for side, (left_frame, right_frame) in frame_ids.items():
                if (
                    left_frame < 0
                    or right_frame < 0
                    or left_frame >= len(model.frames)
                    or right_frame >= len(model.frames)
                ):
                    raise ValueError("finger link frame is missing")
                left_position = data.oMf[left_frame].translation
                right_position = data.oMf[right_frame].translation
                spacing = float(np.linalg.norm(left_position - right_position))
                current = spacings.setdefault(side, [math.nan, math.nan])
                current[0 if endpoint == EXPECTED_FINGER_LIMIT[0] else 1] = spacing

        motion_passed = True
        for side, (open_spacing, closed_spacing) in spacings.items():
            delta = abs(closed_spacing - open_spacing)
            metrics[f"{side}_finger_spacing_open_m"] = open_spacing
            metrics[f"{side}_finger_spacing_closed_m"] = closed_spacing
            metrics[f"{side}_finger_spacing_change_m"] = delta
            motion_passed = motion_passed and delta >= MIN_FINGER_SPACING_CHANGE_M
        checks["pinocchio_finger_motion"] = motion_passed
        if not motion_passed:
            failures.append("pinocchio: finger spacing does not change by 1 mm")
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        checks["pinocchio_finger_motion"] = False
        failures.append(f"pinocchio: finger motion check failed ({type(exc).__name__})")


def build_report(asset_dir: Path) -> dict[str, Any]:
    asset_dir = asset_dir.resolve()
    urdf_path = asset_dir / DEFAULT_URDF
    checks: dict[str, bool] = {}
    failures: list[str] = []
    metrics: dict[str, Any] = {}

    if not urdf_path.is_file():
        checks["urdf_present"] = False
        failures.append("urdf: generated URDF is missing")
        return {
            "schema_version": ASSERTION_SCHEMA,
            "status": "FAIL",
            "checks": checks,
            "failures": failures,
            "metrics": metrics,
            "absolute_paths_emitted": False,
        }
    checks["urdf_present"] = True

    try:
        root = ET.parse(urdf_path).getroot()
    except (OSError, ET.ParseError):
        checks["urdf_xml_parse"] = False
        failures.append("urdf: XML parse failed")
        return {
            "schema_version": ASSERTION_SCHEMA,
            "status": "FAIL",
            "checks": checks,
            "failures": failures,
            "metrics": metrics,
            "absolute_paths_emitted": False,
        }
    checks["urdf_xml_parse"] = True
    metrics["link_count"] = len(iter_elements(root, "link"))
    metrics["joint_count"] = len(iter_elements(root, "joint"))

    mesh_references, collision_mesh_count, collision_sphere_count = check_meshes(
        root, urdf_path, asset_dir, checks, failures
    )
    metrics["mesh_count"] = len(mesh_references)
    metrics["collision_mesh_count"] = collision_mesh_count
    metrics["collision_sphere_count"] = collision_sphere_count
    check_manifest(asset_dir, urdf_path, mesh_references, checks, failures)
    check_fingers_and_tcp(root, checks, failures)
    check_pinocchio(urdf_path, asset_dir, checks, failures, metrics)

    return {
        "schema_version": ASSERTION_SCHEMA,
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failures": failures,
        "metrics": metrics,
        "absolute_paths_emitted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build_report(args.asset_dir)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        report = {
            "schema_version": ASSERTION_SCHEMA,
            "status": "ERROR",
            "checks": {},
            "failures": [f"assertion harness failed ({type(exc).__name__})"],
            "metrics": {},
            "absolute_paths_emitted": False,
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

