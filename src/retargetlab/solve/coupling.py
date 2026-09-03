"""The only module that interprets relationships between pose streams."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray

from retargetlab.contracts import CanonicalTrajectory, RobotProfile, SolveOptions
from retargetlab.kinematics.base import KinematicsBackend
from retargetlab.solve.sequence import StreamSolution, solve_stream


class SolveCoupling(StrEnum):
    """Registered cross-stream coupling modes."""

    INDEPENDENT = "independent"
    WARM_START_FROM_STATE = "warm_start_from_state"
    JOINT_SOLVE = "joint_solve"
    INTERLEAVED_SEQUENCE = "interleaved_sequence"


def solve_coupled(
    trajectory: CanonicalTrajectory,
    stream_groups: Mapping[str, str],
    backend: KinematicsBackend,
    profile: RobotProfile,
    opts: SolveOptions,
    coupling: SolveCoupling,
    seeds: Mapping[str, NDArray[np.floating] | list[float] | list[list[float]]] | None = None,
) -> dict[str, StreamSolution]:
    """Solve streams according to one explicit coupling mode.

    ``joint_solve`` is capability-gated and intentionally not emulated by
    independently solving streams. ``interleaved_sequence`` is retained as a
    rejected compatibility value because the project has already ruled out its
    timestamp assumption.
    """

    if not stream_groups:
        raise ValueError("stream_groups must not be empty")
    if coupling is SolveCoupling.INTERLEAVED_SEQUENCE:
        raise ValueError(
            "interleaved_sequence is rejected: action timing is not assumed to lie "
            "between state frames"
        )
    if coupling is SolveCoupling.JOINT_SOLVE:
        if not backend.capabilities.multi_group_joint_solve:
            raise RuntimeError("backend does not declare multi_group_joint_solve")
        raise NotImplementedError("joint_solve backend adapter is scheduled after M0.11")

    results: dict[str, StreamSolution] = {}
    for stream, group in stream_groups.items():
        if seeds is None or stream not in seeds:
            raise ValueError(f"an explicit seed is required for stream {stream!r}")
        results[stream] = solve_stream(
            trajectory,
            stream,
            group,
            backend,
            profile,
            opts,
            seeds[stream],
        )
    return results
