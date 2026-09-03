import hashlib
import math

import pytest
from pydantic import ValidationError

from retargetlab.contracts import (
    CanonicalFrame,
    CanonicalTrajectory,
    KinematicGroup,
    Pose,
    RobotProfile,
)
from retargetlab.kinematics.pinocchio_backend import PinocchioBackend
from retargetlab.synthetic import generate_synthetic_trajectory

FIXTURE_URDF = """<?xml version="1.0"?>
<robot name="fixture">
  <link name="base"/><link name="tool"/>
  <joint name="joint1" type="revolute">
    <parent link="base"/><child link="tool"/><axis xyz="0 0 1"/>
    <limit lower="-3.14" upper="3.14" effort="10" velocity="10"/>
  </joint>
</robot>
"""


def make_backend(tmp_path):
    (tmp_path / "fixture.urdf").write_text(FIXTURE_URDF, encoding="utf-8")
    profile = RobotProfile(
        robot_id="negative-fixture",
        asset_dir=str(tmp_path),
        urdf_path="fixture.urdf",
        urdf_sha256=hashlib.sha256(FIXTURE_URDF.encode("utf-8")).hexdigest(),
        groups=(
            KinematicGroup(
                name="arm",
                joint_names=("joint1",),
                end_effector_frame="tool",
            ),
        ),
    )
    return PinocchioBackend(profile)


def test_contract_negative_cases_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Pose(position_m=(0.0, 0.0, 0.0), quaternion_wxyz=(2.0, 0.0, 0.0, 0.0))
    with pytest.raises(ValidationError):
        Pose(position_m=(math.nan, 0.0, 0.0), quaternion_wxyz=(1.0, 0.0, 0.0, 0.0))

    pose = Pose(position_m=(0.0, 0.0, 0.0), quaternion_wxyz=(1.0, 0.0, 0.0, 0.0))
    with pytest.raises(ValidationError, match="same stream names"):
        CanonicalTrajectory(
            frames=[
                CanonicalFrame(timestamp_s=0.0, poses={"left": pose}),
                CanonicalFrame(timestamp_s=0.01, poses={"right": pose}),
            ]
        )
    with pytest.raises(ValidationError, match="strictly increasing"):
        CanonicalTrajectory(
            frames=[
                CanonicalFrame(timestamp_s=0.01, poses={"arm": pose}),
                CanonicalFrame(timestamp_s=0.01, poses={"arm": pose}),
            ]
        )
    with pytest.raises(ValidationError, match="coordinate_frame"):
        CanonicalTrajectory(
            coordinate_frame="base",
            frames=[
                CanonicalFrame(
                    timestamp_s=0.0,
                    poses={
                        "arm": Pose(
                            position_m=(0.0, 0.0, 0.0),
                            quaternion_wxyz=(1.0, 0.0, 0.0, 0.0),
                            frame="other",
                        )
                    },
                )
            ],
        )
    with pytest.raises(ValidationError):
        CanonicalTrajectory(frames=[])


def test_generator_and_backend_negative_cases_are_rejected(tmp_path) -> None:
    pytest.importorskip("pinocchio")
    backend = make_backend(tmp_path)
    common = dict(
        backend=backend,
        groups=("arm",),
        initial_q=(0.0,),
        lower_limits=(-3.14,),
        upper_limits=(3.14,),
    )
    with pytest.raises(ValueError, match="positive integer"):
        generate_synthetic_trajectory(**common, steps=0)
    with pytest.raises(ValueError, match="same shape"):
        generate_synthetic_trajectory(**{**common, "lower_limits": (-3.14, -1.0)})
    with pytest.raises(ValueError, match="inside"):
        generate_synthetic_trajectory(**{**common, "initial_q": (4.0,)})
    with pytest.raises(ValueError, match="max_joint_delta"):
        generate_synthetic_trajectory(**common, max_joint_delta=(0.1, 0.1))
    with pytest.raises(KeyError, match="unknown kinematic group"):
        backend.fk("missing", (0.0,))
