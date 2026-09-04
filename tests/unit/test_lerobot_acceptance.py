from pathlib import Path

import numpy as np
from test_replay import _write_inputs

import retargetlab.run.lerobot_acceptance as acceptance
from retargetlab.contracts import (
    CanonicalTrajectory,
    LeRobotTrainingDatasetConfig,
    TargetReplayFrame,
    TargetReplayTrajectory,
)
from retargetlab.export import build_export_profile, build_target_vector_layout
from retargetlab.kinematics.pinocchio_backend import PinocchioBackend
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes


def _ready_config(root: Path) -> LeRobotTrainingDatasetConfig:
    return LeRobotTrainingDatasetConfig(
        status="READY",
        dataset_alias="synthetic-fixture",
        repo_id="synthetic-fixture",
        root=str(root),
        episodes=(0, 2),
        plan_path="/tmp/plan.json",
        plan_sha256="a" * 64,
        preflight_path="/tmp/preflight.json",
        preflight_sha256="b" * 64,
    )


def test_acceptance_reports_missing_optional_runtime(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    config = _ready_config(tmp_path / "dataset")
    config_path.write_text(config.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(acceptance, "verify_lerobot_training_dataset_config", lambda _: config)
    monkeypatch.setattr(acceptance.importlib.util, "find_spec", lambda _: None)

    report = acceptance.run_lerobot_acceptance(config_path)

    assert report.status == "ENVIRONMENT_UNAVAILABLE"
    assert report.episodes == (0, 2)
    assert tuple(check.name for check in report.checks) == (
        "config_contract",
        "episode_allowlist",
        "time_window",
        "normalization_batch",
        "fk_semantic_recheck",
    )
    assert report.checks[0].status == "PASSED"
    assert all(check.status == "SKIPPED" for check in report.checks[1:])
    assert "optional_runtime_missing:lerobot" in report.blocking_reasons


def test_acceptance_report_write_and_value_free_verify(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = _ready_config(tmp_path / "dataset")
    config_path.write_text(config.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(acceptance, "verify_lerobot_training_dataset_config", lambda _: config)
    monkeypatch.setattr(acceptance.importlib.util, "find_spec", lambda _: None)
    report = acceptance.run_lerobot_acceptance(config_path)
    report_path = tmp_path / "acceptance.json"

    acceptance.write_lerobot_acceptance_report(report_path, report)
    verification = acceptance.verify_lerobot_acceptance_report(report_path)

    assert verification.status == "VERIFIED"
    assert verification.acceptance_status == "ENVIRONMENT_UNAVAILABLE"
    assert verification.check_count == 5
    assert verification.config_sha256 == report.config_sha256


def test_fk_semantic_recheck_runs_both_exported_streams(tmp_path: Path, monkeypatch) -> None:
    trajectory_path, profile_path, _recipe_path, _solve_path, _grippers_path = _write_inputs(
        tmp_path
    )
    profile = acceptance.RobotProfile.model_validate_json(
        profile_path.read_text(encoding="utf-8")
    )
    canonical = CanonicalTrajectory.model_validate_json(
        trajectory_path.read_text(encoding="utf-8")
    )
    layout = build_target_vector_layout(profile)
    export_profile = build_export_profile(profile)
    export_profile_hash = sha256_bytes(canonical_json_bytes(export_profile))
    backend = PinocchioBackend(profile)
    frame = TargetReplayFrame(timestamp_s=0.0, joint_positions=(0.0, 0.0))
    state = TargetReplayTrajectory(
        stream_name="observation.state",
        replay_id="fixture-replay",
        robot_id=profile.robot_id,
        replay_manifest_path=str(tmp_path / "manifest.json"),
        replay_manifest_sha256="a" * 64,
        export_profile_path=str(tmp_path / "export-profile.json"),
        export_profile_sha256=export_profile_hash,
        layout=layout,
        frame_count=1,
        frames=[frame],
    )
    action = state.model_copy(update={"stream_name": "action"})
    context = acceptance._FKEpisodeContext(
        canonical=canonical,
        profile=profile,
        layout=layout,
        state=state,
        action=action,
        backend=backend,
        position_tolerance_m=0.01,
        orientation_tolerance_rad=0.1,
    )

    class _Dataset:
        def __len__(self) -> int:
            return 1

        def __getitem__(self, index: int) -> dict[str, object]:
            assert index == 0
            return {
                "episode_index": 0,
                "frame_index": 0,
                "timestamp": 0.0,
                "observation.state": np.asarray([0.0, 0.0]),
                "action": np.asarray([0.0, 0.0]),
            }

    config = _ready_config(tmp_path / "dataset")
    config = config.model_copy(update={"episodes": (0,)})
    monkeypatch.setattr(acceptance, "_load_fk_contexts", lambda _: {0: context})

    detail = acceptance._fk_semantic_recheck(_Dataset(), config)

    assert "observation.state and action" in detail
    assert "max_position_error_m=0" in detail


def test_acceptance_keeps_missing_fk_binding_blocked_after_runtime_checks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = _ready_config(tmp_path / "dataset").model_copy(update={"episodes": (0,)})
    config_path.write_text(config.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(acceptance, "verify_lerobot_training_dataset_config", lambda _: config)
    monkeypatch.setattr(acceptance.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setattr(acceptance, "_load_dataset", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(acceptance, "_episode_allowlist_check", lambda *_args: "allowlist")
    monkeypatch.setattr(acceptance, "_time_window_check", lambda *_args: "time window")
    monkeypatch.setattr(acceptance, "_normalization_batch_check", lambda *_args: "normalization")

    report = acceptance.run_lerobot_acceptance(config_path)

    assert report.status == "BLOCKED"
    assert report.checks[-1].status == "BLOCKED"
    assert report.blocking_reasons == (
        "acceptance_check_blocked:fk_semantic_recheck",
    )
