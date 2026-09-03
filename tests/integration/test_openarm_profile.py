import os
from pathlib import Path

import numpy as np
import pytest

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
    assert (
        profile.collision.srdf_sha256
        == "e4bccdd6912241dcd6c4acce2fdd903a7aa6b45dc1787dc768eba2244b0b8f35"
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
