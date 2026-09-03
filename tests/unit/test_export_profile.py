import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from retargetlab.cli.main import EXIT_OK, app
from retargetlab.contracts import (
    ExportProfile,
    KinematicGroup,
    MimicJoint,
    RobotProfile,
    TargetGripperProfile,
    TargetVectorLayout,
)
from retargetlab.export import build_export_profile, build_target_vector_layout
from retargetlab.run import write_export_profile
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes

FIXTURE_URDF = """<?xml version="1.0"?>
<robot name="fixture">
  <link name="world"/>
  <link name="tool"/>
  <link name="finger_link1"/>
  <link name="finger_link2"/>
  <joint name="joint1" type="revolute">
    <parent link="world"/>
    <child link="tool"/>
    <limit lower="-1.0" upper="1.0" effort="1.0" velocity="1.0"/>
  </joint>
  <joint name="finger_joint1" type="prismatic">
    <parent link="tool"/>
    <child link="finger_link1"/>
    <limit lower="0.0" upper="0.044" effort="1.0" velocity="1.0"/>
  </joint>
  <joint name="finger_joint2" type="prismatic">
    <parent link="tool"/>
    <child link="finger_link2"/>
    <mimic joint="finger_joint1" multiplier="1.0" offset="0.0"/>
    <limit lower="0.0" upper="0.044" effort="1.0" velocity="1.0"/>
  </joint>
</robot>
"""


def _profile(tmp_path: Path) -> RobotProfile:
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    urdf_path = asset_dir / "fixture.urdf"
    urdf_path.write_text(FIXTURE_URDF, encoding="utf-8")
    gripper = TargetGripperProfile(
        name="fixture_gripper",
        driver_joint_name="finger_joint1",
        mimic_joints=(MimicJoint(joint_name="finger_joint2"),),
        driver_lower_m=0.0,
        driver_upper_m=0.044,
    )
    return RobotProfile(
        robot_id="fixture",
        asset_dir=str(asset_dir),
        urdf_path=urdf_path.name,
        urdf_sha256=sha256_bytes(urdf_path.read_bytes()),
        root_frame="world",
        groups=(
            KinematicGroup(
                name="arm",
                joint_names=("joint1",),
                end_effector_frame="tool",
                gripper_joint_names=gripper.joint_names,
                gripper=gripper,
            ),
        ),
    )


def test_target_layout_is_arm_first_and_omits_mimic_dimensions(tmp_path: Path) -> None:
    profile = _profile(tmp_path)

    layout = build_target_vector_layout(profile)

    assert layout.group_names == ("arm",)
    assert layout.names == ("joint1", "finger_joint1")
    assert layout.units == ("rad", "m")
    assert layout.dtype == "float32"
    assert layout.shape == (2,)


def test_export_profile_binds_layout_to_verified_robot_profile(tmp_path: Path) -> None:
    profile = _profile(tmp_path)

    export_profile = build_export_profile(
        profile,
        normalization_exclude=("valid.retarget",),
    )
    output = tmp_path / "export-profile.json"
    write_export_profile(output, export_profile)

    assert export_profile.robot_id == "fixture"
    assert export_profile.normalization_exclude == ("valid.retarget",)
    assert export_profile.robot_profile_sha256 == sha256_bytes(canonical_json_bytes(profile))
    assert json.loads(output.read_text(encoding="utf-8"))["target_layout"]["names"] == [
        "joint1",
        "finger_joint1",
    ]
    assert ExportProfile.model_validate_json(output.read_text(encoding="utf-8")) == export_profile
    with pytest.raises(FileExistsError):
        write_export_profile(output, export_profile)


def test_build_export_profile_cli_writes_layout_summary(tmp_path: Path, capsys) -> None:
    profile = _profile(tmp_path)
    profile_path = tmp_path / "robot-profile.json"
    profile_path.write_text(profile.model_dump_json(), encoding="utf-8")
    output = tmp_path / "export-profile.json"

    assert (
        app(
            [
                "build-export-profile",
                "--profile",
                str(profile_path),
                "--output",
                str(output),
                "--json",
            ]
        )
        == EXIT_OK
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "WRITTEN"
    assert payload["shape"] == [2]
    assert payload["joint_names"] == ["joint1", "finger_joint1"]


def test_target_layout_rejects_unresolved_gripper_joint_semantics() -> None:
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
                gripper_joint_names=("finger_joint1",),
            ),
        ),
    )

    with pytest.raises(ValueError, match="no explicit semantics"):
        build_target_vector_layout(profile)


def test_target_layout_contract_rejects_misaligned_or_duplicate_names() -> None:
    with pytest.raises(ValidationError, match="same length"):
        TargetVectorLayout(
            group_names=("arm",),
            names=("joint1",),
            units=("rad", "m"),
        )
    with pytest.raises(ValidationError, match="must be unique"):
        TargetVectorLayout(
            group_names=("arm",),
            names=("joint1", "joint1"),
            units=("rad", "rad"),
        )
