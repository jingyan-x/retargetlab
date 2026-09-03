"""Pure frame-level quality predicates."""

from __future__ import annotations

from retargetlab.contracts import FrameDiagnostics, IKResult, IKStatus
from retargetlab.diagnose.thresholds import ThresholdSet


def check_frame(
    result: IKResult,
    frame_index: int,
    thresholds: ThresholdSet,
    *,
    delta_violation: bool = False,
) -> FrameDiagnostics:
    """Classify one result without changing the result or its configuration."""

    collision_free = result.collision_free
    valid = (
        result.status is IKStatus.CONVERGED
        and collision_free is True
        and not result.joint_limit_violation
        and not delta_violation
        and result.position_error_m <= thresholds.position_nominal_m.fail
    )
    nominal = valid and result.orientation_error_rad <= thresholds.orientation_nominal_rad.fail
    relaxed = valid and result.orientation_error_rad <= thresholds.orientation_relaxed_rad.fail
    return FrameDiagnostics(
        frame_index=frame_index,
        solver_status=result.status,
        position_error_m=result.position_error_m,
        orientation_error_rad=result.orientation_error_rad,
        collision_free=collision_free,
        joint_limit_violation=result.joint_limit_violation,
        delta_violation=delta_violation,
        nominal=nominal,
        relaxed=relaxed,
    )
