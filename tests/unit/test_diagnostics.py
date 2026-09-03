import math

from retargetlab.contracts import IKResult, IKStatus
from retargetlab.diagnose import check_frame, default_m0_thresholds, diagnose_episode


def result(
    *,
    position_error_m: float,
    orientation_error_rad: float,
    collision_free: bool | None = True,
    status: IKStatus = IKStatus.CONVERGED,
) -> IKResult:
    return IKResult(
        status=status,
        q=(0.0,),
        iterations=1,
        position_error_m=position_error_m,
        orientation_error_rad=orientation_error_rad,
        termination_reason="fixture",
        solver="fixture",
        collision_free=collision_free,
    )


def test_frame_checks_separate_nominal_relaxed_and_unverified_collision() -> None:
    thresholds = default_m0_thresholds()
    nominal = check_frame(result(position_error_m=0.001, orientation_error_rad=0.01), 0, thresholds)
    assert nominal.nominal is True
    assert nominal.relaxed is True

    relaxed = check_frame(
        result(position_error_m=0.004, orientation_error_rad=math.radians(4.0)),
        1,
        thresholds,
    )
    assert relaxed.nominal is False
    assert relaxed.relaxed is True

    unverified = check_frame(
        result(position_error_m=0.001, orientation_error_rad=0.01, collision_free=None),
        2,
        thresholds,
    )
    assert unverified.nominal is False
    assert unverified.relaxed is False


def test_episode_status_is_read_only_pass_warn_fail() -> None:
    thresholds = default_m0_thresholds()
    passing = diagnose_episode(
        [result(position_error_m=0.001, orientation_error_rad=0.01)],
        thresholds=thresholds,
    )
    assert passing.status == "PASS"

    warning = diagnose_episode(
        [result(position_error_m=0.004, orientation_error_rad=math.radians(4.0))],
        thresholds=thresholds,
    )
    assert warning.status == "WARN"

    failing = diagnose_episode(
        [result(position_error_m=0.001, orientation_error_rad=0.01, collision_free=False)],
        thresholds=thresholds,
    )
    assert failing.status == "FAIL"
