import hashlib

import numpy as np
import pytest

from retargetlab.contracts import KinematicGroup, RobotProfile, SolveOptions
from retargetlab.kinematics.pink_backend import PinkBackend
from retargetlab.kinematics.pinocchio_backend import PinocchioBackend
from retargetlab.synthetic import generate_synthetic_trajectory

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


def make_profile(tmp_path):
    (tmp_path / "fixture.urdf").write_text(FIXTURE_URDF, encoding="utf-8")
    return RobotProfile(
        robot_id="synthetic-fixture",
        asset_dir=str(tmp_path),
        urdf_path="fixture.urdf",
        urdf_sha256=hashlib.sha256(FIXTURE_URDF.encode("utf-8")).hexdigest(),
        root_frame="base",
        groups=(
            KinematicGroup(
                name="arm",
                joint_names=("joint1", "joint2"),
                end_effector_frame="tool",
            ),
        ),
    )


def test_generator_is_bounded_smooth_and_fk_backed(tmp_path) -> None:
    pytest.importorskip("pinocchio")
    profile = make_profile(tmp_path)
    backend = PinocchioBackend(profile)
    generated = generate_synthetic_trajectory(
        backend,
        ("arm",),
        initial_q=(0.2, -0.3),
        lower_limits=(-3.14, -3.14),
        upper_limits=(3.14, 3.14),
        steps=16,
        max_joint_delta=0.025,
        seed=7,
    )

    configurations = np.asarray(generated.joint_configurations)
    assert configurations.shape == (16, 2)
    assert np.all(configurations >= -3.14)
    assert np.all(configurations <= 3.14)
    assert np.max(np.abs(np.diff(configurations, axis=0))) <= 0.025 + 1e-12
    assert generated.trajectory.stream_names == ("arm",)
    assert generated.trajectory.frame_count == 16

    for configuration, frame in zip(configurations, generated.trajectory.frames):
        position, quaternion = backend.fk("arm", configuration)
        np.testing.assert_allclose(frame.poses["arm"].position_m, position)
        np.testing.assert_allclose(frame.poses["arm"].quaternion_wxyz, quaternion)


def test_synthetic_fk_targets_round_trip_through_pink(tmp_path) -> None:
    pytest.importorskip("pinocchio")
    pytest.importorskip("pink")
    profile = make_profile(tmp_path)
    fk_backend = PinocchioBackend(profile)
    generated = generate_synthetic_trajectory(
        fk_backend,
        ("arm",),
        initial_q=(0.15, -0.2),
        lower_limits=(-3.14, -3.14),
        upper_limits=(3.14, 3.14),
        steps=8,
        max_joint_delta=0.01,
        seed=11,
    )
    options = SolveOptions(max_iterations=120)
    results = PinkBackend(profile).solve_sequence(
        "arm",
        [frame.poses["arm"] for frame in generated.trajectory.frames],
        generated.joint_configurations[0],
        options,
    )

    assert len(results) == generated.trajectory.frame_count
    assert all(result.status.value == "CONVERGED" for result in results)
    assert all(
        result.position_error_m <= options.position_tolerance_m
        and result.orientation_error_rad <= options.orientation_tolerance_rad
        for result in results
    )
