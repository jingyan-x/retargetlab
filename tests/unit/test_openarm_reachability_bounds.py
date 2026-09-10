import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness/m_minus_1"))
from inspect_openarm_reachability_bounds import summarize_bounds, wrist_tolerance


def test_pose_tolerance_is_included_before_certifying_impossibility():
    slack = wrist_tolerance(0.005, math.radians(2), 0.1801)
    assert 0.011 < slack < 0.012
    centers = {"left": np.zeros(3), "right": np.zeros(3)}
    radii = {"left": 1.0, "right": 1.0}
    wrists = {"left": [[1.005, 0, 0], [1.02, 0, 0]], "right": [[0, 0, 0], [0, 0, 0]]}
    result = summarize_bounds(wrists, centers, radii, slack)
    assert result["fixed_current_placement"]["any_arm_certified_impossible_frames"] == 1
    assert result["fixed_current_placement"]["nominal_rate_upper_bound"] == 0.5


def test_global_span_and_diameter_checks_do_not_depend_on_translation():
    centers = {"left": np.array([0, 0.1, 0]), "right": np.array([0, -0.1, 0])}
    radii = {"left": 1.0, "right": 1.0}
    wrists = {"left": np.array([[0, 0, 0], [2.5, 0, 0]]), "right": np.array([[0, 0, 0], [0, 0, 0]])}
    first = summarize_bounds(wrists, centers, radii, 0.01)
    moved = summarize_bounds({s: w + [10, 20, 30] for s, w in wrists.items()}, centers, radii, 0.01)
    assert first["any_common_rigid_placement"] == moved["any_common_rigid_placement"]
    assert first["any_common_rigid_placement"]["bimanual_span_certified_impossible_frames"] == 1
    assert (
        first["any_common_rigid_placement"]["single_arm_trajectory_diameters"]["left"][
            "pairwise_conflict_count"
        ]
        == 1
    )
