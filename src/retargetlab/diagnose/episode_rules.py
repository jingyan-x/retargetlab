"""Episode-level diagnostic aggregation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from retargetlab.contracts import EpisodeReport, FrameDiagnostics, IKResult
from retargetlab.diagnose.frame_checks import check_frame
from retargetlab.diagnose.thresholds import ThresholdSet, default_m0_thresholds


def _episode_status(
    frames: Sequence[FrameDiagnostics],
) -> Literal["PASS", "WARN", "FAIL"]:
    if all(frame.nominal for frame in frames):
        return "PASS"
    if all(frame.relaxed for frame in frames):
        return "WARN"
    return "FAIL"


def diagnose_episode(
    results: Sequence[IKResult],
    episode_index: int = 0,
    thresholds: ThresholdSet | None = None,
    delta_violations: Sequence[bool] | None = None,
) -> EpisodeReport:
    """Aggregate quality facts; this function never repairs a solution."""

    if not results:
        raise ValueError("cannot diagnose an empty episode")
    threshold_set = thresholds or default_m0_thresholds()
    deltas = list(delta_violations or [False] * len(results))
    if len(deltas) != len(results):
        raise ValueError("delta_violations must match the result count")
    frames = tuple(
        check_frame(result, index, threshold_set, delta_violation=deltas[index])
        for index, result in enumerate(results)
    )
    count = len(frames)
    return EpisodeReport(
        episode_index=episode_index,
        frame_count=count,
        nominal_rate=sum(frame.nominal for frame in frames) / count,
        relaxed_rate=sum(frame.relaxed for frame in frames) / count,
        collision_fraction=sum(frame.collision_free is not True for frame in frames) / count,
        joint_limit_violation_fraction=sum(frame.joint_limit_violation for frame in frames) / count,
        delta_violation_fraction=sum(frame.delta_violation for frame in frames) / count,
        status=_episode_status(frames),
        frames=frames,
    )
