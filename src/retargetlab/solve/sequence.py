"""Backend-agnostic warm-start and bounded retry orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from retargetlab.contracts import (
    CanonicalTrajectory,
    IKResult,
    IKStatus,
    RobotProfile,
    SolveOptions,
)
from retargetlab.kinematics.base import KinematicsBackend

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class StreamSolution:
    """One selected sequence attempt and its audit metadata."""

    stream: str
    group: str
    results: tuple[IKResult, ...]
    selected_seed_index: int
    attempts: int

    @property
    def converged_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(result.status is IKStatus.CONVERGED for result in self.results) / len(
            self.results
        )


def _seed_list(
    seeds: NDArray[np.floating] | list[float] | list[list[float]] | None,
) -> list[FloatArray]:
    if seeds is None:
        raise ValueError("solve_stream requires at least one explicit solver seed")
    values = np.asarray(seeds, dtype=float)
    if values.ndim == 1:
        values = values[None, :]
    if values.ndim != 2 or values.shape[0] == 0 or values.shape[1] == 0:
        raise ValueError("seeds must have shape (nq,) or (M, nq)")
    if not np.all(np.isfinite(values)):
        raise ValueError("seeds must contain only finite values")
    return [row.copy() for row in values]


def _attempt_quality(
    results: list[IKResult], opts: SolveOptions, seed_index: int
) -> tuple[Any, ...]:
    failure_count = sum(result.status is not IKStatus.CONVERGED for result in results)
    residual_score = max(
        (
            max(
                result.position_error_m / opts.position_tolerance_m,
                result.orientation_error_rad / opts.orientation_tolerance_rad,
            )
            for result in results
        ),
        default=float("inf"),
    )
    return failure_count, residual_score, sum(result.iterations for result in results), seed_index


def solve_stream(
    trajectory: CanonicalTrajectory,
    stream: str,
    group: str,
    backend: KinematicsBackend,
    profile: RobotProfile,
    opts: SolveOptions,
    seeds: NDArray[np.floating] | list[float] | list[list[float]] | None,
) -> StreamSolution:
    """Solve one stream with fixed seed budget and backend-owned warm starts."""

    if stream not in trajectory.stream_names:
        raise KeyError(f"unknown trajectory stream: {stream}")
    if group not in {item.name for item in profile.groups}:
        raise KeyError(f"unknown robot group: {group}")
    targets = [frame.poses[stream] for frame in trajectory.frames]
    attempts = _seed_list(seeds)
    selected_results: list[IKResult] | None = None
    selected_quality: tuple[Any, ...] | None = None
    selected_seed_index = 0
    for seed_index, seed in enumerate(attempts[: opts.retry_seed_count]):
        candidate_results = list(backend.solve_sequence(group, targets, seed, opts))
        if len(candidate_results) != len(targets):
            raise ValueError("backend returned a sequence with the wrong frame count")
        quality = _attempt_quality(candidate_results, opts, seed_index)
        if selected_quality is None or quality < selected_quality:
            selected_results = candidate_results
            selected_quality = quality
            selected_seed_index = seed_index
        if quality[0] == 0:
            break
    if selected_results is None:
        raise RuntimeError("no solver attempt was executed")
    return StreamSolution(
        stream=stream,
        group=group,
        results=tuple(selected_results),
        selected_seed_index=selected_seed_index,
        attempts=min(len(attempts), opts.retry_seed_count),
    )
