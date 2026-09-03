import json

import pytest

from retargetlab.io import analyze_command_timing


def _write_fixture(tmp_path, *, encoded_action: bool = False):
    pa = pytest.importorskip("pyarrow")
    parquet = pytest.importorskip("pyarrow.parquet")
    rows = {
        "episode_index": [],
        "frame_index": [],
        "observation.state.position": [],
        "action.position": [],
    }
    for episode in range(2):
        state = [
            [float(episode * 100 + frame), float(episode * 1000 + 2 * frame)] for frame in range(8)
        ]
        action = state[2:] + [[-1.0, -1.0], [-1.0, -1.0]]
        if encoded_action:
            action = [[2.0 * row[0] + 1.0, row[1]] for row in action]
        rows["episode_index"].extend([episode] * 8)
        rows["frame_index"].extend(range(8))
        rows["observation.state.position"].extend(state)
        rows["action.position"].extend(action)
    path = tmp_path / "timing.parquet"
    parquet.write_table(
        pa.table(
            rows,
            schema=pa.schema(
                [
                    pa.field("episode_index", pa.int64()),
                    pa.field("frame_index", pa.int64()),
                    pa.field(
                        "observation.state.position",
                        pa.list_(pa.float32()),
                    ),
                    pa.field("action.position", pa.list_(pa.float32())),
                ]
            ),
        ),
        path,
    )
    return path


def test_command_timing_analysis_ranks_expected_shift_without_source_values(tmp_path) -> None:
    path = _write_fixture(tmp_path)

    report = analyze_command_timing(
        path,
        dataset_alias="fixture",
        source_revision="v1",
        episode_indices=(0, 1),
        joint_indices=(0, 1),
        max_shift=4,
        expected_shift_range=(2, 2),
    )

    assert report.status == "SUPPORTED"
    assert report.best_shift == 2
    assert report.shifts[2].rmse == 0.0
    assert report.frame_count == 16
    assert report.joint_count == 2
    assert "observation.state.position" not in report.model_dump_json()

    encoded = _write_fixture(tmp_path, encoded_action=True)
    transformed = analyze_command_timing(
        encoded,
        dataset_alias="fixture",
        source_revision="v1",
        episode_indices=(0, 1),
        joint_indices=(0, 1),
        action_scales=(0.5, 1.0),
        action_offsets=(-0.5, 0.0),
        max_shift=4,
        expected_shift_range=(2, 2),
    )
    assert transformed.best_shift == 2
    assert transformed.action_scales == (0.5, 1.0)


def test_command_timing_cli_writes_conflict_status_and_report(tmp_path, capsys) -> None:
    from retargetlab.cli.main import EXIT_QUALITY, app

    data_path = _write_fixture(tmp_path)
    output_path = tmp_path / "timing-report.json"
    assert (
        app(
            [
                "analyze-timing",
                "--data",
                str(data_path),
                "--dataset-alias",
                "fixture",
                "--source-revision",
                "v1",
                "--episode-indices",
                "0",
                "1",
                "--joint-indices",
                "0",
                "1",
                "--max-shift",
                "4",
                "--expected-shifts",
                "0",
                "1",
                "--output",
                str(output_path),
                "--json",
            ]
        )
        == EXIT_QUALITY
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "CONFLICTED"
    assert payload["best_shift"] == 2
    assert output_path.is_file()
    assert "action.position" not in output_path.read_text(encoding="utf-8")
