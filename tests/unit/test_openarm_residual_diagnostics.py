import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness/m_minus_1"))
from openarm_residual_diagnostics import ResidualAudit


def sample():
    return {
        "q": np.array([0.999, 0.5, 0.0]),
        "metrics": {
            "left_position_error_m": 0.02,
            "right_position_error_m": 0.001,
            "left_orientation_error_rad": 0.1,
            "right_orientation_error_rad": 0.01,
            "penetration": False,
            "joint_limit_violation": False,
        },
        "position_stage": {
            "metrics": {
                "left_position_error_m": 0.001,
                "right_position_error_m": 0.001,
            }
        },
    }


def test_distinguishes_orientation_stage_loss_and_real_arm_limit_activity():
    audit = ResidualAudit({"left_joint": (0, 0, 1), "right_joint": (1, 0, 1)})
    audit.add(sample(), 0.005, 0.035)
    report = audit.report()
    assert report["position_stage"]["position_reached_then_full_pose_failed"] == 1
    assert report["final_failure_counts"]["residual_sides_left"] == 1
    assert report["failed_frames_near_arm_limit_counts"] == {"left_joint": 1}
    assert "q" not in report
    assert report["raw_pose_or_joint_values_emitted"] is False


def test_no_false_limit_attribution_for_successful_frame_or_position_failure():
    audit = ResidualAudit({"left_joint": (0, 0, 1), "right_joint": (1, 0, 1)})
    frame = sample()
    frame["position_stage"]["metrics"]["left_position_error_m"] = 0.02
    audit.add(frame, 0.005, 0.035)
    frame["metrics"]["left_position_error_m"] = 0.001
    frame["metrics"]["left_orientation_error_rad"] = 0.01
    audit.add(frame, 0.005, 0.035)
    report = audit.report()
    assert report["position_stage"].get("position_reached_then_full_pose_failed", 0) == 0
    assert report["failed_frames_near_arm_limit_counts"]["left_joint"] == 1
    assert report["final_failure_counts"]["residual_sides_neither"] == 1
