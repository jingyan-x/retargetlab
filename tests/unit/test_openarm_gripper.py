import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from retargetlab.contracts import (
    KinematicGroup,
    MimicJoint,
    RobotProfile,
    TargetGripperProfile,
)
from retargetlab.run import write_robot_profile


def make_gripper() -> TargetGripperProfile:
    return TargetGripperProfile(
        name="fixture_gripper",
        driver_joint_name="finger_joint1",
        mimic_joints=(MimicJoint(joint_name="finger_joint2"),),
        driver_lower_m=0.0,
        driver_upper_m=0.044,
    )


def test_target_gripper_maps_aperture_to_driver_and_mimic() -> None:
    gripper = make_gripper()

    assert gripper.joint_names == ("finger_joint1", "finger_joint2")
    assert gripper.aperture_to_joint_positions(0.0) == {
        "finger_joint1": 0.0,
        "finger_joint2": 0.0,
    }
    assert gripper.aperture_to_joint_positions(1.0) == {
        "finger_joint1": 0.044,
        "finger_joint2": 0.044,
    }
    assert gripper.aperture_to_joint_positions(0.5) == {
        "finger_joint1": 0.022,
        "finger_joint2": 0.022,
    }


def test_target_gripper_rejects_nonfinite_or_out_of_range_aperture() -> None:
    gripper = make_gripper()
    for value in (-0.01, 1.01, math.nan, math.inf):
        with pytest.raises(ValueError, match="aperture_fraction"):
            gripper.aperture_to_joint_positions(value)


def test_group_requires_explicit_gripper_joint_order() -> None:
    with pytest.raises(ValidationError, match="gripper semantics must match"):
        KinematicGroup(
            name="arm",
            joint_names=("joint1",),
            end_effector_frame="tool",
            gripper_joint_names=("finger_joint2", "finger_joint1"),
            gripper=make_gripper(),
        )


def test_robot_profile_writer_is_exclusive(tmp_path: Path) -> None:
    profile = RobotProfile(
        robot_id="fixture",
        asset_dir="assets/fixture",
        urdf_path="fixture.urdf",
        urdf_sha256="0" * 64,
        groups=(
            KinematicGroup(
                name="arm",
                joint_names=("joint1",),
                end_effector_frame="tool",
            ),
        ),
    )
    output = tmp_path / "robot-profile.json"

    write_robot_profile(output, profile)

    assert json.loads(output.read_text(encoding="utf-8"))["robot_id"] == "fixture"
    with pytest.raises(FileExistsError):
        write_robot_profile(output, profile)
