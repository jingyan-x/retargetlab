import json

import pytest

from retargetlab.contracts import DatasetCoverage
from retargetlab.io import scan_lerobot_coverage
from retargetlab.run import write_dataset_coverage


def _write_fixture(tmp_path, *, gap: bool = False):
    pa = pytest.importorskip("pyarrow")
    parquet = pytest.importorskip("pyarrow.parquet")
    info_path = tmp_path / "info.json"
    info_path.write_text(
        json.dumps(
            {
                "dataset_name": "synthetic",
                "total_episodes": 2,
                "total_frames": 3,
                "total_tasks": 1,
                "total_chunks": 1,
                "fps": 30.0,
                "features": {
                    "timestamp": {"dtype": "float32", "shape": [1]},
                    "observation.state": {
                        "dtype": "float32",
                        "shape": [2],
                        "names": ["x", "y"],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    data_path = tmp_path / "data.parquet"
    vector = pa.FixedSizeListArray.from_arrays(
        pa.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0], type=pa.float32()),
        list_size=2,
    )
    parquet.write_table(
        pa.table(
            {
                "timestamp": pa.array([0.0, 0.01, 0.02], type=pa.float32()),
                "observation.state": vector,
            }
        ),
        data_path,
    )
    episodes_path = tmp_path / "episodes.parquet"
    starts = [0, 2] if gap else [0, 1]
    parquet.write_table(
        pa.table(
            {
                "episode_index": pa.array([0, 1]),
                "dataset_from_index": pa.array(starts),
                "dataset_to_index": pa.array([1, 3]),
            }
        ),
        episodes_path,
    )
    tasks_path = tmp_path / "tasks.parquet"
    parquet.write_table(pa.table({"task_index": pa.array([0])}), tasks_path)
    stats_path = tmp_path / "stats.json"
    stats_path.write_text(json.dumps({"observation.state": {"min": []}}), encoding="utf-8")
    return info_path, data_path, episodes_path, tasks_path, stats_path


def _scan(tmp_path, *, gap: bool = False) -> DatasetCoverage:
    paths = _write_fixture(tmp_path, gap=gap)
    return scan_lerobot_coverage(
        info_path=paths[0],
        data_path=paths[1],
        episodes_path=paths[2],
        tasks_path=paths[3],
        stats_path=paths[4],
        dataset_alias="fixture",
        source_revision="v1",
        validation_scope="synthetic fixture",
    )


def test_coverage_scan_binds_revision_and_intervals(tmp_path) -> None:
    coverage = _scan(tmp_path)

    assert coverage.status == "COMPLETE"
    assert coverage.coverage_complete is True
    assert coverage.observed_episode_count == 2
    assert coverage.observed_frame_count == 3
    assert coverage.structure_compatible is True
    assert coverage.shape_normalized == ("timestamp",)
    assert coverage.episode_ranges[1].start_row == 1

    output = tmp_path / "coverage.json"
    write_dataset_coverage(output, coverage)
    text = output.read_text(encoding="utf-8")
    assert "observation.state" in text
    assert "3.14" not in text
    with pytest.raises(FileExistsError):
        write_dataset_coverage(output, coverage)


def test_coverage_scan_reports_gap_without_failing_to_emit_summary(tmp_path) -> None:
    coverage = _scan(tmp_path, gap=True)

    assert coverage.status == "INCONSISTENT"
    assert coverage.coverage_complete is False
    assert "episode intervals are not contiguous" in coverage.blocking_reasons
