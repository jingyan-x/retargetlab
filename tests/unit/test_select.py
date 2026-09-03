import json

import pytest

from retargetlab.contracts import (
    ColumnRef,
    MappingReview,
    MappingSpec,
    ReviewEvidenceChecklist,
    StreamMapping,
    StructureComparison,
)
from retargetlab.io import run_parquet_calibration, select_calibration_rows


def _write_fixture(tmp_path):
    pa = pytest.importorskip("pyarrow")
    parquet = pytest.importorskip("pyarrow.parquet")
    episodes_path = tmp_path / "episodes.parquet"
    parquet.write_table(
        pa.table(
            {
                "episode_index": pa.array([0, 1], type=pa.int64()),
                "dataset_from_index": pa.array([0, 4], type=pa.int64()),
                "dataset_to_index": pa.array([4, 8], type=pa.int64()),
            }
        ),
        episodes_path,
    )
    state = [[float(index), 0.0, 0.0, 1.0, 0.0, 0.0, 0.0] for index in range(8)]
    data_path = tmp_path / "data.parquet"
    parquet.write_table(
        pa.table(
            {
                "episode_index": pa.array([0] * 4 + [1] * 4, type=pa.int64()),
                "frame_index": pa.array(list(range(4)) * 2, type=pa.int64()),
                "index": pa.array(list(range(8)), type=pa.int64()),
                "timestamp": pa.array([index / 10 for index in range(8)], type=pa.float32()),
                "observation.state": pa.array(
                    state,
                    type=pa.list_(pa.float32()),
                ),
                "action": pa.array(state, type=pa.list_(pa.float32())),
            }
        ),
        data_path,
    )
    return data_path, episodes_path


def test_selector_preserves_episode_boundaries_and_provenance(tmp_path) -> None:
    data_path, episodes_path = _write_fixture(tmp_path)

    rows, selection = select_calibration_rows(
        data_path,
        episodes_path,
        dataset_alias="fixture",
        source_revision="v1",
        episode_indices=(0, 1),
        frames_per_episode=2,
    )

    assert [row["index"] for row in rows] == [0, 3, 4, 7]
    assert [row["episode_index"] for row in rows] == [0, 0, 1, 1]
    assert selection.selected_frame_count == 4
    assert selection.selected_row_indices == (0, 3, 4, 7)
    assert [item.length for item in selection.episode_ranges] == [4, 4]
    assert selection.data_sha256
    assert "values" not in repr(selection)


def test_selector_rejects_unbounded_or_missing_requests(tmp_path) -> None:
    data_path, episodes_path = _write_fixture(tmp_path)

    with pytest.raises(ValueError, match="must not exceed 60"):
        select_calibration_rows(
            data_path,
            episodes_path,
            dataset_alias="fixture",
            source_revision="v1",
            episode_indices=(0, 1),
            frames_per_episode=31,
        )
    with pytest.raises(ValueError, match="missing requested episodes"):
        select_calibration_rows(
            data_path,
            episodes_path,
            dataset_alias="fixture",
            source_revision="v1",
            episode_indices=(2,),
            frames_per_episode=1,
        )


def _approved_spec() -> MappingSpec:
    frame = "dataset_native"
    return MappingSpec(
        dataset_alias="fixture",
        source_revision="v1",
        coordinate_frame=frame,
        timestamp=ColumnRef(source="timestamp", expected_shape=(), unit="s"),
        streams=(
            StreamMapping(
                name="left",
                role="robot_state",
                fields={
                    "position": ColumnRef(
                        source="observation.state",
                        expected_shape=(7,),
                        indices=(0, 1, 2),
                        unit="m",
                        frame=frame,
                    ),
                    "orientation": ColumnRef(
                        source="observation.state",
                        expected_shape=(7,),
                        indices=(3, 4, 5, 6),
                        frame=frame,
                        quaternion_order="wxyz",
                    ),
                },
            ),
        ),
        metadata={
            "candidate_status": "APPROVED",
            "accepted_unverified_shape": "false",
            "reviewer": "test",
            "review_evidence": "fixture",
            "target_group.slot_0": "panda_2",
            "target_group.slot_1": "panda_1",
        },
    )


def _full_comparison() -> StructureComparison:
    return StructureComparison(
        compatible=True,
        fully_verified=True,
        alias_match=True,
        revision_match=True,
        row_count_match=True,
        declared_total_frames=8,
        observed_row_count=8,
    )


def test_combined_parquet_calibration_preflights_before_reading_rows(tmp_path) -> None:
    data_path, episodes_path = _write_fixture(tmp_path)

    trajectory, report, selection = run_parquet_calibration(
        data_path,
        episodes_path,
        _approved_spec(),
        _full_comparison(),
        episode_indices=(0,),
        frames_per_episode=2,
        columns=("episode_index", "frame_index", "index", "timestamp", "observation.state"),
    )

    assert trajectory.frame_count == 2
    assert report.status == "COMPLETED"
    assert selection.selected_row_indices == (0, 3)

    unapproved = _approved_spec().model_copy(
        update={"metadata": {"candidate_status": "REVIEW_REQUIRED"}}
    )
    with pytest.raises(ValueError, match="approved mapping"):
        run_parquet_calibration(
            tmp_path / "missing.parquet",
            tmp_path / "missing-episodes.parquet",
            unapproved,
            _full_comparison(),
            episode_indices=(0,),
            frames_per_episode=1,
            columns=("episode_index", "frame_index", "index", "timestamp", "observation.state"),
        )


def test_calibrate_cli_writes_audit_only_for_approved_slice(tmp_path, capsys) -> None:
    from retargetlab.cli.main import EXIT_OK, app

    data_path, episodes_path = _write_fixture(tmp_path)
    frame = "UNRESOLVED"
    candidate = MappingSpec(
        dataset_alias="fixture",
        source_revision="v1",
        coordinate_frame=frame,
        timestamp=ColumnRef(source="timestamp", expected_shape=()),
        streams=(
            StreamMapping(
                name="observation.state.slot_0",
                role="robot_state",
                fields={
                    "position": ColumnRef(
                        source="observation.state",
                        expected_shape=(7,),
                        indices=(0, 1, 2),
                    ),
                    "orientation": ColumnRef(
                        source="observation.state",
                        expected_shape=(7,),
                        indices=(3, 4, 5, 6),
                        quaternion_order="wxyz",
                    ),
                },
            ),
        ),
        metadata={"candidate_status": "REVIEW_REQUIRED"},
    )
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(
        json.dumps({"mapping": candidate.model_dump(mode="json")}),
        encoding="utf-8",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(
        MappingReview(
            dataset_alias="fixture",
            source_revision="v1",
            coordinate_frame="dataset_native",
            position_unit="m",
            timestamp_unit="s",
            orientation_quaternion_order="wxyz",
            slot_labels={"slot_0": "left", "slot_1": "right"},
            target_group_by_slot={"slot_0": "panda_2", "slot_1": "panda_1"},
            evidence=("synthetic-fixture",),
            reviewer="test",
            accept_unverified_shape=True,
            approved=True,
            checklist=ReviewEvidenceChecklist(
                structure_evidence_reviewed=True,
                coordinate_frame_confirmed=True,
                position_unit_confirmed=True,
                timestamp_unit_confirmed=True,
                orientation_order_confirmed=True,
                slot_labels_confirmed=True,
                target_groups_confirmed=True,
                shape_acceptance="ACCEPTED",
            ),
        ).model_dump_json(),
        encoding="utf-8",
    )
    comparison_path = tmp_path / "comparison.json"
    comparison_path.write_text(
        StructureComparison(
            compatible=True,
            fully_verified=False,
            alias_match=True,
            revision_match=True,
            row_count_match=True,
            declared_total_frames=8,
            observed_row_count=8,
            shape_unverified=("observation.state",),
        ).model_dump_json(),
        encoding="utf-8",
    )
    decision_path = tmp_path / "review-decision.json"
    assert (
        app(
            [
                "review-mapping",
                str(candidate_path),
                "--review",
                str(review_path),
                "--comparison",
                str(comparison_path),
                "--output",
                str(decision_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    decision_payload = json.loads(capsys.readouterr().out)
    assert decision_payload["decision_output"] == str(decision_path)
    output_path = tmp_path / "audit.json"

    assert (
        app(
            [
                "calibrate",
                "--data",
                str(data_path),
                "--episodes",
                str(episodes_path),
                "--candidate",
                str(candidate_path),
                "--review",
                str(review_path),
                "--comparison",
                str(comparison_path),
                "--decision",
                str(decision_path),
                "--episode-indices",
                "0",
                "--frames-per-episode",
                "2",
                "--output",
                str(output_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "COMPLETED"
    assert payload["frame_count"] == 2
    recipe_payload = json.loads(
        (output_path.parent / "calibration-recipe.json").read_text(encoding="utf-8")
    )
    assert recipe_payload["decision_sha256"]
    artifact_text = output_path.read_text(encoding="utf-8")
    assert "poses" not in artifact_text
    assert "position_m" not in artifact_text
    assert (
        app(
            [
                "verify-calibration",
                "--run",
                str(output_path.parent),
                "--json",
            ]
        )
        == EXIT_OK
    )
    verification_payload = json.loads(capsys.readouterr().out)
    assert verification_payload["status"] == "VERIFIED"
    assert verification_payload["selected_frame_count"] == 2
