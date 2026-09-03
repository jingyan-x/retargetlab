"""The single quaternion/SE(3) conversion boundary for RetargetLab.

All quaternions in this module use ``wxyz`` order.  No function here applies a
robot-specific frame mapping; those mappings belong in an explicit recipe or
adapter and must remain visible to callers.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


def _vector(values: Sequence[float] | NDArray[np.floating], size: int, name: str) -> FloatArray:
    array = np.asarray(values, dtype=float)
    if array.shape != (size,):
        raise ValueError(f"{name} must have shape ({size},), got {array.shape}")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    return array


def _rotation_matrix(matrix: Sequence[Sequence[float]] | NDArray[np.floating]) -> FloatArray:
    result = np.asarray(matrix, dtype=float)
    if result.shape != (3, 3):
        raise ValueError(f"rotation matrix must have shape (3, 3), got {result.shape}")
    if not np.all(np.isfinite(result)):
        raise ValueError("rotation matrix must contain only finite values")
    if not np.allclose(result.T @ result, np.eye(3), atol=1e-7):
        raise ValueError("rotation matrix is not orthonormal")
    if not math.isclose(float(np.linalg.det(result)), 1.0, abs_tol=1e-7):
        raise ValueError("rotation matrix determinant must be +1")
    return result


def normalize_quaternion_wxyz(
    quaternion: Sequence[float] | NDArray[np.floating],
    *,
    canonical_sign: bool = False,
) -> FloatArray:
    """Normalize one wxyz quaternion, optionally choosing a deterministic sign."""

    result = _vector(quaternion, 4, "quaternion_wxyz")
    norm = float(np.linalg.norm(result))
    if norm < 1e-12:
        raise ValueError("quaternion norm is too small")
    result = result / norm
    if canonical_sign and result[0] < 0.0:
        result = -result
    return result


def quaternion_wxyz_to_matrix(
    quaternion: Sequence[float] | NDArray[np.floating],
) -> FloatArray:
    """Convert a wxyz quaternion to a 3x3 active rotation matrix."""

    w, x, y, z = normalize_quaternion_wxyz(quaternion)
    return np.array(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=float,
    )


def matrix_to_quaternion_wxyz(
    matrix: Sequence[Sequence[float]] | NDArray[np.floating],
    *,
    canonical_sign: bool = True,
) -> FloatArray:
    """Convert a proper 3x3 rotation matrix to a normalized wxyz quaternion."""

    rotation = _rotation_matrix(matrix)
    trace = float(np.trace(rotation))
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        quaternion = np.array(
            [
                0.25 * scale,
                (rotation[2, 1] - rotation[1, 2]) / scale,
                (rotation[0, 2] - rotation[2, 0]) / scale,
                (rotation[1, 0] - rotation[0, 1]) / scale,
            ],
            dtype=float,
        )
    else:
        diagonal = np.diag(rotation)
        index = int(np.argmax(diagonal))
        if index == 0:
            scale = (
                math.sqrt(max(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2], 0.0)) * 2.0
            )
            quaternion = np.array(
                [
                    (rotation[2, 1] - rotation[1, 2]) / scale,
                    0.25 * scale,
                    (rotation[0, 1] + rotation[1, 0]) / scale,
                    (rotation[0, 2] + rotation[2, 0]) / scale,
                ],
                dtype=float,
            )
        elif index == 1:
            scale = (
                math.sqrt(max(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2], 0.0)) * 2.0
            )
            quaternion = np.array(
                [
                    (rotation[0, 2] - rotation[2, 0]) / scale,
                    (rotation[0, 1] + rotation[1, 0]) / scale,
                    0.25 * scale,
                    (rotation[1, 2] + rotation[2, 1]) / scale,
                ],
                dtype=float,
            )
        else:
            scale = (
                math.sqrt(max(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1], 0.0)) * 2.0
            )
            quaternion = np.array(
                [
                    (rotation[1, 0] - rotation[0, 1]) / scale,
                    (rotation[0, 2] + rotation[2, 0]) / scale,
                    (rotation[1, 2] + rotation[2, 1]) / scale,
                    0.25 * scale,
                ],
                dtype=float,
            )
    return normalize_quaternion_wxyz(quaternion, canonical_sign=canonical_sign)


def pose_to_se3(
    position_m: Sequence[float] | NDArray[np.floating],
    quaternion_wxyz: Sequence[float] | NDArray[np.floating],
) -> FloatArray:
    """Construct a homogeneous transform from position and wxyz orientation."""

    transform = np.eye(4, dtype=float)
    transform[:3, :3] = quaternion_wxyz_to_matrix(quaternion_wxyz)
    transform[:3, 3] = _vector(position_m, 3, "position_m")
    return transform


def se3_to_pose(
    transform: Sequence[Sequence[float]] | NDArray[np.floating],
    *,
    canonical_sign: bool = True,
) -> tuple[FloatArray, FloatArray]:
    """Decompose a homogeneous transform into position and wxyz orientation."""

    result = np.asarray(transform, dtype=float)
    if result.shape != (4, 4):
        raise ValueError(f"SE(3) transform must have shape (4, 4), got {result.shape}")
    if not np.all(np.isfinite(result)) or not np.allclose(
        result[3], [0.0, 0.0, 0.0, 1.0], atol=1e-8
    ):
        raise ValueError("invalid homogeneous transform")
    return result[:3, 3].copy(), matrix_to_quaternion_wxyz(
        result[:3, :3], canonical_sign=canonical_sign
    )


def compose_se3(first: NDArray[np.floating], second: NDArray[np.floating]) -> FloatArray:
    """Compose two validated homogeneous transforms."""

    first_pose = se3_to_pose(first)
    second_pose = se3_to_pose(second)
    return pose_to_se3(
        first_pose[0] + quaternion_wxyz_to_matrix(first_pose[1]) @ second_pose[0],
        matrix_to_quaternion_wxyz(
            quaternion_wxyz_to_matrix(first_pose[1]) @ quaternion_wxyz_to_matrix(second_pose[1])
        ),
    )


def inverse_se3(transform: NDArray[np.floating]) -> FloatArray:
    """Invert a validated homogeneous transform."""

    position, quaternion = se3_to_pose(transform)
    rotation = quaternion_wxyz_to_matrix(quaternion)
    result = np.eye(4, dtype=float)
    result[:3, :3] = rotation.T
    result[:3, 3] = -rotation.T @ position
    return result


def quaternion_geodesic_angle_rad(
    first: Sequence[float] | NDArray[np.floating],
    second: Sequence[float] | NDArray[np.floating],
) -> float:
    """Return the sign-invariant shortest angle between two orientations."""

    first_unit = normalize_quaternion_wxyz(first)
    second_unit = normalize_quaternion_wxyz(second)
    dot = float(np.clip(abs(np.dot(first_unit, second_unit)), -1.0, 1.0))
    return 2.0 * math.acos(dot)


def make_quaternion_sign_continuous(
    quaternions: Sequence[Sequence[float]] | NDArray[np.floating],
) -> FloatArray:
    """Normalize a quaternion sequence and remove only q/-q sign jumps."""

    result = np.asarray(quaternions, dtype=float)
    if result.ndim != 2 or result.shape[1] != 4 or result.shape[0] == 0:
        raise ValueError("quaternions must have shape (M, 4) with M > 0")
    output = np.vstack([normalize_quaternion_wxyz(row) for row in result])
    for index in range(1, len(output)):
        if float(np.dot(output[index - 1], output[index])) < 0.0:
            output[index] *= -1.0
    return output
