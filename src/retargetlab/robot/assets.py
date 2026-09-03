"""Portable robot-asset path and hash validation."""

from __future__ import annotations

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any

from retargetlab.contracts import RobotProfile


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_asset_file(asset_dir: Path, relative_or_absolute: str) -> Path:
    """Resolve a profile path without allowing it to escape its asset root."""

    candidate = Path(relative_or_absolute)
    if candidate.is_absolute():
        return candidate
    return (asset_dir / candidate).resolve()


def load_manifest(asset_dir: Path) -> dict[str, Any]:
    """Load an asset manifest as an object and reject non-object JSON."""

    manifest_path = asset_dir / "asset_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read asset manifest: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("asset manifest must be a JSON object")
    return manifest


def _mesh_path(asset_dir: Path, filename: str) -> Path:
    if filename.startswith("package://"):
        package_relative = filename.removeprefix("package://").split("/", 1)
        if len(package_relative) != 2:
            raise ValueError(f"invalid package mesh URI: {filename}")
        filename = package_relative[1]
    if Path(filename).is_absolute() or PurePosixPath(filename).is_absolute():
        raise ValueError(f"absolute mesh path is not portable: {filename}")
    relative = PurePosixPath(filename)
    if ".." in relative.parts:
        raise ValueError(f"mesh path escapes asset directory: {filename}")
    return (asset_dir / Path(*relative.parts)).resolve()


def validate_urdf_meshes(asset_dir: Path, urdf_path: Path) -> list[str]:
    """Validate every URDF mesh reference and return normalized filenames."""

    try:
        root = ET.parse(urdf_path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f"cannot parse URDF: {urdf_path}") from exc
    references: list[str] = []
    asset_root = asset_dir.resolve()
    for mesh in root.iter():
        if mesh.tag.rsplit("}", 1)[-1] != "mesh":
            continue
        filename = mesh.get("filename")
        if not filename:
            raise ValueError("URDF mesh element has no filename")
        resolved = _mesh_path(asset_root, filename)
        try:
            resolved.relative_to(asset_root)
        except ValueError as exc:
            raise ValueError(f"mesh path escapes asset directory: {filename}") from exc
        if not resolved.is_file():
            raise FileNotFoundError(f"URDF mesh is missing: {resolved}")
        references.append(filename)
    return references


def verify_profile_urdf(
    asset_dir: Path,
    urdf_path: Path,
    expected_hash: str,
) -> Path:
    """Verify one profile URDF hash and all portable mesh references."""

    if not urdf_path.is_file():
        raise FileNotFoundError(f"robot URDF does not exist: {urdf_path}")
    actual_hash = sha256_file(urdf_path)
    if actual_hash.lower() != expected_hash.lower():
        raise ValueError(
            f"URDF hash mismatch: expected {expected_hash.lower()}, got {actual_hash.lower()}"
        )
    validate_urdf_meshes(asset_dir, urdf_path)
    return urdf_path


def verify_urdf_manifest(asset_dir: Path, manifest: dict[str, Any]) -> Path:
    """Check the manifest's generated URDF path and recorded SHA-256."""

    raw_path = manifest.get("generated_urdf_path")
    expected_hash = manifest.get("generated_urdf_sha256")
    if not isinstance(raw_path, str) or not isinstance(expected_hash, str):
        raise ValueError("manifest is missing generated URDF path or hash")
    urdf_path = resolve_asset_file(asset_dir, raw_path)
    return verify_profile_urdf(asset_dir, urdf_path, expected_hash)


def _named_urdf_elements(root: ET.Element, tag: str) -> dict[str, ET.Element]:
    return {
        name: element
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == tag and (name := element.get("name")) is not None
    }


def _urdf_limit(joint: ET.Element, attribute: str) -> float:
    limit = next(
        (child for child in joint if child.tag.rsplit("}", 1)[-1] == "limit"),
        None,
    )
    if limit is None:
        raise ValueError(f"URDF joint has no limit: {joint.get('name')}")
    raw = limit.get(attribute)
    if raw is None:
        raise ValueError(f"URDF joint limit is missing {attribute}: {joint.get('name')}")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"URDF joint limit is not numeric: {joint.get('name')}") from exc
    if not math.isfinite(value):
        raise ValueError(f"URDF joint limit is not finite: {joint.get('name')}")
    return value


def verify_robot_profile_asset(profile: RobotProfile) -> Path:
    """Verify a profile's URDF/SRDF files and declared joint/frame semantics."""

    asset_dir = Path(profile.asset_dir).resolve()
    urdf_path = resolve_asset_file(asset_dir, profile.urdf_path)
    verify_profile_urdf(asset_dir, urdf_path, profile.urdf_sha256)
    try:
        root = ET.parse(urdf_path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f"cannot parse robot profile URDF: {urdf_path}") from exc
    links = _named_urdf_elements(root, "link")
    joints = _named_urdf_elements(root, "joint")
    if profile.root_frame not in links:
        raise ValueError(f"robot profile root frame is not a URDF link: {profile.root_frame}")
    frame_names = set(links) | set(joints)
    for group in profile.groups:
        if group.end_effector_frame not in frame_names:
            raise ValueError(
                f"robot profile end-effector frame is missing: {group.end_effector_frame}"
            )
        for joint_name in group.joint_names + group.gripper_joint_names:
            if joint_name not in joints:
                raise ValueError(f"robot profile joint is missing from URDF: {joint_name}")
        if group.gripper is None:
            continue
        driver = joints[group.gripper.driver_joint_name]
        if driver.get("type") != "prismatic":
            raise ValueError("target gripper driver joint must be prismatic")
        lower = _urdf_limit(driver, "lower")
        upper = _urdf_limit(driver, "upper")
        if not math.isclose(lower, group.gripper.driver_lower_m, abs_tol=1e-9):
            raise ValueError("target gripper lower limit does not match the URDF")
        if not math.isclose(upper, group.gripper.driver_upper_m, abs_tol=1e-9):
            raise ValueError("target gripper upper limit does not match the URDF")
        for mimic_profile in group.gripper.mimic_joints:
            mimic_joint = joints[mimic_profile.joint_name]
            if mimic_joint.get("type") != "prismatic":
                raise ValueError("target gripper mimic joint must be prismatic")
            mimic = next(
                (child for child in mimic_joint if child.tag.rsplit("}", 1)[-1] == "mimic"),
                None,
            )
            if mimic is None or mimic.get("joint") != group.gripper.driver_joint_name:
                raise ValueError("target gripper mimic relation does not match the URDF")
            multiplier = float(mimic.get("multiplier", "1.0"))
            offset = float(mimic.get("offset", "0.0"))
            if not math.isclose(multiplier, mimic_profile.multiplier, abs_tol=1e-12):
                raise ValueError("target gripper mimic multiplier does not match the URDF")
            if not math.isclose(offset, mimic_profile.offset_m, abs_tol=1e-12):
                raise ValueError("target gripper mimic offset does not match the URDF")

    collision = profile.collision
    if collision is not None and collision.srdf_path is not None:
        srdf_path = resolve_asset_file(asset_dir, collision.srdf_path)
        if not srdf_path.is_file():
            raise FileNotFoundError(f"robot profile SRDF does not exist: {srdf_path}")
        if collision.srdf_sha256 is not None:
            actual_hash = sha256_file(srdf_path)
            if actual_hash.lower() != collision.srdf_sha256.lower():
                raise ValueError("robot profile SRDF hash does not match the profile")
        try:
            srdf_root = ET.parse(srdf_path).getroot()
        except (OSError, ET.ParseError) as exc:
            raise ValueError(f"cannot parse robot profile SRDF: {srdf_path}") from exc
        if srdf_root.tag.rsplit("}", 1)[-1] != "robot":
            raise ValueError("robot profile SRDF root is not robot")
    return urdf_path
