import math
from pathlib import Path

import numpy as np
import pytest

from retargetlab.contracts import (
    CanonicalFrame,
    CanonicalTrajectory,
    KinematicGroup,
    Pose,
    RobotProfile,
    SolveOptions,
)
from retargetlab.kinematics.pink_backend import PinkBackend
from retargetlab.solve import SolveCoupling, solve_coupled

FIXTURE_URDF = """<?xml version="1.0"?>
<robot name="fixture">
  <link name="base"/>
  <link name="link1"/>
  <link name="tool"/>
  <joint name="joint1" type="revolute">
    <parent link="base"/>
    <child link="link1"/>
    <axis xyz="0 0 1"/>
    <limit lower="-3.14" upper="3.14" effort="10" velocity="10"/>
  </joint>
  <joint name="joint2" type="revolute">
    <parent link="link1"/>
    <child link="tool"/>
    <origin xyz="1 0 0"/>
    <axis xyz="0 0 1"/>
    <limit lower="-3.14" upper="3.14" effort="10" velocity="10"/>
  </joint>
</robot>
"""


def make_profile(tmp_path: Path) -> RobotProfile:
    (tmp_path / "fixture.urdf").write_text(FIXTURE_URDF, encoding="utf-8")
    return RobotProfile(
        robot_id="fixture",
        asset_dir=str(tmp_path),
        urdf_path="fixture.urdf",
        urdf_sha256="0" * 64,
        root_frame="base",
        groups=(
            KinematicGroup(
                name="arm",
                joint_names=("joint1", "joint2"),
                end_effector_frame="tool",
            ),
        ),
    )


def test_pink_solves_one_pose_and_warm_starts_sequence(tmp_path: Path) -> None:
    pytest.importorskip("pinocchio")
    pytest.importorskip("pink")
    backend = PinkBackend(make_profile(tmp_path))
    options = SolveOptions(
        max_iterations=200,
        integration_dt_s=0.02,
        position_tolerance_m=1e-4,
        orientation_tolerance_rad=1e-4,
        qp_eps_abs=1e-7,
        qp_eps_rel=1e-7,
    )
    target = Pose(
        position_m=(0.0, 1.0, 0.0),
        quaternion_wxyz=(math.cos(math.pi / 4.0), 0.0, 0.0, math.sin(math.pi / 4.0)),
        frame="base",
    )
    result = backend.solve_frame("arm", target, np.zeros(2), options)
    assert result.status.value == "CONVERGED"
    assert result.position_error_m <= options.position_tolerance_m
    assert result.orientation_error_rad <= options.orientation_tolerance_rad

    sequence = backend.solve_sequence("arm", [target, target], np.zeros(2), options)
    assert len(sequence) == 2
    assert all(item.status.value == "CONVERGED" for item in sequence)
    assert sequence[1].iterations <= sequence[0].iterations


def test_coupling_keeps_modes_explicit(tmp_path: Path) -> None:
    pytest.importorskip("pinocchio")
    pytest.importorskip("pink")
    backend = PinkBackend(make_profile(tmp_path))
    target = Pose(
        position_m=(0.0, 1.0, 0.0),
        quaternion_wxyz=(math.cos(math.pi / 4.0), 0.0, 0.0, math.sin(math.pi / 4.0)),
        frame="base",
    )
    trajectory = CanonicalTrajectory(
        coordinate_frame="base",
        frames=[
            CanonicalFrame(timestamp_s=0.0, poses={"tool": target}),
            CanonicalFrame(timestamp_s=0.02, poses={"tool": target}),
        ],
    )
    solutions = solve_coupled(
        trajectory,
        {"tool": "arm"},
        backend,
        make_profile(tmp_path),
        SolveOptions(max_iterations=100),
        SolveCoupling.INDEPENDENT,
        {"tool": [0.0, 0.0]},
    )
    assert solutions["tool"].converged_rate == 1.0
    with pytest.raises(ValueError, match="interleaved_sequence is rejected"):
        solve_coupled(
            trajectory,
            {"tool": "arm"},
            backend,
            make_profile(tmp_path),
            SolveOptions(),
            SolveCoupling.INTERLEAVED_SEQUENCE,
            {"tool": [0.0, 0.0]},
        )
    with pytest.raises(RuntimeError, match="multi_group_joint_solve"):
        solve_coupled(
            trajectory,
            {"tool": "arm"},
            backend,
            make_profile(tmp_path),
            SolveOptions(),
            SolveCoupling.JOINT_SOLVE,
            {"tool": [0.0, 0.0]},
        )
