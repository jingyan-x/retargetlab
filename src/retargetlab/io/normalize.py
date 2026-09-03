"""Narrow, explicit row normalization into CanonicalTrajectory v0.1."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from retargetlab.contracts import CanonicalFrame, CanonicalTrajectory, MappingSpec, Pose
from retargetlab.kinematics.transforms import normalize_quaternion_wxyz


class NormalizationError(ValueError):
    """The source rows do not satisfy the explicit pose-only mapping."""


def _read_values(row: Mapping[str, object], reference_source: str) -> np.ndarray:
    if reference_source not in row:
        raise NormalizationError(f"source field is missing from row: {reference_source}")
    try:
        values = np.asarray(row[reference_source], dtype=float)
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"source field is not numeric: {reference_source}") from exc
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
    if orientation.quaternion_order != "wxyz" or orientation.frame != spec.coordinate_frame:
        raise NormalizationError(
            f"{stream_name}.orientation must explicitly declare wxyz and the mapping frame"
        )
    return position, orientation


def normalize_rows(
    rows: Sequence[Mapping[str, object]],
    spec: MappingSpec,
) -> CanonicalTrajectory:
    """Normalize mapped pose rows, preserving stream roles and quaternion signs."""

    if not rows:
        raise NormalizationError("cannot normalize an empty row sequence")
    stream_refs = {stream.name: _pose_refs(spec, stream.name) for stream in spec.streams}
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
        frames.append(CanonicalFrame(timestamp_s=timestamp, poses=poses))
    return CanonicalTrajectory(
        coordinate_frame=spec.coordinate_frame,
        frames=frames,
        metadata={
            "normalizer": "retargetlab.io.normalize.pose_only.v0.1",
            "dataset_alias": spec.dataset_alias,
            "source_revision": spec.source_revision,
        },
    )
