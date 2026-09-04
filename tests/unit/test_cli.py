import json

import pytest

from retargetlab.cli.main import EXIT_OK, EXIT_QUALITY, EXIT_SEMANTIC, app
from retargetlab.contracts import (
    CanonicalFrame,
    CanonicalTrajectory,
    ColumnRef,
    DatasetReport,
    EpisodeReport,
    FrameDiagnostics,
    IKStatus,
    MappingSpec,
    Pose,
    StreamMapping,
    StructureField,
    StructureManifest,
)


def test_doctor_json_is_structured(capsys) -> None:
    exit_code = app(["doctor", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code in {EXIT_OK, 5}
    assert payload["command"] == "doctor"
    assert set(payload["dependencies"]) >= {"numpy", "pydantic"}
    assert isinstance(payload["optional_missing"], list)


def test_inspect_canonical_json_is_read_only(tmp_path, capsys) -> None:
    pose = Pose(position_m=(0.0, 0.0, 0.0), quaternion_wxyz=(1.0, 0.0, 0.0, 0.0))
    trajectory = CanonicalTrajectory(frames=[CanonicalFrame(timestamp_s=0.0, poses={"arm": pose})])
    path = tmp_path / "trajectory.json"
    path.write_text(trajectory.model_dump_json(), encoding="utf-8")

    assert app(["inspect", str(path), "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["frame_count"] == 1
    assert payload["stream_names"] == ["arm"]


def test_inspect_invalid_input_returns_semantic_exit(tmp_path, capsys) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{}", encoding="utf-8")

    assert app(["inspect", str(path), "--json"]) == EXIT_SEMANTIC
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "INVALID_INPUT"


def test_inspect_invalid_human_input_is_reported_without_traceback(tmp_path, capsys) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{}", encoding="utf-8")

    assert app(["inspect", str(path)]) == EXIT_SEMANTIC
    captured = capsys.readouterr()
    assert "invalid input" in captured.err


def test_inspect_parquet_reports_structure_only(tmp_path, capsys) -> None:
    pa = pytest.importorskip("pyarrow")
    parquet = pytest.importorskip("pyarrow.parquet")
    path = tmp_path / "fixture.parquet"
    parquet.write_table(pa.table({"timestamp": pa.array([0.0, 0.01])}), path)

    assert (
        app(
            [
                "inspect",
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
    assert payload["kind"] == "parquet"
    assert payload["row_count"] == 2
    assert payload["fields"]["timestamp"]["shape"] == []
    assert payload["source_sha256"]


def test_inspect_parquet_compares_lerobot_metadata_without_rows(tmp_path, capsys) -> None:
    pa = pytest.importorskip("pyarrow")
    parquet = pytest.importorskip("pyarrow.parquet")
    data_path = tmp_path / "data.parquet"
    parquet.write_table(
        pa.table(
            {
                "timestamp": pa.array([0.0, 0.01], type=pa.float32()),
                "state": pa.array(
                    [[0.0, 1.0], [2.0, 3.0]],
                    type=pa.list_(pa.float32()),
                ),
            }
        ),
        data_path,
    )
    info_path = tmp_path / "info.json"
    info_path.write_text(
        json.dumps(
            {
                "dataset_name": "synthetic",
                "total_episodes": 1,
                "total_frames": 2,
                "total_tasks": 1,
                "total_chunks": 1,
                "fps": 30.0,
                "features": {"state": {"dtype": "float32", "shape": [2], "names": ["x", "y"]}},
            }
        ),
        encoding="utf-8",
    )

    assert (
        app(
            [
                "inspect",
                str(data_path),
                "--dataset-alias",
                "fixture",
                "--source-revision",
                "v1",
                "--metadata",
                str(info_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["comparison"]["compatible"] is True
    assert payload["comparison"]["fully_verified"] is False
    assert payload["comparison"]["shape_unverified"] == ["state"]
    assert "values" not in captured.out


def test_diagnose_completed_run_uses_quality_exit_without_joint_arrays(tmp_path, capsys) -> None:
    frame = FrameDiagnostics(
        frame_index=0,
        solver_status=IKStatus.CONVERGED,
        position_error_m=0.006,
        orientation_error_rad=0.01,
        collision_free=True,
    )
    episode = EpisodeReport(
        episode_index=0,
        frame_count=1,
        nominal_rate=0.0,
        relaxed_rate=0.0,
        collision_fraction=0.0,
        joint_limit_violation_fraction=0.0,
        delta_violation_fraction=0.0,
        status="FAIL",
        frames=(frame,),
    )
    report = DatasetReport(episode_count=1, episodes=(episode,), status="FAIL")
    run_path = tmp_path / "run"
    (run_path / "result").mkdir(parents=True)
    (run_path / "result" / "report.json").write_text(report.model_dump_json(), encoding="utf-8")

    assert app(["diagnose", "--run", str(run_path), "--json"]) == EXIT_QUALITY
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "FAIL"
    assert "q" not in json.dumps(payload)


def test_validate_input_json_uses_explicit_mapping(tmp_path, capsys) -> None:
    manifest = StructureManifest(
        dataset_alias="fixture",
        source_revision="v1",
        row_count=1,
        fields={"timestamp": StructureField(dtype="float64", shape=())},
    )
    spec = MappingSpec(
        dataset_alias="fixture",
        source_revision="v1",
        coordinate_frame="dataset_native",
        timestamp=ColumnRef(source="timestamp", expected_shape=()),
        streams=(
            StreamMapping(
                name="state",
                role="robot_state",
                fields={"time": ColumnRef(source="timestamp", expected_shape=())},
            ),
        ),
    )
    manifest_path = tmp_path / "manifest.json"
    spec_path = tmp_path / "spec.json"
    manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")
    spec_path.write_text(spec.model_dump_json(), encoding="utf-8")

    assert (
        app(["validate-input", str(manifest_path), "--spec", str(spec_path), "--json"]) == EXIT_OK
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True


def test_normalize_json_writes_canonical_output_once(tmp_path, capsys) -> None:
    spec = MappingSpec(
        dataset_alias="fixture",
        source_revision="v1",
        coordinate_frame="dataset_native",
        timestamp=ColumnRef(source="time", expected_shape=()),
        streams=(
            StreamMapping(
                name="state",
                role="robot_state",
                fields={
                    "position": ColumnRef(
                        source="position",
                        expected_shape=(3,),
                        unit="m",
                        frame="dataset_native",
                    ),
                    "orientation": ColumnRef(
                        source="orientation",
                        expected_shape=(4,),
                        frame="dataset_native",
                        quaternion_order="wxyz",
                    ),
                },
            ),
        ),
    )
    rows = [
        {
            "time": 0.0,
            "position": [0.0, 0.0, 0.1],
            "orientation": [1.0, 0.0, 0.0, 0.0],
        }
    ]
    spec_path = tmp_path / "spec.json"
    rows_path = tmp_path / "rows.json"
    output_path = tmp_path / "canonical.json"
    spec_path.write_text(spec.model_dump_json(), encoding="utf-8")
    rows_path.write_text(json.dumps(rows), encoding="utf-8")

    assert (
        app(
            [
                "normalize",
                str(rows_path),
                "--spec",
                str(spec_path),
                "--output",
                str(output_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "NORMALIZED"
    assert "position" not in payload
    normalized = CanonicalTrajectory.model_validate_json(output_path.read_text(encoding="utf-8"))
    assert normalized.frame_count == 1

    assert (
        app(
            [
                "normalize",
                str(rows_path),
                "--spec",
                str(spec_path),
                "--output",
                str(output_path),
                "--json",
            ]
        )
        == EXIT_SEMANTIC
    )
