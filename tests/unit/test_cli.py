import json

from retargetlab.cli.main import EXIT_OK, EXIT_QUALITY, EXIT_SEMANTIC, app
from retargetlab.contracts import (
    CanonicalFrame,
    CanonicalTrajectory,
    DatasetReport,
    EpisodeReport,
    FrameDiagnostics,
    IKStatus,
    Pose,
)


def test_doctor_json_is_structured(capsys) -> None:
    exit_code = app(["doctor", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code in {EXIT_OK, 5}
    assert payload["command"] == "doctor"
    assert set(payload["dependencies"]) >= {"numpy", "pydantic"}


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
