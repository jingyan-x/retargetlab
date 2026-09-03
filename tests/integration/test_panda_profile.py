import os
from pathlib import Path

import numpy as np
import pytest

from retargetlab.kinematics.pinocchio_backend import PinocchioBackend
from retargetlab.robot.collision import PinocchioCollisionModel
from retargetlab.robot.panda import load_panda_bimanual_profile


def test_panda_profile_fk_and_collision_smoke() -> None:
    raw_asset_dir = os.environ.get("RETARGETLAB_PANDA_ASSET_DIR")
    if not raw_asset_dir:
        pytest.skip("set RETARGETLAB_PANDA_ASSET_DIR for the remote Panda asset smoke")
    asset_dir = Path(raw_asset_dir)
    if not asset_dir.is_dir():
        pytest.skip(f"Panda asset directory is unavailable: {asset_dir}")

    profile = load_panda_bimanual_profile(asset_dir)
    backend = PinocchioBackend(profile)
    collision = PinocchioCollisionModel(profile)
    q = np.zeros(collision.model.nq)
    for prefix in ("panda_1", "panda_2"):
        for joint_index, value in enumerate(
            (0.0, -0.7853981634, 0.0, -2.3561944902, 0.0, 1.5707963268, 0.7853981634), 1
        ):
            joint_id = collision.model.getJointId(f"{prefix}_joint{joint_index}")
            q[int(collision.model.idx_qs[joint_id])] = value

    left_position, left_quaternion = backend.fk("panda_2", q)
    right_position, right_quaternion = backend.fk("panda_1", q)
    assert left_position.shape == (3,)
    assert right_position.shape == (3,)
    assert left_quaternion.shape == (4,)
    assert right_quaternion.shape == (4,)
    assert collision.report(q).collision_free
