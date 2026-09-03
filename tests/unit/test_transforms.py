import math

import numpy as np
import pytest

from retargetlab.kinematics.transforms import (
    compose_se3,
    inverse_se3,
    make_quaternion_sign_continuous,
    matrix_to_quaternion_wxyz,
    pose_to_se3,
    quaternion_geodesic_angle_rad,
    quaternion_wxyz_to_matrix,
    se3_to_pose,
)


def test_wxyz_quarter_turn_and_round_trip() -> None:
    quaternion = (math.cos(math.pi / 4), 0.0, 0.0, math.sin(math.pi / 4))
    rotation = quaternion_wxyz_to_matrix(quaternion)
    np.testing.assert_allclose(rotation @ [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], atol=1e-12)
    recovered = matrix_to_quaternion_wxyz(rotation)
    assert quaternion_geodesic_angle_rad(quaternion, recovered) < 1e-12


def test_se3_composition_and_inverse() -> None:
    first = pose_to_se3([1.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0])
    second_quaternion = (math.cos(math.pi / 4), 0.0, 0.0, math.sin(math.pi / 4))
    second = pose_to_se3([0.0, 2.0, 0.0], second_quaternion)
    composed = compose_se3(first, second)
    position, quaternion = se3_to_pose(composed)
    np.testing.assert_allclose(position, [1.0, 2.0, 0.0], atol=1e-12)
    assert quaternion_geodesic_angle_rad(quaternion, second_quaternion) < 1e-12
    np.testing.assert_allclose(compose_se3(composed, inverse_se3(composed)), np.eye(4), atol=1e-12)


def test_quaternion_sign_continuity_only_changes_sign() -> None:
    source = np.array(
        [
            [1.0, 0.0, 0.0, 0.0],
            [-1.0, 0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0, 0.0],
        ]
    )
    result = make_quaternion_sign_continuous(source)
    np.testing.assert_allclose(result, np.tile([1.0, 0.0, 0.0, 0.0], (3, 1)))


def test_invalid_rotation_and_zero_quaternion_are_rejected() -> None:
    with pytest.raises(ValueError, match="too small"):
        quaternion_wxyz_to_matrix([0.0, 0.0, 0.0, 0.0])
    with pytest.raises(ValueError, match="determinant"):
        matrix_to_quaternion_wxyz(np.diag([1.0, 1.0, -1.0]))
