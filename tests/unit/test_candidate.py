import json

import pytest

from retargetlab.contracts import DatasetInfoManifest, FeatureDeclaration, MappingReview
from retargetlab.io import apply_mapping_review, build_pose_mapping_candidate


def _info() -> DatasetInfoManifest:
    names = [
        "gripper_0",
        "epos_0_qw",
        "epos_0_qx",
        "epos_0_qy",
        "epos_0_qz",
        "epos_0_x",
        "epos_0_y",
        "epos_0_z",
        "gripper_1",
        "epos_1_qw",
        "epos_1_qx",
        "epos_1_qy",
        "epos_1_qz",
        "epos_1_x",
        "epos_1_y",
        "epos_1_z",
    ]
    features = {
        "timestamp": FeatureDeclaration(dtype="float32", shape=(1,)),
        "observation.state": FeatureDeclaration(dtype="float32", shape=(16,), names=tuple(names)),
        "action": FeatureDeclaration(dtype="float32", shape=(16,), names=tuple(names)),
    }
    return DatasetInfoManifest(
        dataset_alias="fixture",
        source_revision="v1",
        dataset_name="synthetic",
        total_episodes=1,
        total_frames=2,
        total_tasks=1,
        total_chunks=1,
        fps=30.0,
        features=features,
    )


def test_pose_candidate_uses_declared_names_but_keeps_semantics_unresolved() -> None:
    candidate = build_pose_mapping_candidate(_info())

    assert candidate.coordinate_frame == "UNRESOLVED"
    assert candidate.metadata["candidate_status"] == "REVIEW_REQUIRED"
    assert [stream.name for stream in candidate.streams] == [
        "observation.state.slot_0",
        "observation.state.slot_1",
        "action.slot_0",
        "action.slot_1",
    ]
    state_slot_0 = candidate.streams[0]
    assert state_slot_0.fields["position"].indices == (5, 6, 7)
    assert state_slot_0.fields["orientation"].indices == (1, 2, 3, 4)
    assert state_slot_0.fields["orientation"].quaternion_order == "wxyz"
    assert state_slot_0.fields["position"].unit is None
    assert state_slot_0.fields["position"].frame is None


def _review(*, approved: bool) -> MappingReview:
    return MappingReview(
        dataset_alias="fixture",
        source_revision="v1",
        coordinate_frame="dataset_native",
        position_unit="m",
        timestamp_unit="s",
        orientation_quaternion_order="wxyz",
        slot_labels={"slot_0": "left", "slot_1": "right"},
        target_group_by_slot={"slot_0": "panda_2", "slot_1": "panda_1"},
        evidence=("manual-review-fixture",),
        reviewer="test",
        approved=approved,
    )


def test_review_must_be_explicit_before_candidate_promotion() -> None:
    candidate = build_pose_mapping_candidate(_info())

    with pytest.raises(ValueError, match="not approved"):
        apply_mapping_review(candidate, _review(approved=False))

    approved = apply_mapping_review(candidate, _review(approved=True))
    assert approved.coordinate_frame == "dataset_native"
    assert approved.timestamp.unit == "s"
    assert [stream.name for stream in approved.streams] == [
        "observation.state.left",
        "observation.state.right",
        "action.left",
        "action.right",
    ]
    assert approved.streams[0].fields["position"].unit == "m"
    assert approved.streams[0].fields["position"].frame == "dataset_native"
    assert approved.metadata["candidate_status"] == "APPROVED"
    assert approved.metadata["target_group.slot_0"] == "panda_2"


def test_candidate_cli_emits_review_only_mapping(tmp_path, capsys) -> None:
    from retargetlab.cli.main import EXIT_OK, app

    path = tmp_path / "info.json"
    path.write_text(
        json.dumps(
            {
                "dataset_name": "synthetic",
                "total_episodes": 1,
                "total_frames": 2,
                "total_tasks": 1,
                "total_chunks": 1,
                "fps": 30.0,
                "features": {
                    "timestamp": {"dtype": "float32", "shape": [1]},
                    "observation.state": {
                        "dtype": "float32",
                        "shape": [16],
                        "names": [
                            "gripper_0",
                            "epos_0_qw",
                            "epos_0_qx",
                            "epos_0_qy",
                            "epos_0_qz",
                            "epos_0_x",
                            "epos_0_y",
                            "epos_0_z",
                            "gripper_1",
                            "epos_1_qw",
                            "epos_1_qx",
                            "epos_1_qy",
                            "epos_1_qz",
                            "epos_1_x",
                            "epos_1_y",
                            "epos_1_z",
                        ],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    assert (
        app(
            [
                "candidate",
                str(path),
                "--dataset-alias",
                "fixture",
                "--source-revision",
                "v1",
                "--json",
            ]
        )
        == EXIT_OK
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "REVIEW_REQUIRED"
    assert payload["mapping"]["coordinate_frame"] == "UNRESOLVED"
    assert len(payload["mapping"]["streams"]) == 2
