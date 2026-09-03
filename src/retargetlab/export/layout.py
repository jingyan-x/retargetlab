"""Build deterministic target-side vector layouts from a RobotProfile."""

from __future__ import annotations

from retargetlab.contracts import ExportProfile, RobotProfile, TargetVectorLayout
from retargetlab.contracts.export_profile import JointUnit
from retargetlab.robot.assets import verify_robot_profile_asset
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes


def build_target_vector_layout(profile: RobotProfile) -> TargetVectorLayout:
    """Build the explicit arm-first, group-ordered target joint layout."""

    names: list[str] = []
    units: list[JointUnit] = []
    group_names = tuple(group.name for group in profile.groups)
    for group in profile.groups:
        names.extend(group.joint_names)
        units.extend("rad" for _ in group.joint_names)
        if group.gripper is None:
            if group.gripper_joint_names:
                raise ValueError(
                    f"target group has gripper joints but no explicit semantics: {group.name}"
                )
            continue
        names.append(group.gripper.driver_joint_name)
        units.append("m")
    return TargetVectorLayout(
        group_names=group_names,
        names=tuple(names),
        units=tuple(units),
    )


def build_export_profile(
    profile: RobotProfile,
    *,
    normalization_exclude: tuple[str, ...] = (),
) -> ExportProfile:
    """Verify assets and build a target layout bound to the profile hash."""

    verify_robot_profile_asset(profile)
    return ExportProfile(
        robot_id=profile.robot_id,
        robot_profile_sha256=sha256_bytes(canonical_json_bytes(profile)),
        target_layout=build_target_vector_layout(profile),
        normalization_exclude=normalization_exclude,
    )
