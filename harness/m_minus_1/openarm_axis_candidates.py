"""Deterministic data-only OpenArm frame candidates.

The helpers in this module deliberately operate on pose components instead of
robot-specific objects.  A candidate is a proper right-handed axis rotation
followed by an optional full-pose inversion; the same rigid rotation is
applied to both the translation and the rotation matrix.  The target-base
transform is then applied to both components as well.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

import numpy as np

PoseDirection = Literal["forward", "inverse"]


@dataclass(frozen=True)
class AxisRotation:
    """One signed permutation matrix with determinant +1."""

    index: int
    permutation: tuple[int, int, int]
    signs: tuple[int, int, int]
    matrix: tuple[tuple[int, int, int], ...]
    rotation_id: str


@dataclass(frozen=True)
class RigidCandidate:
    """A deterministic, value-free description of one evaluated candidate."""

    candidate_id: str
    rotation_id: str
    pose_direction: PoseDirection
    target_frame: str
    side_mapping: Literal["direct", "swapped"]
    base_candidate_id: str
    axis_matrix: tuple[tuple[int, int, int], ...]
    candidate_hash: str


def _matrix_from_signed_permutation(
    permutation: tuple[int, int, int],
    signs: tuple[int, int, int],
) -> np.ndarray:
    matrix = np.zeros((3, 3), dtype=int)
    for row, (column, sign) in enumerate(zip(permutation, signs)):
        matrix[row, column] = sign
    return matrix


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def enumerate_axis_rotations() -> tuple[AxisRotation, ...]:
    """Return all 24 proper signed axis permutations in deterministic order."""

    rotations: list[AxisRotation] = []
    for permutation in itertools.permutations(range(3)):
        for signs in itertools.product((-1, 1), repeat=3):
            matrix = _matrix_from_signed_permutation(permutation, signs)
            if round(float(np.linalg.det(matrix))) != 1:
                continue
            index = len(rotations)
            sign_text = "".join("p" if sign > 0 else "n" for sign in signs)
            rotation_id = (
                f"axis-{index:02d}-perm{''.join(str(item) for item in permutation)}-"
                f"sign{sign_text}"
            )
            rotations.append(
                AxisRotation(
                    index=index,
                    permutation=permutation,
                    signs=signs,
                    matrix=tuple(tuple(int(item) for item in row) for row in matrix),
                    rotation_id=rotation_id,
                )
            )
    if len(rotations) != 24:
        raise AssertionError("proper signed axis permutations must contain 24 rotations")
    return tuple(rotations)


def pose_components(
    position: Iterable[float],
    rotation: Iterable[Iterable[float]],
) -> tuple[np.ndarray, np.ndarray]:
    """Validate and copy a finite position/rotation pair."""

    position_array = np.asarray(tuple(position), dtype=float)
    rotation_array = np.asarray(tuple(tuple(row) for row in rotation), dtype=float)
    if position_array.shape != (3,):
        raise ValueError("position must have shape (3,)")
    if rotation_array.shape != (3, 3):
        raise ValueError("rotation must have shape (3, 3)")
    if not np.all(np.isfinite(position_array)) or not np.all(np.isfinite(rotation_array)):
        raise ValueError("pose components must be finite")
    return position_array, rotation_array


def apply_rigid_candidate(
    position: Iterable[float],
    rotation: Iterable[Iterable[float]],
    *,
    base_rotation: Iterable[Iterable[float]],
    base_translation: Iterable[float],
    axis_rotation: AxisRotation | np.ndarray,
    pose_direction: PoseDirection,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply a data-only candidate to both pose position and orientation.

    ``pose_direction=inverse`` inverts the complete SE(3) pose, including its
    translation.  The axis rotation is a world-frame coordinate rotation, so
    it left-multiplies both the source position and source orientation before
    the target-base transform.  This is the concrete implementation of the
    rigid lineage ``T_base_from_source * T_source_eef * T_source_eef_to_tool``
    for the data-only axis candidates; the recorded source TCP offset is
    already baked into the dataset EEF reference and is therefore not added a
    second time.
    """

    if pose_direction not in ("forward", "inverse"):
        raise ValueError(f"unknown pose direction: {pose_direction}")
    source_position, source_rotation = pose_components(position, rotation)
    target_base_rotation = np.asarray(
        tuple(tuple(row) for row in base_rotation), dtype=float
    )
    target_base_translation = np.asarray(tuple(base_translation), dtype=float)
    if target_base_rotation.shape != (3, 3) or target_base_translation.shape != (3,):
        raise ValueError("base transform has an invalid shape")
    if isinstance(axis_rotation, AxisRotation):
        axis = np.asarray(axis_rotation.matrix, dtype=float)
    else:
        axis = np.asarray(axis_rotation, dtype=float)
    if axis.shape != (3, 3):
        raise ValueError("axis rotation must have shape (3, 3)")
    if pose_direction == "inverse":
        source_position = -source_rotation.T @ source_position
        source_rotation = source_rotation.T
    mapped_position = target_base_rotation @ (axis @ source_position) + target_base_translation
    mapped_rotation = target_base_rotation @ axis @ source_rotation
    return mapped_position, mapped_rotation


def _proper_rotation_matrix(
    value: AxisRotation | Iterable[Iterable[float]],
    *,
    name: str,
) -> np.ndarray:
    """Return one finite, orthonormal, right-handed rotation matrix."""

    matrix = np.asarray(
        value.matrix if isinstance(value, AxisRotation) else tuple(tuple(row) for row in value),
        dtype=float,
    )
    if matrix.shape != (3, 3):
        raise ValueError(f"{name} must have shape (3, 3)")
    if not np.all(np.isfinite(matrix)):
        raise ValueError(f"{name} must be finite")
    if not np.allclose(matrix.T @ matrix, np.eye(3), atol=1e-8):
        raise ValueError(f"{name} must be orthonormal")
    if not np.isclose(np.linalg.det(matrix), 1.0, atol=1e-8):
        raise ValueError(f"{name} must be right-handed")
    return matrix


def apply_separated_frame_candidate(
    position: Iterable[float],
    rotation: Iterable[Iterable[float]],
    *,
    base_rotation: Iterable[Iterable[float]],
    base_translation: Iterable[float],
    world_rotation: AxisRotation | Iterable[Iterable[float]],
    tool_rotation: AxisRotation | Iterable[Iterable[float]],
    pose_direction: PoseDirection,
) -> tuple[np.ndarray, np.ndarray]:
    """Map one source pose with independent world and tool rotations.

    ``world_rotation`` changes the source coordinate basis and therefore
    left-multiplies both position and orientation. ``tool_rotation`` changes
    only the source-TCP to target-TCP convention and therefore right-multiplies
    orientation without rotating the already-recorded TCP reference point.
    The target-base transform is applied last.
    """

    if pose_direction not in ("forward", "inverse"):
        raise ValueError(f"unknown pose direction: {pose_direction}")
    source_position, source_rotation = pose_components(position, rotation)
    target_base_rotation = _proper_rotation_matrix(
        base_rotation, name="base_rotation"
    )
    target_base_translation = np.asarray(tuple(base_translation), dtype=float)
    if target_base_translation.shape != (3,) or not np.all(
        np.isfinite(target_base_translation)
    ):
        raise ValueError("base_translation must be a finite shape-(3,) vector")
    world = _proper_rotation_matrix(world_rotation, name="world_rotation")
    tool = _proper_rotation_matrix(tool_rotation, name="tool_rotation")
    if pose_direction == "inverse":
        source_position = -source_rotation.T @ source_position
        source_rotation = source_rotation.T
    mapped_position = (
        target_base_rotation @ (world @ source_position) + target_base_translation
    )
    mapped_rotation = target_base_rotation @ world @ source_rotation @ tool
    return mapped_position, mapped_rotation


def make_candidate(
    *,
    axis_rotation: AxisRotation,
    pose_direction: PoseDirection,
    target_frame: str,
    side_mapping: Literal["direct", "swapped"],
    base_candidate_id: str,
) -> RigidCandidate:
    """Build a stable ID and SHA-256 for an evaluated candidate."""

    if pose_direction not in ("forward", "inverse"):
        raise ValueError(f"unknown pose direction: {pose_direction}")
    if side_mapping not in ("direct", "swapped"):
        raise ValueError(f"unknown side mapping: {side_mapping}")
    descriptor = {
        "axis_matrix": axis_rotation.matrix,
        "base_candidate_id": base_candidate_id,
        "pose_direction": pose_direction,
        "rotation_id": axis_rotation.rotation_id,
        "side_mapping": side_mapping,
        "target_frame": target_frame,
    }
    candidate_hash = hashlib.sha256(_canonical_json(descriptor).encode("utf-8")).hexdigest()
    candidate_id = (
        f"{base_candidate_id}__{axis_rotation.rotation_id}__{pose_direction}__"
        f"{target_frame}__{side_mapping}"
    )
    return RigidCandidate(
        candidate_id=candidate_id,
        rotation_id=axis_rotation.rotation_id,
        pose_direction=pose_direction,
        target_frame=target_frame,
        side_mapping=side_mapping,
        base_candidate_id=base_candidate_id,
        axis_matrix=axis_rotation.matrix,
        candidate_hash=candidate_hash,
    )


def enumerate_candidates(
    *,
    target_frames: Iterable[str],
    side_mapping: Literal["direct", "swapped"] = "direct",
    base_candidate_id: str = "t2-023",
) -> tuple[RigidCandidate, ...]:
    """Enumerate rotations × pose directions × target frames deterministically."""

    candidates = [
        make_candidate(
            axis_rotation=axis_rotation,
            pose_direction=pose_direction,
            target_frame=target_frame,
            side_mapping=side_mapping,
            base_candidate_id=base_candidate_id,
        )
        for target_frame in target_frames
        for pose_direction in ("forward", "inverse")
        for axis_rotation in enumerate_axis_rotations()
    ]
    return tuple(candidates)


def candidate_set_hash(candidates: Iterable[RigidCandidate]) -> str:
    """Hash only deterministic candidate descriptors, never private values."""

    descriptors = [
        {
            "axis_matrix": candidate.axis_matrix,
            "base_candidate_id": candidate.base_candidate_id,
            "candidate_hash": candidate.candidate_hash,
            "candidate_id": candidate.candidate_id,
            "pose_direction": candidate.pose_direction,
            "rotation_id": candidate.rotation_id,
            "side_mapping": candidate.side_mapping,
            "target_frame": candidate.target_frame,
        }
        for candidate in candidates
    ]
    return hashlib.sha256(_canonical_json(descriptors).encode("utf-8")).hexdigest()
