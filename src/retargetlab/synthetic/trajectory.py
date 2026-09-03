"""Generate bounded, FK-backed trajectories without private input data."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from retargetlab.contracts import CanonicalFrame, CanonicalTrajectory, Pose
from retargetlab.kinematics.base import KinematicsBackend

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class SyntheticTrajectory:
    """A canonical trajectory plus its synthetic joint-space reference."""

    trajectory: CanonicalTrajectory
    joint_configurations: tuple[tuple[float, ...], ...]


def _vector(
    values: Sequence[float] | NDArray[np.floating],
    *,
    name: str,
) -> FloatArray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional vector")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    return array


def _step_bound(
    value: float | Sequence[float] | NDArray[np.floating],
    size: int,
) -> FloatArray:
    array = np.asarray(value, dtype=float)
    if array.ndim == 0:
        array = np.full(size, float(array))
    if array.shape != (size,):
        raise ValueError(f"max_joint_delta must have shape ({size},)")
    if not np.all(np.isfinite(array)) or np.any(array <= 0.0):
        raise ValueError("max_joint_delta must be finite and positive")
    return array


def _pose_from_fk(
    backend: KinematicsBackend,
    group: str,
    q: FloatArray,
    frame: str,
) -> Pose:
    position, quaternion = backend.fk(group, q)
    position_array = np.asarray(position, dtype=float)
    quaternion_array = np.asarray(quaternion, dtype=float)
    if position_array.shape != (3,) or quaternion_array.shape != (4,):
        raise ValueError("backend.fk must return one position (3,) and quaternion (4,)")
    return Pose(
        position_m=(
            float(position_array[0]),
            float(position_array[1]),
            float(position_array[2]),
        ),
        quaternion_wxyz=(
            float(quaternion_array[0]),
            float(quaternion_array[1]),
            float(quaternion_array[2]),
            float(quaternion_array[3]),
        ),
        frame=frame,
    )


def generate_synthetic_trajectory(
    backend: KinematicsBackend,
    groups: Sequence[str],
    initial_q: Sequence[float] | NDArray[np.floating],
    lower_limits: Sequence[float] | NDArray[np.floating],
    upper_limits: Sequence[float] | NDArray[np.floating],
    *,
    frame: str = "base",
    steps: int = 20,
    dt_s: float = 0.01,
    max_joint_delta: float | Sequence[float] | NDArray[np.floating] = 0.02,
    seed: int = 20260904,
) -> SyntheticTrajectory:
    """Generate smooth bounded joint states and derive canonical FK targets.

    The returned configurations are test references only. They are never
    required by the canonical trajectory contract or written to input data.
    """

    group_names = tuple(groups)
    if not group_names or any(not group.strip() for group in group_names):
        raise ValueError("groups must contain at least one non-blank name")
    if len(set(group_names)) != len(group_names):
        raise ValueError("groups must be unique")
    if not isinstance(steps, int) or steps <= 0:
        raise ValueError("steps must be a positive integer")
    if not np.isfinite(dt_s) or dt_s <= 0.0:
        raise ValueError("dt_s must be finite and positive")

    q = _vector(initial_q, name="initial_q")
    lower = _vector(lower_limits, name="lower_limits")
    upper = _vector(upper_limits, name="upper_limits")
    if lower.shape != q.shape or upper.shape != q.shape:
        raise ValueError("initial_q and limits must have the same shape")
    if np.any(lower >= upper):
        raise ValueError("each lower limit must be below its upper limit")
    if np.any(q < lower) or np.any(q > upper):
        raise ValueError("initial_q must be inside the provided limits")
    max_delta = _step_bound(max_joint_delta, q.size)

    rng = np.random.default_rng(seed)
    configurations: list[FloatArray] = [q.copy()]
    velocity = np.zeros_like(q)
    for _ in range(1, steps):
        random_velocity = rng.uniform(-max_delta, max_delta)
        velocity = 0.7 * velocity + 0.3 * random_velocity
        next_q = np.clip(configurations[-1] + velocity, lower, upper)
        velocity = next_q - configurations[-1]
        configurations.append(next_q)

    frames: list[CanonicalFrame] = []
    for index, configuration in enumerate(configurations):
        poses = {
            group: _pose_from_fk(backend, group, configuration, frame) for group in group_names
        }
        frames.append(CanonicalFrame(timestamp_s=index * dt_s, poses=poses))
    trajectory = CanonicalTrajectory(
        coordinate_frame=frame,
        frames=frames,
        metadata={
            "generator": "retargetlab.synthetic.v0.1",
            "seed": str(seed),
            "max_joint_delta": ",".join(f"{value:.12g}" for value in max_delta),
        },
    )
    return SyntheticTrajectory(
        trajectory=trajectory,
        joint_configurations=tuple(
            tuple(float(value) for value in configuration) for configuration in configurations
        ),
    )
