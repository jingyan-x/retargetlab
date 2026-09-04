"""Run and archive the optional loader-backed LeRobot acceptance checks."""

from __future__ import annotations

import importlib.util
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from retargetlab.contracts import (
    LeRobotAcceptanceCheck,
    LeRobotAcceptanceReport,
    LeRobotAcceptanceReportVerification,
    LeRobotTrainingDatasetConfig,
)
from retargetlab.robot.assets import sha256_file
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes
from retargetlab.run.lerobot_export import verify_lerobot_training_dataset_config

AcceptanceCheckName = Literal[
    "config_contract",
    "episode_allowlist",
    "time_window",
    "normalization_batch",
    "fk_semantic_recheck",
]
AcceptanceCheckStatus = Literal["PASSED", "BLOCKED", "SKIPPED", "FAILED"]
AcceptanceStatus = Literal["PASSED", "BLOCKED", "ENVIRONMENT_UNAVAILABLE", "FAILED"]

_CHECK_NAMES: tuple[AcceptanceCheckName, ...] = (
    "config_contract",
    "episode_allowlist",
    "time_window",
    "normalization_batch",
    "fk_semantic_recheck",
)
_OPTIONAL_RUNTIME_MODULES = ("lerobot", "torch", "datasets", "huggingface_hub")
_NORMALIZATION_FEATURES = ("observation.state", "action")
_MAX_NORMALIZED_ABS = 10.0


def _check(
    name: AcceptanceCheckName,
    status: AcceptanceCheckStatus,
    detail: str,
) -> LeRobotAcceptanceCheck:
    return LeRobotAcceptanceCheck(name=name, status=status, detail=detail)


def _skipped_checks(start: int, detail: str) -> tuple[LeRobotAcceptanceCheck, ...]:
    return tuple(_check(name, "SKIPPED", detail) for name in _CHECK_NAMES[start:])


def _report(
    *,
    config: LeRobotTrainingDatasetConfig,
    config_path: Path,
    config_sha256: str,
    status: AcceptanceStatus,
    checks: tuple[LeRobotAcceptanceCheck, ...],
    blocking_reasons: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
) -> LeRobotAcceptanceReport:
    return LeRobotAcceptanceReport(
        status=status,
        dataset_alias=config.dataset_alias,
        repo_id=config.repo_id,
        root=config.root,
        episodes=config.episodes,
        config_path=config_path.as_posix(),
        config_sha256=config_sha256,
        checks=checks,
        blocking_reasons=blocking_reasons,
        warnings=warnings,
    )


def _load_config(path: Path) -> tuple[LeRobotTrainingDatasetConfig, str]:
    path = path.resolve()
    config = LeRobotTrainingDatasetConfig.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    return config, sha256_file(path)


def _missing_runtime_modules() -> tuple[str, ...]:
    missing: list[str] = []
    for module_name in _OPTIONAL_RUNTIME_MODULES:
        try:
            available = importlib.util.find_spec(module_name) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            available = False
        if not available:
            missing.append(module_name)
    return tuple(missing)


def _load_runtime() -> tuple[Any, Any]:
    """Import optional runtime dependencies only after the environment check."""

    import torch  # type: ignore[import-not-found]
    from torch.utils.data import DataLoader  # type: ignore[import-not-found]

    return torch, DataLoader


def _load_dataset(config: LeRobotTrainingDatasetConfig, **kwargs: Any) -> Any:
    """Construct the pinned loader without making the optional dependency required."""

    from lerobot.datasets.lerobot_dataset import (  # type: ignore[import-not-found]
        LeRobotDataset,
    )

    options: dict[str, Any] = {
        "repo_id": config.repo_id,
        "root": config.root,
        "episodes": list(config.episodes),
        "download_videos": False,
    }
    options.update(kwargs)
    return LeRobotDataset(**options)


def _scalar(value: Any) -> Any:
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except (TypeError, ValueError, RuntimeError):
            pass
    return value


def _as_int(value: Any) -> int:
    return int(_scalar(value))


def _as_float(value: Any) -> float:
    return float(_scalar(value))


def _shape(value: Any) -> tuple[int, ...]:
    shape = getattr(value, "shape", None)
    if shape is None:
        return ()
    return tuple(int(dimension) for dimension in shape)


def _episode_allowlist_check(
    dataset: Any,
    config: LeRobotTrainingDatasetConfig,
) -> str:
    requested = set(config.episodes)
    observed: set[int] = set()
    unexpected: set[int] = set()
    invalid_rows = 0
    row_count = len(dataset)
    for row_index in range(row_count):
        sample = dataset[row_index]
        episode_index = _as_int(sample["episode_index"])
        observed.add(episode_index)
        if episode_index not in requested:
            unexpected.add(episode_index)
        if not bool(_scalar(sample["valid.retarget"])):
            invalid_rows += 1
    if observed != requested:
        raise ValueError(
            "loader episode set mismatch: "
            f"requested={tuple(sorted(requested))}, observed={tuple(sorted(observed))}"
        )
    if unexpected:
        raise ValueError(f"loader returned unexpected episodes: {tuple(sorted(unexpected))}")
    if invalid_rows:
        raise ValueError(f"loader returned {invalid_rows} rows with valid.retarget=false")
    return (
        f"loader returned {row_count} rows from episodes {tuple(sorted(observed))}; "
        "all rows carry valid.retarget=true"
    )


def _time_window_check(dataset: Any, config: LeRobotTrainingDatasetConfig) -> str:
    fps = _as_float(dataset.meta.fps)
    if not math.isfinite(fps) or fps <= 0.0:
        raise ValueError(f"loader metadata fps is not a positive finite value: {fps}")
    step = 1.0 / fps
    window_dataset = _load_dataset(
        config,
        delta_timestamps={
            "timestamp": [-step, 0.0],
            "observation.state": [-step, 0.0],
            "action": [-step, 0.0],
        },
    )
    if len(window_dataset) < 2:
        raise ValueError("loader has fewer than two rows for a temporal-window check")
    sample = window_dataset[min(1, len(window_dataset) - 1)]
    for key in ("timestamp", *_NORMALIZATION_FEATURES):
        if _shape(sample[key])[:1] != (2,):
            raise ValueError(
                f"temporal-window feature {key!r} does not expose exactly two timestamps: "
                f"shape={_shape(sample[key])}"
            )
    timestamps = sample["timestamp"]
    observed_step = _as_float(timestamps[1]) - _as_float(timestamps[0])
    if not math.isclose(observed_step, step, rel_tol=1e-4, abs_tol=1e-6):
        raise ValueError(
            f"temporal-window timestamp step mismatch: expected={step}, "
            f"observed={observed_step}"
        )
    return f"timestamp/state/action expose a two-frame window at fps={fps:g}"


def _normalization_batch_check(dataset: Any, config: LeRobotTrainingDatasetConfig) -> str:
    stats_path = Path(config.root) / "meta" / "stats.json"
    stats_payload = json.loads(stats_path.read_text(encoding="utf-8"))
    if not isinstance(stats_payload, Mapping):
        raise ValueError("stats.json must contain an object")
    if "valid.retarget" in stats_payload:
        raise ValueError("valid.retarget must remain excluded from normalization statistics")

    torch, data_loader = _load_runtime()
    batch_size = min(2, len(dataset))
    if batch_size < 1:
        raise ValueError("loader returned no rows for normalization")
    batch = next(iter(data_loader(dataset, batch_size=batch_size, shuffle=False)))
    maxima: list[str] = []
    for key in _NORMALIZATION_FEATURES:
        feature_stats = stats_payload.get(key)
        if not isinstance(feature_stats, Mapping):
            raise ValueError(f"stats.json is missing feature statistics: {key}")
        mean = torch.as_tensor(feature_stats["mean"], dtype=torch.float64)
        std = torch.as_tensor(feature_stats["std"], dtype=torch.float64)
        if not bool(torch.isfinite(mean).all().item()) or not bool(
            torch.isfinite(std).all().item()
        ):
            raise ValueError(f"stats.json has non-finite mean/std for {key}")
        if bool((std < 0).any().item()):
            raise ValueError(f"stats.json has a negative standard deviation for {key}")
        values = batch[key].to(dtype=torch.float64)
        if values.ndim == 1:
            values = values.unsqueeze(0)
        if tuple(values.shape[1:]) != tuple(mean.shape):
            raise ValueError(
                f"normalization shape mismatch for {key}: "
                f"batch={tuple(values.shape)}, stats={tuple(mean.shape)}"
            )
        safe_std = torch.where(std == 0, torch.ones_like(std), std)
        normalized = (values - mean) / safe_std
        if not bool(torch.isfinite(normalized).all().item()):
            raise ValueError(f"normalized batch contains non-finite values for {key}")
        maximum = float(torch.max(torch.abs(normalized)).item())
        if maximum > _MAX_NORMALIZED_ABS:
            raise ValueError(
                f"normalized batch exceeds {_MAX_NORMALIZED_ABS:g} for {key}: {maximum:g}"
            )
        maxima.append(f"{key} max_abs={maximum:.4g}")
    return "finite normalized batch; " + ", ".join(maxima)


def _runtime_failure(
    *,
    config: LeRobotTrainingDatasetConfig,
    config_path: Path,
    config_sha256: str,
    check_name: AcceptanceCheckName,
    error: Exception,
    passed_details: Mapping[str, str] = {},
) -> LeRobotAcceptanceReport:
    def make_check(name: AcceptanceCheckName) -> LeRobotAcceptanceCheck:
        if name == "config_contract":
            return _check(name, "PASSED", "verified READY training dataset config")
        if name == check_name:
            return _check(name, "FAILED", f"{type(error).__name__}: {error}")
        if name in passed_details:
            return _check(name, "PASSED", passed_details[name])
        return _check(name, "SKIPPED", f"skipped after {check_name} failure")

    checks = tuple(make_check(name) for name in _CHECK_NAMES)
    return _report(
        config=config,
        config_path=config_path,
        config_sha256=config_sha256,
        status="FAILED",
        checks=checks,
        blocking_reasons=(f"acceptance_check_failed:{check_name}",),
        warnings=config.warnings,
    )


def run_lerobot_acceptance(config_path: Path) -> LeRobotAcceptanceReport:
    """Run five explicit checks against a READY LeRobot dataset configuration.

    This function intentionally reports missing optional dependencies instead of importing
    them at package import time. The final FK check remains blocked until the training
    configuration binds a RobotProfile and source EEF reference artifact.
    """

    config_path = config_path.resolve()
    config, config_sha256 = _load_config(config_path)
    try:
        verified_config = verify_lerobot_training_dataset_config(config_path)
    except Exception as exc:
        return _report(
            config=config,
            config_path=config_path,
            config_sha256=config_sha256,
            status="BLOCKED",
            checks=(
                _check("config_contract", "BLOCKED", f"{type(exc).__name__}: {exc}"),
                *_skipped_checks(1, "skipped after config contract failure"),
            ),
            blocking_reasons=("config_contract_invalid",),
            warnings=config.warnings,
        )
    config = verified_config
    config_detail = (
        f"verified READY config for repo_id={config.repo_id!r}; "
        f"episodes={config.episodes}"
    )
    if config.status != "READY":
        return _report(
            config=config,
            config_path=config_path,
            config_sha256=config_sha256,
            status="BLOCKED",
            checks=(
                _check("config_contract", "BLOCKED", config_detail),
                *_skipped_checks(1, "skipped because training config is BLOCKED"),
            ),
            blocking_reasons=config.blocking_reasons,
            warnings=config.warnings,
        )

    missing = _missing_runtime_modules()
    if missing:
        reason_values = tuple(f"optional_runtime_missing:{name}" for name in missing)
        return _report(
            config=config,
            config_path=config_path,
            config_sha256=config_sha256,
            status="ENVIRONMENT_UNAVAILABLE",
            checks=(
                _check("config_contract", "PASSED", config_detail),
                *_skipped_checks(
                    1,
                    "skipped because optional LeRobot runtime is unavailable",
                ),
            ),
            blocking_reasons=reason_values,
            warnings=config.warnings,
        )

    try:
        dataset = _load_dataset(config)
        episode_detail = _episode_allowlist_check(dataset, config)
    except Exception as exc:
        return _runtime_failure(
            config=config,
            config_path=config_path,
            config_sha256=config_sha256,
            check_name="episode_allowlist",
            error=exc,
        )

    try:
        time_detail = _time_window_check(dataset, config)
    except Exception as exc:
        return _runtime_failure(
            config=config,
            config_path=config_path,
            config_sha256=config_sha256,
            check_name="time_window",
            error=exc,
            passed_details={"episode_allowlist": episode_detail},
        )

    try:
        normalization_detail = _normalization_batch_check(dataset, config)
    except Exception as exc:
        return _runtime_failure(
            config=config,
            config_path=config_path,
            config_sha256=config_sha256,
            check_name="normalization_batch",
            error=exc,
            passed_details={
                "episode_allowlist": episode_detail,
                "time_window": time_detail,
            },
        )

    return _report(
        config=config,
        config_path=config_path,
        config_sha256=config_sha256,
        status="BLOCKED",
        checks=(
            _check("config_contract", "PASSED", config_detail),
            _check("episode_allowlist", "PASSED", episode_detail),
            _check("time_window", "PASSED", time_detail),
            _check("normalization_batch", "PASSED", normalization_detail),
            _check(
                "fk_semantic_recheck",
                "BLOCKED",
                "acceptance config does not bind RobotProfile and source EEF references",
            ),
        ),
        blocking_reasons=(
            "fk_semantic_recheck_requires_robot_profile_and_source_eef_binding",
        ),
        warnings=config.warnings,
    )


def _assert_external_artifact_path(path: Path, dataset_root: str) -> None:
    try:
        path.resolve().relative_to(Path(dataset_root).resolve())
    except ValueError:
        return
    raise ValueError("LeRobot acceptance report must be outside the dataset output root")


def write_lerobot_acceptance_report(
    path: Path,
    report: LeRobotAcceptanceReport,
) -> LeRobotAcceptanceReport:
    """Persist one exclusive acceptance report outside the dataset root."""

    path = path.resolve()
    _assert_external_artifact_path(path, report.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(report.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return report


def verify_lerobot_acceptance_report(
    path: Path,
) -> LeRobotAcceptanceReportVerification:
    """Verify report structure and current configuration binding without rerunning the loader."""

    path = path.resolve()
    report = LeRobotAcceptanceReport.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    config_path = Path(report.config_path).resolve()
    if sha256_file(config_path) != report.config_sha256:
        raise ValueError("acceptance report config hash does not match config file")
    config = verify_lerobot_training_dataset_config(config_path)
    if (
        report.dataset_alias != config.dataset_alias
        or report.repo_id != config.repo_id
        or report.root != config.root
        or report.episodes != config.episodes
    ):
        raise ValueError("acceptance report identity does not match its training config")
    if report.status == "PASSED":
        raise ValueError("acceptance report cannot claim PASSED before FK semantic binding")
    if config.status == "READY" and report.checks[0].status not in {"PASSED", "BLOCKED"}:
        raise ValueError("READY training config must not have a skipped config check")
    if config.status == "BLOCKED" and report.checks[0].status != "BLOCKED":
        raise ValueError("BLOCKED training config must have a BLOCKED config check")
    return LeRobotAcceptanceReportVerification(
        dataset_alias=report.dataset_alias,
        config_path=config_path.as_posix(),
        config_sha256=report.config_sha256,
        report_sha256=sha256_bytes(canonical_json_bytes(report)),
        acceptance_status=report.status,
        check_count=len(report.checks),
    )
