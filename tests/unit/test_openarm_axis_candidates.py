from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

MODULE_PATH = Path(__file__).parents[2] / "harness" / "m_minus_1" / "openarm_axis_candidates.py"
SPEC = importlib.util.spec_from_file_location("openarm_axis_candidates", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_enumerates_exactly_24_unique_proper_rotations() -> None:
    rotations = MODULE.enumerate_axis_rotations()
    assert len(rotations) == 24
    matrices = {rotation.matrix for rotation in rotations}
    assert len(matrices) == 24
    for rotation in rotations:
        matrix = np.asarray(rotation.matrix, dtype=float)
        assert np.allclose(matrix.T @ matrix, np.eye(3))
        assert np.isclose(np.linalg.det(matrix), 1.0)


def test_axis_rotation_changes_position_and_orientation_together() -> None:
    identity = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
    axis = next(
        rotation
        for rotation in MODULE.enumerate_axis_rotations()
        if rotation.matrix != identity
    )
    position = np.array([1.0, 2.0, 3.0])
    rotation = np.eye(3)
    base_rotation = np.eye(3)
    base_translation = np.zeros(3)

    mapped_position, mapped_rotation = MODULE.apply_rigid_candidate(
        position,
        rotation,
        base_rotation=base_rotation,
        base_translation=base_translation,
        axis_rotation=axis,
        pose_direction="forward",
    )

    expected = np.asarray(axis.matrix, dtype=float)
    assert np.allclose(mapped_position, expected @ position)
    assert np.allclose(mapped_rotation, expected @ rotation)
    assert not np.allclose(mapped_position, position)


def test_inverse_candidate_inverts_translation_and_orientation() -> None:
    source_rotation = np.array(
        [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]],
        dtype=float,
    )
    source_position = np.array([1.0, 2.0, 3.0])
    identity = np.eye(3)
    zero = np.zeros(3)
    _, mapped_rotation = MODULE.apply_rigid_candidate(
        source_position,
        source_rotation,
        base_rotation=identity,
        base_translation=zero,
        axis_rotation=identity,
        pose_direction="inverse",
    )
    assert np.allclose(mapped_rotation, source_rotation.T)
    mapped_position, _ = MODULE.apply_rigid_candidate(
        source_position,
        source_rotation,
        base_rotation=identity,
        base_translation=zero,
        axis_rotation=identity,
        pose_direction="inverse",
    )
    assert np.allclose(mapped_position, -source_rotation.T @ source_position)


def test_candidate_ids_and_hashes_are_deterministic() -> None:
    first = MODULE.enumerate_candidates(target_frames=("link7", "hand_tcp"))
    second = MODULE.enumerate_candidates(target_frames=("link7", "hand_tcp"))
    assert len(first) == 96
    assert [item.candidate_id for item in first] == [item.candidate_id for item in second]
    assert MODULE.candidate_set_hash(first) == MODULE.candidate_set_hash(second)
