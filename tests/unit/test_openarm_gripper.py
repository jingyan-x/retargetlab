import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from retargetlab.contracts import (
    CanonicalFrame,
    CanonicalTrajectory,
    KinematicGroup,
    MimicJoint,
    Pose,
    RobotProfile,
    TargetGripperProfile,
)
from retargetlab.run import map_target_grippers, write_robot_profile


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


def test_target_gripper_mapping_emits_only_profile_bound_joint_values() -> None:
    left = make_gripper().model_copy(
        update={
            "name": "left_gripper",
            "driver_joint_name": "left_finger_joint1",
            "mimic_joints": (MimicJoint(joint_name="left_finger_joint2"),),
        }
    )
    right = make_gripper().model_copy(
        update={
            "name": "right_gripper",
            "driver_joint_name": "right_finger_joint1",
            "mimic_joints": (MimicJoint(joint_name="right_finger_joint2"),),
        }
    )
    profile = RobotProfile(
        robot_id="fixture",
        asset_dir="assets/fixture",
        urdf_path="fixture.urdf",
        urdf_sha256="0" * 64,
        groups=(
            KinematicGroup(
                name="left",
                joint_names=("left_joint1",),
                end_effector_frame="left_tool",
                gripper_joint_names=left.joint_names,
                gripper=left,
            ),
            KinematicGroup(
                name="right",
                joint_names=("right_joint1",),
                end_effector_frame="right_tool",
                gripper_joint_names=right.joint_names,
                gripper=right,
            ),
        ),
    )
    pose = Pose(
        position_m=(0.0, 0.0, 0.0),
        quaternion_wxyz=(1.0, 0.0, 0.0, 0.0),
    )
    trajectory = CanonicalTrajectory(
        coordinate_frame="dataset_native",
        frames=[
            CanonicalFrame(
                timestamp_s=0.0,
                poses={"source.left": pose, "source.right": pose},
                grippers={"source.left": 0.0, "source.right": 1.0},
            ),
            CanonicalFrame(
                timestamp_s=0.1,
                poses={"source.left": pose, "source.right": pose},
                grippers={"source.left": 0.5, "source.right": 0.25},
            ),
        ],
    )

    mapped = map_target_grippers(
        trajectory,
        profile,
        {"source.left": "left", "source.right": "right"},
    )

    assert mapped.robot_id == "fixture"
    assert mapped.frames[0].joint_positions == {
        "left_finger_joint1": 0.0,
        "left_finger_joint2": 0.0,
        "right_finger_joint1": 0.044,
        "right_finger_joint2": 0.044,
    }
    assert mapped.frames[1].joint_positions["left_finger_joint1"] == 0.022
    assert mapped.frames[1].joint_positions["right_finger_joint1"] == 0.011
    assert "poses" not in mapped.model_dump()


def test_target_gripper_mapping_rejects_unbound_stream() -> None:
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
                gripper_joint_names=make_gripper().joint_names,
                gripper=make_gripper(),
            ),
        ),
    )
    pose = Pose(
        position_m=(0.0, 0.0, 0.0),
        quaternion_wxyz=(1.0, 0.0, 0.0, 0.0),
    )
    trajectory = CanonicalTrajectory(
        frames=[
            CanonicalFrame(
                timestamp_s=0.0,
                poses={"other": pose},
                grippers={"other": 0.0},
            )
        ]
    )

    with pytest.raises(ValueError, match="exactly the trajectory grippers"):
        map_target_grippers(trajectory, profile, {"source": "arm"})
