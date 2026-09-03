import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as parquet
import pytest
from test_replay import _write_inputs

from retargetlab.cli.main import EXIT_OK, EXIT_SEMANTIC, app
from retargetlab.contracts import RobotProfile
from retargetlab.export import build_export_profile, write_synthetic_target_table
from retargetlab.run import (
    build_target_replay_bundle,
    build_target_replay_manifest,
    build_target_replay_trajectory,
    write_export_profile,
    write_target_replay_bundle,
    write_target_replay_manifest,
    write_target_replay_trajectory,
)


def _write_bundle(tmp_path: Path) -> Path:
    paths = _write_inputs(tmp_path)
    manifest = build_target_replay_manifest(
        replay_id="fixture-replay",
        trajectory_path=paths[0],
        profile_path=paths[1],
        recipe_path=paths[2],
        arm_solve_paths=(paths[3],),
        target_grippers_path=paths[4],
        coupling="independent",
    )
    manifest_path = tmp_path / "replay-manifest.json"
    write_target_replay_manifest(manifest_path, manifest)
    profile = RobotProfile.model_validate_json(paths[1].read_text(encoding="utf-8"))
    export_profile_path = tmp_path / "export-profile.json"
    write_export_profile(export_profile_path, build_export_profile(profile))

    state_path = tmp_path / "state-replay.json"
    write_target_replay_trajectory(
        state_path,
        build_target_replay_trajectory(
            manifest_path=manifest_path,
            export_profile_path=export_profile_path,
            stream_name="observation.state",
        ),
    )
    action_path = tmp_path / "action-replay.json"
    write_target_replay_trajectory(
        action_path,
        build_target_replay_trajectory(
            manifest_path=manifest_path,
            export_profile_path=export_profile_path,
            stream_name="action",
        ),
    )
    bundle_path = tmp_path / "replay-bundle.json"
    write_target_replay_bundle(
        bundle_path,
        build_target_replay_bundle(
            observation_state_path=state_path,
            action_path=action_path,
        ),
    )
    return bundle_path


def _write_source_table(path: Path, *, timestamps: list[float] | None = None) -> None:
    table = pa.table(
        {
            "index": pa.array([17, 18], type=pa.int64()),
            "episode_index": pa.array([3, 3], type=pa.int64()),
            "frame_index": pa.array([0, 1], type=pa.int64()),
            "timestamp": pa.array(timestamps or [0.0, 0.1], type=pa.float64()),
            "task_index": pa.array([0, 0], type=pa.int64()),
            "observation.state": pa.array(
                [[99.0, 99.0], [98.0, 98.0]],
                type=pa.list_(pa.float32(), 2),
            ),
            "action": pa.array(
                [[97.0, 97.0], [96.0, 96.0]],
                type=pa.list_(pa.float32(), 2),
            ),
            "next.done": pa.array([False, True], type=pa.bool_()),
        }
    )
    parquet.write_table(table, path)


def test_synthetic_table_writer_replaces_only_target_streams(tmp_path: Path) -> None:
    bundle_path = _write_bundle(tmp_path)
    source_path = tmp_path / "synthetic-source.parquet"
    output_path = tmp_path / "synthetic-target.parquet"
    _write_source_table(source_path)

    result = write_synthetic_target_table(
        source_path=source_path,
        target_replay_bundle_path=bundle_path,
        output_path=output_path,
    )
    output = parquet.read_table(output_path)

    assert result.source_scope == "synthetic_public_only"
    assert result.frame_count == 2
    assert result.preserved_columns == (
        "index",
        "episode_index",
        "frame_index",
        "timestamp",
        "task_index",
        "next.done",
    )
    assert output.column_names == [
        "index",
        "episode_index",
        "frame_index",
        "timestamp",
        "task_index",
        "observation.state",
        "action",
        "next.done",
        "valid.retarget",
    ]
    for column_name in ("observation.state", "action"):
        for observed, expected in zip(
            output[column_name].to_pylist(), [[0.0, 0.0], [0.1, 0.044]], strict=True
        ):
            assert observed == pytest.approx(expected, abs=1e-6)
    assert output["index"].to_pylist() == [17, 18]
    assert output["task_index"].to_pylist() == [0, 0]
    assert output["valid.retarget"].to_pylist() == [True, True]
    assert pa.types.is_fixed_size_list(output.schema.field("action").type)
    metadata = output.schema.metadata or {}
    assert metadata[b"retargetlab.source_scope"] == b"synthetic_public_only"


def test_synthetic_table_writer_rejects_timestamp_mismatch_without_output(
    tmp_path: Path,
) -> None:
    bundle_path = _write_bundle(tmp_path)
    source_path = tmp_path / "synthetic-source.parquet"
    output_path = tmp_path / "synthetic-target.parquet"
    _write_source_table(source_path, timestamps=[0.0, 0.2])

    with pytest.raises(ValueError, match="timestamp does not match"):
        write_synthetic_target_table(
            source_path=source_path,
            target_replay_bundle_path=bundle_path,
            output_path=output_path,
        )
    assert not output_path.exists()


def test_synthetic_table_writer_cli_is_explicitly_scoped(tmp_path: Path, capsys) -> None:
    bundle_path = _write_bundle(tmp_path)
    source_path = tmp_path / "synthetic-source.parquet"
    output_path = tmp_path / "synthetic-target.parquet"
    _write_source_table(source_path)

    assert (
        app(
            [
                "write-synthetic-table",
                "--source",
                str(source_path),
                "--target-replay-bundle",
                str(bundle_path),
                "--output",
                str(output_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["artifact_type"] == "synthetic_target_table"
    assert payload["source_scope"] == "synthetic_public_only"

    assert (
        app(
            [
                "write-synthetic-table",
                "--source",
                str(source_path),
                "--target-replay-bundle",
                str(bundle_path),
                "--output",
                str(output_path),
                "--json",
            ]
        )
        == EXIT_SEMANTIC
    )
    assert json.loads(capsys.readouterr().out)["status"] == "INVALID_INPUT"
