import json
import os
from pathlib import Path

import numpy as np
import pytest

from retargetlab.cli.main import EXIT_OK, EXIT_SEMANTIC, app
from retargetlab.contracts import (
    CanonicalFrame,
    CanonicalTrajectory,
    Pose,
    RobotProfile,
    TargetGripperTrajectory,
)
from retargetlab.kinematics.pinocchio_backend import PinocchioBackend
from retargetlab.robot.collision import PinocchioCollisionModel
from retargetlab.robot.openarm import load_openarm_bimanual_profile


def test_openarm_profile_loads_verified_asset_and_maps_real_fingers() -> None:
    raw_asset_dir = os.environ.get("RETARGETLAB_OPENARM_ASSET_DIR")
    if not raw_asset_dir:
        pytest.skip("set RETARGETLAB_OPENARM_ASSET_DIR for the remote OpenArm asset smoke")
    asset_dir = Path(raw_asset_dir)
    if not asset_dir.is_dir():
        pytest.skip(f"OpenArm asset directory is unavailable: {asset_dir}")

    profile = load_openarm_bimanual_profile(asset_dir)
    assert profile.robot_id == "openarm_bimanual"
    assert profile.root_frame == "world"
    assert {group.name for group in profile.groups} == {"openarm_left", "openarm_right"}
    assert profile.collision is not None
    assert profile.collision.srdf_sha256 == (
        "e4bccdd6912241dcd6c4acce2fdd903a7aa6b45dc1787dc768eba2244b0b8f35"
    )

    backend = PinocchioBackend(profile)
    collision = PinocchioCollisionModel(profile)
    assert len(collision.srdf_disabled_pairs) == 16
    barrier = collision.barrier_geometry(2)
    assert len(barrier.collisionPairs) == 2
    assert backend.model is not None
    model = backend.model
    q = np.zeros(model.nq)
    for group in profile.groups:
        assert group.gripper is not None
        assert model.getFrameId(group.end_effector_frame) < model.nframes
        positions = group.gripper.aperture_to_joint_positions(1.0)
        for joint_name, value in positions.items():
            joint_id = model.getJointId(joint_name)
            q[int(model.idx_qs[joint_id])] = value
        assert q[int(model.idx_qs[model.getJointId(group.gripper.driver_joint_name)])] == 0.044

    left_position, left_quaternion = backend.fk("openarm_left", q)
    right_position, right_quaternion = backend.fk("openarm_right", q)
    assert left_position.shape == (3,)
    assert right_position.shape == (3,)
    assert left_quaternion.shape == (4,)
    assert right_quaternion.shape == (4,)


def test_openarm_profile_cli_materializes_exclusive_json(tmp_path: Path, capsys) -> None:
    raw_asset_dir = os.environ.get("RETARGETLAB_OPENARM_ASSET_DIR")
    if not raw_asset_dir:
        pytest.skip("set RETARGETLAB_OPENARM_ASSET_DIR for the remote OpenArm asset smoke")
    asset_dir = Path(raw_asset_dir)
    if not asset_dir.is_dir():
        pytest.skip(f"OpenArm asset directory is unavailable: {asset_dir}")
    output = tmp_path / "openarm-robot-profile.json"
    argv = [
        "build-robot-profile",
        "--robot",
        "openarm_bimanual",
        "--asset-dir",
        str(asset_dir),
        "--output",
        str(output),
        "--json",
    ]

    assert app(argv) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    profile = RobotProfile.model_validate_json(output.read_text(encoding="utf-8"))
    assert payload["status"] == "WRITTEN"
    assert payload["profile_sha256"]
    assert profile.robot_id == "openarm_bimanual"
    assert profile.groups[0].gripper is not None

    assert app(argv) == EXIT_SEMANTIC
    error = json.loads(capsys.readouterr().out)
    assert error["status"] == "INVALID_INPUT"


def test_map_grippers_cli_binds_real_profile_without_arm_poses(tmp_path: Path, capsys) -> None:
    raw_asset_dir = os.environ.get("RETARGETLAB_OPENARM_ASSET_DIR")
    if not raw_asset_dir:
        pytest.skip("set RETARGETLAB_OPENARM_ASSET_DIR for the remote OpenArm asset smoke")
    asset_dir = Path(raw_asset_dir)
    profile_path = asset_dir / "robot-profile-v0.1.json"
    if not profile_path.is_file():
        pytest.skip(f"OpenArm profile artifact is unavailable: {profile_path}")
    pose = Pose(
        position_m=(0.0, 0.0, 0.0),
        quaternion_wxyz=(1.0, 0.0, 0.0, 0.0),
    )
    trajectory = CanonicalTrajectory(
        frames=[
            CanonicalFrame(
                timestamp_s=0.0,
                poses={"left": pose, "right": pose},
                grippers={"left": 0.0, "right": 1.0},
            ),
            CanonicalFrame(
                timestamp_s=0.1,
                poses={"left": pose, "right": pose},
                grippers={"left": 0.5, "right": 0.25},
            ),
        ]
    )
    trajectory_path = tmp_path / "canonical.json"
    trajectory_path.write_text(trajectory.model_dump_json(), encoding="utf-8")
    output = tmp_path / "target-grippers.json"

    assert (
        app(
            [
                "map-grippers",
                "--trajectory",
                str(trajectory_path),
                "--profile",
                str(profile_path),
                "--binding",
                "left=openarm_left",
                "--binding",
                "right=openarm_right",
                "--output",
                str(output),
                "--json",
            ]
        )
        == EXIT_OK
    )
    payload = json.loads(capsys.readouterr().out)
    mapped = TargetGripperTrajectory.model_validate_json(output.read_text(encoding="utf-8"))
    assert payload["status"] == "MAPPED"
    assert mapped.profile_sha256 == (
        "1aa65d1241838b7fd29ed79d2a485488aec187b946ccb8fc654d4bfb71bc0194"
    )
    assert mapped.frames[0].joint_positions["openarm_left_finger_joint1"] == 0.0
    assert mapped.frames[0].joint_positions["openarm_right_finger_joint1"] == 0.044


def test_geometric_outer_bound_never_rejects_target_fk_poses():
    import sys

    import pinocchio as pin

    raw_asset_dir = os.environ.get("RETARGETLAB_OPENARM_ASSET_DIR")
    if not raw_asset_dir:
        pytest.skip("set RETARGETLAB_OPENARM_ASSET_DIR for the target-FK bound check")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness/m_minus_1"))
    import probe_openarm_reachability as harness
    from inspect_openarm_reachability_bounds import arm_bounds, summarize_bounds

    asset = Path(raw_asset_dir)
    model, _, _ = harness.prepare_geometry(asset, harness.discover_manifest_srdf(asset, None))
    centers, radii = arm_bounds(model)
    wrists = {"left": [], "right": []}
    rng = np.random.default_rng(20260910)
    data = model.createData()
    for _ in range(64):
        q = harness.random_target_configuration(model, rng)
        pin.framesForwardKinematics(model, data, q)
        for side in wrists:
            wrists[side].append(
                data.oMf[model.getFrameId(f"openarm_{side}_link7")].translation.copy()
            )
    report = summarize_bounds(wrists, centers, radii, 0.0)
    assert report["fixed_current_placement"]["any_arm_certified_impossible_frames"] == 0
    assert report["any_common_rigid_placement"]["bimanual_span_certified_impossible_frames"] == 0
