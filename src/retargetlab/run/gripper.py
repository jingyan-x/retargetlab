"""Map canonical aperture streams to target gripper replay artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from retargetlab.contracts import (
    CanonicalTrajectory,
    RobotProfile,
    TargetGripperFrame,
    TargetGripperProfile,
    TargetGripperTrajectory,
)
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes


def map_target_grippers(
    trajectory: CanonicalTrajectory,
    profile: RobotProfile,
    stream_to_group: Mapping[str, str],
) -> TargetGripperTrajectory:
    """Map only canonical grippers to target joints; arm poses are not consumed."""

    if not stream_to_group:
        raise ValueError("stream_to_group must not be empty")
    if len(set(stream_to_group.values())) != len(stream_to_group):
        raise ValueError("each target group must have exactly one gripper stream")
    groups = {group.name: group for group in profile.groups}
    if set(stream_to_group.values()) != set(groups):
        raise ValueError("gripper bindings must cover every target robot group")
    trajectory_grippers = set(trajectory.frames[0].grippers)
    if set(stream_to_group) != trajectory_grippers:
        raise ValueError("gripper bindings must cover exactly the trajectory grippers")

    bindings: list[tuple[str, str, TargetGripperProfile]] = []
    for stream_name, group_name in stream_to_group.items():
        group = groups[group_name]
        if group.gripper is None:
            raise ValueError(f"target group has no gripper semantics: {group_name}")
        bindings.append((stream_name, group_name, group.gripper))

    frames: list[TargetGripperFrame] = []
    for frame in trajectory.frames:
        joint_positions: dict[str, float] = {}
        for stream_name, _, gripper in bindings:
            mapped = gripper.aperture_to_joint_positions(frame.grippers[stream_name])
            overlap = set(joint_positions).intersection(mapped)
            if overlap:
                raise ValueError(f"target gripper joint names overlap: {sorted(overlap)}")
            joint_positions.update(mapped)
        frames.append(
            TargetGripperFrame(
                timestamp_s=frame.timestamp_s,
                joint_positions=joint_positions,
            )
        )
    return TargetGripperTrajectory(
        robot_id=profile.robot_id,
        profile_sha256=sha256_bytes(canonical_json_bytes(profile)),
        group_names=tuple(group.name for group in profile.groups),
        frames=frames,
    )


def write_target_gripper_trajectory(
    path: Path,
    trajectory: TargetGripperTrajectory,
) -> TargetGripperTrajectory:
    """Write one exclusive target gripper replay artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(trajectory.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return trajectory
