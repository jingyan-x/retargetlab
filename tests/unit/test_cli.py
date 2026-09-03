import json

from retargetlab.cli.main import EXIT_OK, EXIT_SEMANTIC, app
from retargetlab.contracts import CanonicalFrame, CanonicalTrajectory, Pose


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
