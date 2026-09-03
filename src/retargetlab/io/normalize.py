"""Narrow, explicit row normalization into CanonicalTrajectory v0.1."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from retargetlab.contracts import (
    AffineMap,
    CanonicalFrame,
    CanonicalTrajectory,
    GripperProfile,
    MappingSpec,
    Pose,
    ProfileChannel,
)
from retargetlab.kinematics.transforms import normalize_quaternion_wxyz


class NormalizationError(ValueError):
    """The source rows do not satisfy the explicit pose or gripper mapping."""


def _read_values(row: Mapping[str, object], reference_source: str) -> np.ndarray:
    if reference_source not in row:
        raise NormalizationError(f"source field is missing from row: {reference_source}")
    try:
        values = np.asarray(row[reference_source], dtype=float)
    except (TypeError, ValueError) as exc:
        raise NormalizationError(
            f"source field is not numeric: {reference_source}"
        ) from exc
    if not np.all(np.isfinite(values)):
        raise NormalizationError(f"source field contains non-finite values: {reference_source}")
    return values


def _read_ref(row: Mapping[str, object], reference: Any) -> float | np.ndarray:
    values = _read_values(row, reference.source)
    if reference.expected_shape is not None and values.shape != reference.expected_shape:
        raise NormalizationError(
            f"{reference.source}: expected shape {reference.expected_shape}, got {values.shape}"
        )
    if reference.indices:
        if values.ndim != 1:
            raise NormalizationError(f"indexed source must be one-dimensional: {reference.source}")
        if max(reference.indices) >= values.shape[0]:
            raise NormalizationError(f"index exceeds source width: {reference.source}")
        values = values[list(reference.indices)]
    if values.ndim == 0:
        return float(values)
    return values


def _pose_refs(spec: MappingSpec, stream_name: str) -> tuple[Any, Any]:
    stream = next(stream for stream in spec.streams if stream.name == stream_name)
    required = {"position", "orientation"}
    missing = required - set(stream.fields)
    if missing:
        raise NormalizationError(
            f"stream {stream_name!r} is missing canonical pose fields: {sorted(missing)}"
        )
    unsupported = set(stream.fields) - required
    if unsupported:
        raise NormalizationError(
            f"pose-only normalizer does not support fields: {sorted(unsupported)}"
        )
    position = stream.fields["position"]
    orientation = stream.fields["orientation"]
    if position.unit != "m" or position.frame != spec.coordinate_frame:
        raise NormalizationError(
            f"{stream_name}.position must declare unit=m and the mapping coordinate frame"
        )
    if (
        orientation.quaternion_order != "wxyz"
        or orientation.frame != spec.coordinate_frame
    ):
        raise NormalizationError(
            f"{stream_name}.orientation must explicitly declare wxyz and the mapping frame"
        )
    return position, orientation


def _slot_for_stream(stream_name: str) -> str:
    for slot in ("slot_0", "slot_1"):
        if stream_name.endswith(f".{slot}") or stream_name == slot:
            return slot
    raise NormalizationError(
        f"profile gripper mapping requires an explicit slot suffix: {stream_name}"
    )


def _gripper_bindings(
    spec: MappingSpec,
    grippers: Sequence[GripperProfile],
) -> dict[str, tuple[ProfileChannel, AffineMap]]:
    by_slot: dict[str, GripperProfile] = {
        gripper.slot: gripper for gripper in grippers
    }
    if len(by_slot) != len(grippers):
        raise NormalizationError("profile gripper slots must be unique")
    bindings: dict[str, tuple[ProfileChannel, AffineMap]] = {}
    for stream in spec.streams:
        slot = _slot_for_stream(stream.name)
        gripper = by_slot.get(slot)
        if gripper is None:
            raise NormalizationError(f"profile is missing gripper semantics for {slot}")
        position = stream.fields.get("position")
        if position is None:
            raise NormalizationError(f"stream {stream.name!r} is missing a pose position field")
        channel_pairs = (
            (gripper.observation_state, gripper.observation_to_aperture),
            (gripper.action, gripper.action_to_aperture),
            (gripper.reference_observation_state, gripper.observation_to_aperture),
            (gripper.reference_action, gripper.action_to_aperture),
        )
        matches = [
            (channel, affine)
            for channel, affine in channel_pairs
            if channel.stream == position.source
        ]
        if len(matches) != 1:
            raise NormalizationError(
                f"profile has no unique gripper channel for {stream.name!r} "
                f"source {position.source!r}"
            )
        bindings[stream.name] = matches[0]
    if set(by_slot) != {_slot_for_stream(name) for name in bindings}:
        raise NormalizationError("profile grippers do not cover the mapped streams")
    return bindings


def _read_gripper(
    row: Mapping[str, object],
    stream_name: str,
    channel: ProfileChannel,
    affine: AffineMap,
) -> float:
    values = _read_values(row, channel.stream)
    if values.ndim != 1 or channel.index >= values.shape[0]:
        raise NormalizationError(f"gripper channel index exceeds source vector: {stream_name}")
    aperture = affine.scale * float(values[channel.index]) + affine.offset
    if not math.isfinite(aperture) or not 0.0 <= aperture <= 1.0:
        raise NormalizationError(
            f"gripper aperture is outside [0, 1] after mapping: {stream_name}"
        )
    return aperture


def normalize_rows(
    rows: Sequence[Mapping[str, object]],
    spec: MappingSpec,
    *,
    grippers: Sequence[GripperProfile] = (),
) -> CanonicalTrajectory:
    """Normalize mapped pose rows and optional profile grippers."""

    if not rows:
        raise NormalizationError("cannot normalize an empty row sequence")
    stream_refs = {
        stream.name: _pose_refs(spec, stream.name) for stream in spec.streams
    }
    gripper_refs = _gripper_bindings(spec, grippers) if grippers else {}
    previous_quaternions: dict[str, np.ndarray] = {}
    frames: list[CanonicalFrame] = []
    for row_index, row in enumerate(rows):
        timestamp = _read_ref(row, spec.timestamp)
        if not isinstance(timestamp, float):
            raise NormalizationError("timestamp mapping must resolve to a scalar")
        poses: dict[str, Pose] = {}
        for stream_name, (position_ref, orientation_ref) in stream_refs.items():
            raw_position = _read_ref(row, position_ref)
            raw_orientation = _read_ref(row, orientation_ref)
            if not isinstance(raw_position, np.ndarray) or raw_position.shape != (3,):
                raise NormalizationError(
                    f"{stream_name}.position mapping must resolve to shape (3,)"
                )
            if not isinstance(raw_orientation, np.ndarray) or raw_orientation.shape != (4,):
                raise NormalizationError(
                    f"{stream_name}.orientation mapping must resolve to shape (4,)"
                )
            quaternion = normalize_quaternion_wxyz(raw_orientation)
            previous = previous_quaternions.get(stream_name)
            if previous is not None and float(np.dot(previous, quaternion)) < 0.0:
                quaternion = -quaternion
            previous_quaternions[stream_name] = quaternion
            poses[stream_name] = Pose(
                position_m=(
                    float(raw_position[0]),
                    float(raw_position[1]),
                    float(raw_position[2]),
                ),
                quaternion_wxyz=(
                    float(quaternion[0]),
                    float(quaternion[1]),
                    float(quaternion[2]),
                    float(quaternion[3]),
                ),
                frame=spec.coordinate_frame,
            )
        gripper_values = {
            stream_name: _read_gripper(row, stream_name, channel, affine)
            for stream_name, (channel, affine) in gripper_refs.items()
        }
        frames.append(
            CanonicalFrame(
                timestamp_s=timestamp,
                poses=poses,
                grippers=gripper_values,
            )
        )
    return CanonicalTrajectory(
        coordinate_frame=spec.coordinate_frame,
        frames=frames,
        metadata={
            "normalizer": (
                "retargetlab.io.normalize.pose_and_gripper.v0.1"
                if grippers
                else "retargetlab.io.normalize.pose_only.v0.1"
            ),
            "dataset_alias": spec.dataset_alias,
            "source_revision": spec.source_revision,
        },
    )
