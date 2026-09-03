"""Formal OpenArm bimanual profile built from the versioned asset bundle."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

from retargetlab.contracts import (
    CollisionProfile,
    KinematicGroup,
    MimicJoint,
    RobotProfile,
    TargetGripperProfile,
)

from .assets import load_manifest, resolve_asset_file, sha256_file, verify_profile_urdf

DEFAULT_URDF_PATH = "urdf/openarm_bimanual_v10.urdf"
DEFAULT_ROOT_FRAME = "world"
OPENARM_SIDES = ("left", "right")
OPENARM_FINGER_LIMIT_M = (0.0, 0.044)
OPENARM_HAND_OFFSET_M = 0.1001
OPENARM_TCP_OFFSET_M = 0.08


def _parse_urdf(urdf_path: Path) -> ET.Element:
    try:
        root = ET.parse(urdf_path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f"cannot parse OpenArm URDF: {urdf_path}") from exc
    if root.tag.rsplit("}", 1)[-1] != "robot":
        raise ValueError("OpenArm URDF root is not robot")
    return root


def _named_elements(root: ET.Element, tag: str) -> dict[str, ET.Element]:
    elements: dict[str, ET.Element] = {}
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != tag:
            continue
        name = element.get("name")
        if name:
            elements[name] = element
    return elements


def _float_attribute(element: ET.Element, name: str) -> float:
    raw = element.get(name)
    if raw is None:
        raise ValueError(f"OpenArm URDF element is missing {name}: {element.get('name')}")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"OpenArm URDF has a non-numeric {name}: {element.get('name')}") from exc
    if not math.isfinite(value):
        raise ValueError(f"OpenArm URDF has a non-finite {name}: {element.get('name')}")
    return value


def _validate_finger_joint(
    joints: dict[str, ET.Element],
    side: str,
    driver_name: str,
    mimic_name: str,
) -> None:
    driver = joints.get(driver_name)
    mimic = joints.get(mimic_name)
    if driver is None or mimic is None:
        raise ValueError(f"OpenArm {side} finger joints are missing")
    if driver.get("type") != "prismatic" or mimic.get("type") != "prismatic":
        raise ValueError(f"OpenArm {side} finger joints must be prismatic")
    lower, upper = OPENARM_FINGER_LIMIT_M
    for joint in (driver, mimic):
        limit = next(
            (child for child in joint if child.tag.rsplit("}", 1)[-1] == "limit"),
            None,
        )
        if limit is None:
            raise ValueError(f"OpenArm finger joint has no limit: {joint.get('name')}")
        if not math.isclose(_float_attribute(limit, "lower"), lower, abs_tol=1e-9):
            raise ValueError(f"OpenArm finger lower limit is not {lower}: {joint.get('name')}")
        if not math.isclose(_float_attribute(limit, "upper"), upper, abs_tol=1e-9):
            raise ValueError(f"OpenArm finger upper limit is not {upper}: {joint.get('name')}")
    mimic_element = next(
        (child for child in mimic if child.tag.rsplit("}", 1)[-1] == "mimic"),
        None,
    )
    if mimic_element is None or mimic_element.get("joint") != driver_name:
        raise ValueError(f"OpenArm mimic joint does not reference {driver_name}")
    multiplier = float(mimic_element.get("multiplier", "1.0"))
    offset = float(mimic_element.get("offset", "0.0"))
    if not math.isclose(multiplier, 1.0, abs_tol=1e-12) or not math.isclose(
        offset, 0.0, abs_tol=1e-12
    ):
        raise ValueError("OpenArm finger mimic must use multiplier=1 and offset=0")


def _validate_fixed_offset(
    joints: dict[str, ET.Element],
    name: str,
    parent: str,
    child: str,
    expected_z: float,
) -> None:
    joint = joints.get(name)
    if joint is None or joint.get("type") != "fixed":
        raise ValueError(f"OpenArm fixed joint is missing or has the wrong type: {name}")
    parent_element = next(
        (item for item in joint if item.tag.rsplit("}", 1)[-1] == "parent"),
        None,
    )
    child_element = next(
        (item for item in joint if item.tag.rsplit("}", 1)[-1] == "child"),
        None,
    )
    if parent_element is None or parent_element.get("link") != parent:
        raise ValueError(f"OpenArm fixed joint has an unexpected parent: {name}")
    if child_element is None or child_element.get("link") != child:
        raise ValueError(f"OpenArm fixed joint has an unexpected child: {name}")
    origin = next(
        (item for item in joint if item.tag.rsplit("}", 1)[-1] == "origin"),
        None,
    )
    if origin is None:
        raise ValueError(f"OpenArm fixed joint has no origin: {name}")
    xyz = origin.get("xyz", "").split()
    if len(xyz) != 3:
        raise ValueError(f"OpenArm fixed joint origin is incomplete: {name}")
    try:
        z = float(xyz[2])
    except ValueError as exc:
        raise ValueError(f"OpenArm fixed joint origin is non-numeric: {name}") from exc
    if not math.isclose(z, expected_z, abs_tol=1e-6):
        raise ValueError(f"OpenArm fixed joint offset is unexpected: {name}")


def _validate_openarm_structure(urdf_path: Path) -> None:
    root = _parse_urdf(urdf_path)
    links = _named_elements(root, "link")
    joints = _named_elements(root, "joint")
    required_links = {"world", "openarm_body_link0"}
    for side in OPENARM_SIDES:
        required_links.update({f"openarm_{side}_link{index}" for index in range(8)})
        required_links.update(
            {
                f"openarm_{side}_hand",
                f"openarm_{side}_hand_tcp",
                f"openarm_{side}_left_finger",
                f"openarm_{side}_right_finger",
            }
        )
    missing_links = sorted(required_links - set(links))
    if missing_links:
        raise ValueError(f"OpenArm URDF is missing links: {missing_links}")
    for side in OPENARM_SIDES:
        arm_joints = {f"openarm_{side}_joint{index}" for index in range(1, 8)}
        if arm_joints - set(joints):
            raise ValueError(f"OpenArm {side} arm joints are incomplete")
        _validate_finger_joint(
            joints,
            side,
            f"openarm_{side}_finger_joint1",
            f"openarm_{side}_finger_joint2",
        )
        _validate_fixed_offset(
            joints,
            f"{side}_openarm_hand_joint",
            f"openarm_{side}_link7",
            f"openarm_{side}_hand",
            OPENARM_HAND_OFFSET_M,
        )
        _validate_fixed_offset(
            joints,
            f"openarm_{side}_hand_tcp_joint",
            f"openarm_{side}_hand",
            f"openarm_{side}_hand_tcp",
            OPENARM_TCP_OFFSET_M,
        )


def _arm_joint_names(side: str) -> tuple[str, ...]:
    return tuple(f"openarm_{side}_joint{index}" for index in range(1, 8))


def _gripper_profile(side: str) -> TargetGripperProfile:
    driver = f"openarm_{side}_finger_joint1"
    return TargetGripperProfile(
        name=f"openarm_{side}_parallel_gripper",
        driver_joint_name=driver,
        mimic_joints=(MimicJoint(joint_name=f"openarm_{side}_finger_joint2"),),
        driver_lower_m=OPENARM_FINGER_LIMIT_M[0],
        driver_upper_m=OPENARM_FINGER_LIMIT_M[1],
    )


def load_openarm_bimanual_profile(asset_dir: Path) -> RobotProfile:
    """Build and validate the formal OpenArm bimanual target profile."""

    asset_dir = asset_dir.resolve()
    manifest = load_manifest(asset_dir)
    raw_urdf = manifest.get("generated_urdf_path", DEFAULT_URDF_PATH)
    expected_urdf_hash = manifest.get("generated_urdf_sha256")
    if not isinstance(raw_urdf, str) or not isinstance(expected_urdf_hash, str):
        raise ValueError("OpenArm manifest is missing generated URDF path or hash")
    urdf_path = resolve_asset_file(asset_dir, raw_urdf)
    verify_profile_urdf(asset_dir, urdf_path, expected_urdf_hash)
    _validate_openarm_structure(urdf_path)

    raw_srdf = manifest.get("srdf_path")
    expected_srdf_hash = manifest.get("srdf_sha256")
    if not isinstance(raw_srdf, str) or not isinstance(expected_srdf_hash, str):
        raise ValueError("OpenArm manifest is missing SRDF path or hash")
    srdf_path = resolve_asset_file(asset_dir, raw_srdf)
    if not srdf_path.is_file() or sha256_file(srdf_path).lower() != expected_srdf_hash.lower():
        raise ValueError("OpenArm SRDF is missing or its hash does not match the manifest")

    groups = tuple(
        KinematicGroup(
            name=f"openarm_{side}",
            joint_names=_arm_joint_names(side),
            end_effector_frame=f"openarm_{side}_hand_tcp",
            gripper_joint_names=_gripper_profile(side).joint_names,
            gripper=_gripper_profile(side),
        )
        for side in OPENARM_SIDES
    )
    collision = CollisionProfile(
        srdf_path=raw_srdf,
        srdf_sha256=expected_srdf_hash,
        allowed_contact_pairs=tuple(
            (
                f"openarm_{side}_left_finger",
                f"openarm_{side}_right_finger",
            )
            for side in OPENARM_SIDES
        ),
        required_barrier_pairs=(
            ("openarm_body_link0", "openarm_left_link0"),
            ("openarm_body_link0", "openarm_right_link0"),
        ),
        strategy="srdf",
    )
    return RobotProfile(
        robot_id="openarm_bimanual",
        asset_dir=str(asset_dir),
        urdf_path=str(urdf_path.relative_to(asset_dir)),
        urdf_sha256=expected_urdf_hash,
        root_frame=DEFAULT_ROOT_FRAME,
        groups=groups,
        collision=collision,
        metadata={
            "asset_role": str(manifest.get("asset_role", "target_robot")),
            "asset_manifest_schema": str(manifest.get("schema_version", "unknown")),
            "source_repository": str(manifest.get("source_repository", "unknown")),
            "source_revision": str(manifest.get("source_revision", "unknown")),
            "target_gripper_semantics": (
                "aperture_fraction_to_finger_joint1_m;finger_joint2_mimic"
            ),
            "end_effector_semantics": "hand_tcp",
        },
    )
