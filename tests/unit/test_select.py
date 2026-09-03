import pytest

from retargetlab.contracts import ColumnRef, MappingSpec, StreamMapping, StructureComparison
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
