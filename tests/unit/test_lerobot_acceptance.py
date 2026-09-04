from pathlib import Path

import retargetlab.run.lerobot_acceptance as acceptance
from retargetlab.contracts import LeRobotTrainingDatasetConfig


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
