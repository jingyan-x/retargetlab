import math
from pathlib import Path

import numpy as np
import pytest

from retargetlab.contracts import KinematicGroup, RobotProfile
from retargetlab.kinematics.pinocchio_backend import PinocchioBackend

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


def test_fk_and_jacobian_use_full_model_q(tmp_path: Path) -> None:
    pytest.importorskip("pinocchio")
    backend = PinocchioBackend(make_profile(tmp_path))
    position, quaternion = backend.fk("arm", [0.0, 0.0])
    np.testing.assert_allclose(position, [1.0, 0.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(quaternion, [1.0, 0.0, 0.0, 0.0], atol=1e-12)

    batch_position, batch_quaternion = backend.fk("arm", [[0.0, 0.0], [math.pi / 2.0, 0.0]])
    np.testing.assert_allclose(batch_position, [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], atol=1e-12)
    assert batch_quaternion.shape == (2, 4)
    assert backend.jacobian("arm", [0.0, 0.0]).shape == (6, 2)
    assert backend.jacobian("arm", [[0.0, 0.0], [0.1, 0.2]]).shape == (2, 6, 2)


def test_unknown_group_and_bad_q_are_rejected(tmp_path: Path) -> None:
    pytest.importorskip("pinocchio")
    backend = PinocchioBackend(make_profile(tmp_path))
    with pytest.raises(KeyError, match="unknown kinematic group"):
        backend.fk("missing", [0.0, 0.0])
    with pytest.raises(ValueError, match="shape"):
        backend.fk("arm", [0.0])
