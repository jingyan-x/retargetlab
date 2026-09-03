import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as parquet
import pytest
from test_replay import _write_inputs

from retargetlab.cli.main import EXIT_OK, EXIT_SEMANTIC, app
from retargetlab.contracts import ExportInputGate, RobotProfile
from retargetlab.export import (
    build_export_profile,
    verify_synthetic_target_table,
    write_synthetic_target_table,
)
from retargetlab.run import (
    build_synthetic_table_write_preflight,
    build_target_replay_bundle,
    build_target_replay_manifest,
    build_target_replay_trajectory,
    verify_synthetic_table_write_preflight,
    verify_target_replay_bundle,
    write_export_profile,
    write_synthetic_table_write_preflight,
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


def _write_multi_episode_source_table(path: Path) -> None:
    table = pa.table(
        {
            "index": pa.array([17, 18, 27, 28], type=pa.int64()),
            "episode_index": pa.array([3, 3, 4, 4], type=pa.int64()),
            "frame_index": pa.array([0, 1, 0, 1], type=pa.int64()),
            "timestamp": pa.array([0.0, 0.1, 0.0, 0.1], type=pa.float64()),
            "task_index": pa.array([0, 0, 1, 1], type=pa.int64()),
            "observation.state": pa.array(
                [[99.0, 99.0], [98.0, 98.0], [89.0, 89.0], [88.0, 88.0]],
                type=pa.list_(pa.float32(), 2),
            ),
            "action": pa.array(
                [[97.0, 97.0], [96.0, 96.0], [87.0, 87.0], [86.0, 86.0]],
                type=pa.list_(pa.float32(), 2),
            ),
            "next.done": pa.array([False, True, False, True], type=pa.bool_()),
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
    assert result.selected_episode_indices == (3,)
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
    verification = verify_synthetic_target_table(
        source_path=source_path,
        target_replay_bundle_path=bundle_path,
        output_path=output_path,
    )
    assert verification.status == "VERIFIED"
    assert verification.output_table_sha256 == result.output_table_sha256


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


def test_synthetic_table_verifier_rejects_tampered_target_vector(tmp_path: Path) -> None:
    bundle_path = _write_bundle(tmp_path)
    source_path = tmp_path / "synthetic-source.parquet"
    output_path = tmp_path / "synthetic-target.parquet"
    _write_source_table(source_path)
    write_synthetic_target_table(
        source_path=source_path,
        target_replay_bundle_path=bundle_path,
        output_path=output_path,
    )

    output = parquet.read_table(output_path)
    tampered = output.set_column(
        output.column_names.index("action"),
        "action",
        pa.array([[1.0, 1.0], [1.0, 1.0]], type=pa.list_(pa.float32(), 2)),
    )
    parquet.write_table(tampered, output_path)

    with pytest.raises(ValueError, match="vector does not match replay"):
        verify_synthetic_target_table(
            source_path=source_path,
            target_replay_bundle_path=bundle_path,
            output_path=output_path,
        )


def test_synthetic_table_writer_cli_is_explicitly_scoped(tmp_path: Path, capsys) -> None:
    bundle_path = _write_bundle(tmp_path)
    source_path = tmp_path / "synthetic-source.parquet"
    output_path = tmp_path / "synthetic-target.parquet"
    report_path = tmp_path / "synthetic-write-report.json"
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
                "--report",
                str(report_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["artifact_type"] == "synthetic_target_table"
    assert payload["source_scope"] == "synthetic_public_only"
    assert payload["report_path"] == str(report_path)

    assert (
        app(
            [
                "verify-synthetic-table",
                "--source",
                str(source_path),
                "--target-replay-bundle",
                str(bundle_path),
                "--output",
                str(output_path),
                "--report",
                str(report_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    assert json.loads(capsys.readouterr().out)["status"] == "VERIFIED"

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


def test_synthetic_table_preflight_binds_gate_source_and_bundle(tmp_path: Path) -> None:
    bundle_path = _write_bundle(tmp_path)
    source_path = tmp_path / "synthetic-source.parquet"
    output_path = tmp_path / "synthetic-target.parquet"
    preflight_path = tmp_path / "synthetic-preflight.json"
    _write_source_table(source_path)
    bundle_verification = verify_target_replay_bundle(bundle_path)
    gate_path = tmp_path / "export-input-gate.json"
    gate = ExportInputGate(
        dataset_alias="fixture",
        source_revision="v1",
        data_profile_sha256="a" * 64,
        coverage_sha256="b" * 64,
        target_replay_bundle_sha256=bundle_verification.bundle_sha256,
        export_profile_sha256=bundle_verification.export_profile_sha256,
        robot_id="fixture",
        source_frame_count=2,
        target_replay_frame_count=2,
        training_episode_allowlist=(3,),
    )
    gate_path.write_text(gate.model_dump_json(), encoding="utf-8")

    preflight = build_synthetic_table_write_preflight(
        export_input_gate_path=gate_path,
        source_table_path=source_path,
        target_replay_bundle_path=bundle_path,
        output_table_path=output_path,
    )
    write_synthetic_table_write_preflight(preflight_path, preflight)
    verification = verify_synthetic_table_write_preflight(preflight_path)

    assert preflight.source_scope == "synthetic_public_only"
    assert preflight.training_episode_allowlist == (3,)
    assert verification.status == "VERIFIED"
    assert verification.target_replay_frame_count == 2
    result = write_synthetic_target_table(
        source_path=source_path,
        target_replay_bundle_path=bundle_path,
        output_path=output_path,
        preflight_path=preflight_path,
    )
    assert result.preflight_path == str(preflight_path.resolve())
    assert result.preflight_sha256 == verification.preflight_sha256
    output_verification = verify_synthetic_target_table(
        source_path=source_path,
        target_replay_bundle_path=bundle_path,
        output_path=output_path,
        preflight_path=preflight_path,
    )
    assert output_verification.preflight_sha256 == verification.preflight_sha256
    with pytest.raises(FileExistsError):
        write_synthetic_table_write_preflight(preflight_path, preflight)

    source_path.write_bytes(source_path.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="does not match its bound inputs"):
        verify_synthetic_table_write_preflight(preflight_path)


def test_synthetic_table_preflight_cli_round_trip(tmp_path: Path, capsys) -> None:
    bundle_path = _write_bundle(tmp_path)
    source_path = tmp_path / "synthetic-source.parquet"
    output_path = tmp_path / "synthetic-target.parquet"
    gate_path = tmp_path / "export-input-gate.json"
    preflight_path = tmp_path / "synthetic-preflight.json"
    _write_source_table(source_path)
    bundle_verification = verify_target_replay_bundle(bundle_path)
    gate = ExportInputGate(
        dataset_alias="fixture",
        source_revision="v1",
        data_profile_sha256="a" * 64,
        coverage_sha256="b" * 64,
        target_replay_bundle_sha256=bundle_verification.bundle_sha256,
        export_profile_sha256=bundle_verification.export_profile_sha256,
        robot_id="fixture",
        source_frame_count=2,
        target_replay_frame_count=2,
        training_episode_allowlist=(3,),
    )
    gate_path.write_text(gate.model_dump_json(), encoding="utf-8")

    assert (
        app(
            [
                "build-synthetic-table-preflight",
                "--export-input-gate",
                str(gate_path),
                "--source",
                str(source_path),
                "--target-replay-bundle",
                str(bundle_path),
                "--output-table",
                str(output_path),
                "--output",
                str(preflight_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    assert json.loads(capsys.readouterr().out)["status"] == "READY"

    assert (
        app(
            [
                "verify-synthetic-table-preflight",
                "--preflight",
                str(preflight_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    verification_payload = json.loads(capsys.readouterr().out)
    assert verification_payload["status"] == "VERIFIED"


def test_synthetic_table_writer_uses_preflight_episode_selection(tmp_path: Path) -> None:
    bundle_path = _write_bundle(tmp_path)
    source_path = tmp_path / "synthetic-multi-episode-source.parquet"
    output_path = tmp_path / "synthetic-selected-target.parquet"
    preflight_path = tmp_path / "synthetic-selected-preflight.json"
    _write_multi_episode_source_table(source_path)
    bundle_verification = verify_target_replay_bundle(bundle_path)
    gate_path = tmp_path / "export-input-gate.json"
    gate = ExportInputGate(
        dataset_alias="fixture",
        source_revision="v1",
        data_profile_sha256="a" * 64,
        coverage_sha256="b" * 64,
        target_replay_bundle_sha256=bundle_verification.bundle_sha256,
        export_profile_sha256=bundle_verification.export_profile_sha256,
        robot_id="fixture",
        source_frame_count=4,
        target_replay_frame_count=2,
        training_episode_allowlist=(3,),
    )
    gate_path.write_text(gate.model_dump_json(), encoding="utf-8")
    preflight = build_synthetic_table_write_preflight(
        export_input_gate_path=gate_path,
        source_table_path=source_path,
        target_replay_bundle_path=bundle_path,
        output_table_path=output_path,
    )
    write_synthetic_table_write_preflight(preflight_path, preflight)

    result = write_synthetic_target_table(
        source_path=source_path,
        target_replay_bundle_path=bundle_path,
        output_path=output_path,
        preflight_path=preflight_path,
    )
    output = parquet.read_table(output_path)

    assert result.selected_episode_indices == (3,)
    assert output.num_rows == 2
    assert output["index"].to_pylist() == [17, 18]
    assert output["episode_index"].to_pylist() == [3, 3]
    assert output["frame_index"].to_pylist() == [0, 1]
    assert output["task_index"].to_pylist() == [0, 0]
