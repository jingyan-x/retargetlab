"""Run and archive the optional loader-backed LeRobot acceptance checks."""

from __future__ import annotations

import importlib.util
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np

from retargetlab.contracts import (
    CanonicalTrajectory,
    ExportProfile,
    LeRobotAcceptanceCheck,
    LeRobotAcceptanceReport,
    LeRobotAcceptanceReportVerification,
    LeRobotTargetTableBindingManifest,
    LeRobotTrainingDatasetConfig,
    RobotProfile,
    TargetReplayBundle,
    TargetReplayManifest,
    TargetReplayTrajectory,
    TargetVectorLayout,
)
from retargetlab.kinematics.transforms import quaternion_geodesic_angle_rad
from retargetlab.robot.assets import sha256_file
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes
from retargetlab.run.lerobot_export import (
    verify_lerobot_target_table_binding_manifest,
    verify_lerobot_training_dataset_config,
)
from retargetlab.run.replay import (
    verify_target_replay_bundle,
    verify_target_replay_manifest,
    verify_target_replay_trajectory,
)

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
_SUPPORTED_TARGET_POSE_MAPPING = "identity_dataset_native_hypothesis"


class _AcceptanceSemanticBlocked(ValueError):
    """An acceptance prerequisite is not available for this dataset/config."""


@dataclass(frozen=True)
class _FKEpisodeContext:
    """Verified value-bearing inputs needed for one episode FK recheck."""

    canonical: CanonicalTrajectory
    profile: RobotProfile
    layout: TargetVectorLayout
    state: TargetReplayTrajectory
    action: TargetReplayTrajectory
    backend: Any
    position_tolerance_m: float
    orientation_tolerance_rad: float


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


def _array(value: Any, *, label: str) -> np.ndarray[Any, Any]:
    """Convert a loader value to a finite CPU array without changing its meaning."""

    detach = getattr(value, "detach", None)
    if callable(detach):
        value = detach()
    cpu = getattr(value, "cpu", None)
    if callable(cpu):
        value = cpu()
    to_numpy = getattr(value, "numpy", None)
    if callable(to_numpy):
        value = to_numpy()
    result = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{label} contains non-finite values")
    return result


def _full_model_q(
    backend: Any,
    profile: RobotProfile,
    layout: TargetVectorLayout,
    values: np.ndarray[Any, Any],
) -> np.ndarray[Any, Any]:
    """Expand the exported arm/driver layout into the Pinocchio model q order."""

    model = getattr(backend, "model", None)
    if model is None:
        raise RuntimeError("FK backend has no loaded Pinocchio model")
    if values.shape != (layout.dimension,):
        raise ValueError(
            f"target vector has shape {values.shape}, expected ({layout.dimension},)"
        )

    assignments = dict(zip(layout.names, values.tolist(), strict=True))
    for group in profile.groups:
        if group.gripper is None:
            continue
        driver = assignments[group.gripper.driver_joint_name]
        for mimic in group.gripper.mimic_joints:
            assignments[mimic.joint_name] = mimic.multiplier * driver + mimic.offset_m

    q = np.zeros(int(model.nq), dtype=float)
    assigned_model_joints: set[str] = set()
    for joint_name, value in assignments.items():
        joint_id = int(model.getJointId(joint_name))
        if joint_id <= 0:
            raise ValueError(
                "target layout joint is missing from the Pinocchio model: "
                f"{joint_name}"
            )
        if int(model.nqs[joint_id]) != 1:
            raise ValueError(
                f"FK semantic recheck only supports one-DoF joints: {joint_name}"
            )
        q[int(model.idx_qs[joint_id])] = float(value)
        assigned_model_joints.add(joint_name)

    unbound = [
        str(model.names[joint_id])
        for joint_id in range(1, int(model.njoints))
        if int(model.nqs[joint_id]) > 0
        and str(model.names[joint_id]) not in assigned_model_joints
    ]
    if unbound:
        raise ValueError(
            "FK semantic recheck has unbound movable model joints: "
            + ", ".join(unbound)
        )
    return q


def _threshold_limit(
    recipe: Any,
    name: str,
    unit: str,
    fallback: float,
) -> float:
    threshold = recipe.thresholds.get(name)
    value = fallback if threshold is None else threshold.fail
    if threshold is not None and threshold.unit != unit:
        raise ValueError(f"recipe threshold {name!r} must use unit {unit!r}")
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"FK semantic threshold {name!r} must be positive and finite")
    return float(value)


def _load_fk_contexts(
    config: LeRobotTrainingDatasetConfig,
) -> dict[int, _FKEpisodeContext]:
    """Resolve and verify the replay lineage needed by the FK acceptance check."""

    binding_path_raw = config.target_table_binding_manifest_path
    binding_hash = config.target_table_binding_manifest_sha256
    if binding_path_raw is None or binding_hash is None:
        raise _AcceptanceSemanticBlocked(
            "acceptance config does not bind a target-table/replay reference manifest"
        )
    binding_path = Path(binding_path_raw).resolve()
    if sha256_file(binding_path).lower() != binding_hash.lower():
        raise ValueError("acceptance target-table binding manifest hash does not match")
    verify_lerobot_target_table_binding_manifest(binding_path)
    binding_manifest = LeRobotTargetTableBindingManifest.model_validate_json(
        binding_path.read_text(encoding="utf-8")
    )
    if binding_manifest.plan_path != Path(config.plan_path).resolve().as_posix():
        raise ValueError("acceptance FK binding plan path does not match training config")
    if binding_manifest.plan_sha256 != config.plan_sha256:
        raise ValueError("acceptance FK binding plan hash does not match training config")
    selected = set(config.episodes)
    bindings = {
        binding.episode_index: binding for binding in binding_manifest.bindings
    }
    if not selected.issubset(bindings):
        missing = tuple(sorted(selected.difference(bindings)))
        raise ValueError(f"acceptance FK binding is missing selected episodes: {missing}")

    from retargetlab.contracts import Recipe
    from retargetlab.kinematics.pinocchio_backend import PinocchioBackend

    contexts: dict[int, _FKEpisodeContext] = {}
    backend_by_profile_hash: dict[str, Any] = {}
    for episode_index in sorted(selected):
        binding = bindings[episode_index]
        bundle_path = Path(binding.target_replay_bundle_path).resolve()
        bundle_verification = verify_target_replay_bundle(bundle_path)
        if bundle_verification.bundle_sha256.lower() != binding.target_replay_bundle_sha256.lower():
            raise ValueError(
                f"acceptance replay bundle hash does not match episode {episode_index}"
            )
        bundle = TargetReplayBundle.model_validate_json(
            bundle_path.read_text(encoding="utf-8")
        )
        if (
            bundle.robot_id != binding_manifest.robot_id
            or bundle.layout != binding_manifest.target_layout
            or bundle.frame_count != binding.frame_count
        ):
            raise ValueError(f"acceptance replay bundle identity mismatch: episode {episode_index}")

        state_path = Path(bundle.observation_state_path).resolve()
        action_path = Path(bundle.action_path).resolve()
        state_verification = verify_target_replay_trajectory(state_path)
        action_verification = verify_target_replay_trajectory(action_path)
        if state_verification.artifact_sha256.lower() != bundle.observation_state_sha256.lower():
            raise ValueError(f"acceptance state replay hash mismatch: episode {episode_index}")
        if action_verification.artifact_sha256.lower() != bundle.action_sha256.lower():
            raise ValueError(f"acceptance action replay hash mismatch: episode {episode_index}")
        state = TargetReplayTrajectory.model_validate_json(
            state_path.read_text(encoding="utf-8")
        )
        action = TargetReplayTrajectory.model_validate_json(
            action_path.read_text(encoding="utf-8")
        )
        if state.layout != binding_manifest.target_layout or action.layout != state.layout:
            raise ValueError(f"acceptance replay layout mismatch: episode {episode_index}")
        if state.replay_manifest_path != action.replay_manifest_path:
            raise ValueError(
                "acceptance state/action replay manifest mismatch: "
                f"episode {episode_index}"
            )
        if state.replay_manifest_sha256 != action.replay_manifest_sha256:
            raise ValueError(
                "acceptance state/action replay manifest hash mismatch: "
                f"episode {episode_index}"
            )

        replay_manifest_path = Path(state.replay_manifest_path).resolve()
        replay_verification = verify_target_replay_manifest(replay_manifest_path)
        if replay_verification.manifest_sha256.lower() != state.replay_manifest_sha256.lower():
            raise ValueError(f"acceptance replay manifest hash mismatch: episode {episode_index}")
        replay_manifest = TargetReplayManifest.model_validate_json(
            replay_manifest_path.read_text(encoding="utf-8")
        )
        artifacts = {
            artifact.role: artifact
            for artifact in replay_manifest.artifacts
            if artifact.role != "arm_solve"
        }
        profile_path = Path(artifacts["robot_profile"].path).resolve()
        trajectory_path = Path(artifacts["canonical_trajectory"].path).resolve()
        recipe_path = Path(artifacts["recipe"].path).resolve()
        profile = RobotProfile.model_validate_json(
            profile_path.read_text(encoding="utf-8")
        )
        canonical = CanonicalTrajectory.model_validate_json(
            trajectory_path.read_text(encoding="utf-8")
        )
        recipe = Recipe.model_validate_json(recipe_path.read_text(encoding="utf-8"))
        if recipe.target_pose_mapping != _SUPPORTED_TARGET_POSE_MAPPING:
            raise _AcceptanceSemanticBlocked(
                "FK semantic recheck requires the explicit supported target pose mapping: "
                f"{_SUPPORTED_TARGET_POSE_MAPPING}"
            )
        if canonical.coordinate_frame != "dataset_native":
            raise _AcceptanceSemanticBlocked(
                "FK semantic recheck currently supports canonical coordinate_frame="
                "'dataset_native' only"
            )
        if tuple(canonical.stream_names) != tuple(group.name for group in profile.groups):
            raise ValueError(
                f"canonical pose streams do not match target profile: episode {episode_index}"
            )
        if (
            canonical.frame_count != state.frame_count
            or action.frame_count != state.frame_count
        ):
            raise ValueError(
                "acceptance canonical/replay frame count mismatch: "
                f"episode {episode_index}"
            )
        if (
            profile.robot_id != binding_manifest.robot_id
            or replay_manifest.robot_id != profile.robot_id
        ):
            raise ValueError(f"acceptance robot identity mismatch: episode {episode_index}")
        if replay_manifest.target_group_names != tuple(
            group.name for group in profile.groups
        ):
            raise ValueError(
                f"acceptance replay groups do not match profile: episode {episode_index}"
            )

        export_profile_path = Path(state.export_profile_path).resolve()
        export_profile = ExportProfile.model_validate_json(
            export_profile_path.read_text(encoding="utf-8")
        )
        export_profile_hash = sha256_bytes(canonical_json_bytes(export_profile))
        if state.export_profile_sha256.lower() != export_profile_hash.lower():
            raise ValueError(f"acceptance export profile hash mismatch: episode {episode_index}")
        if (
            export_profile.robot_id != profile.robot_id
            or export_profile.target_layout != state.layout
        ):
            raise ValueError(
                f"acceptance export profile identity mismatch: episode {episode_index}"
            )
        if (
            export_profile.robot_profile_sha256.lower()
            != replay_manifest.robot_profile_sha256.lower()
        ):
            raise ValueError(f"acceptance export/profile hash mismatch: episode {episode_index}")

        profile_hash = sha256_bytes(canonical_json_bytes(profile))
        if profile_hash.lower() != replay_manifest.robot_profile_sha256.lower():
            raise ValueError(f"acceptance robot profile hash mismatch: episode {episode_index}")
        backend = backend_by_profile_hash.get(profile_hash)
        if backend is None:
            backend = PinocchioBackend(profile)
            backend_by_profile_hash[profile_hash] = backend
        position_tolerance_m = _threshold_limit(
            recipe,
            "position",
            "m",
            recipe.solve_options.position_tolerance_m,
        )
        orientation_tolerance_rad = _threshold_limit(
            recipe,
            "orientation",
            "rad",
            recipe.solve_options.orientation_tolerance_rad,
        )
        contexts[episode_index] = _FKEpisodeContext(
            canonical=canonical,
            profile=profile,
            layout=state.layout,
            state=state,
            action=action,
            backend=backend,
            position_tolerance_m=position_tolerance_m,
            orientation_tolerance_rad=orientation_tolerance_rad,
        )
    return contexts


def _fk_semantic_recheck(
    dataset: Any,
    config: LeRobotTrainingDatasetConfig,
) -> str:
    """FK-check both exported streams against their bound canonical EEF poses."""

    contexts = _load_fk_contexts(config)
    row_count = len(dataset)
    if row_count < 1:
        raise ValueError("loader returned no rows for FK semantic recheck")
    seen_episodes: set[int] = set()
    max_position_error = 0.0
    max_orientation_error = 0.0
    checked_rows = 0
    for row_index in range(row_count):
        sample = dataset[row_index]
        episode_index = _as_int(sample["episode_index"])
        frame_index = _as_int(sample["frame_index"])
        context = contexts.get(episode_index)
        if context is None:
            raise ValueError(f"FK semantic recheck saw an unbound episode: {episode_index}")
        if not 0 <= frame_index < context.canonical.frame_count:
            raise ValueError(
                f"FK semantic recheck frame index is outside its source trajectory: "
                f"episode={episode_index}, frame={frame_index}"
            )
        observed_timestamp = _as_float(sample["timestamp"])
        expected_timestamp = context.state.frames[frame_index].timestamp_s
        if not math.isclose(observed_timestamp, expected_timestamp, abs_tol=1e-6):
            raise ValueError(
                "FK semantic recheck timestamp does not match replay binding: "
                f"episode={episode_index}, frame={frame_index}"
            )
        seen_episodes.add(episode_index)
        canonical_frame = context.canonical.frames[frame_index]
        for stream_name, replay in (
            ("observation.state", context.state),
            ("action", context.action),
        ):
            observed = _array(sample[stream_name], label=f"{stream_name}[{row_index}]")
            expected_vector = np.asarray(
                replay.frames[frame_index].joint_positions,
                dtype=float,
            )
            if not np.array_equal(observed.shape, expected_vector.shape):
                raise ValueError(
                    f"{stream_name} loader shape does not match replay binding: "
                    f"episode={episode_index}, frame={frame_index}, "
                    f"observed={observed.shape}, expected={expected_vector.shape}"
                )
            if not np.allclose(observed, expected_vector, rtol=0.0, atol=1e-6):
                raise ValueError(
                    f"{stream_name} loader values do not match replay binding: "
                    f"episode={episode_index}, frame={frame_index}"
                )
            q = _full_model_q(context.backend, context.profile, context.layout, observed)
            for group in context.profile.groups:
                source_pose = canonical_frame.poses[group.name]
                position, quaternion = context.backend.fk(group.name, q)
                position_error = float(
                    np.linalg.norm(
                        np.asarray(position, dtype=float)
                        - np.asarray(source_pose.position_m)
                    )
                )
                orientation_error = quaternion_geodesic_angle_rad(
                    quaternion,
                    source_pose.quaternion_wxyz,
                )
                if position_error > context.position_tolerance_m:
                    raise ValueError(
                        f"{stream_name} FK position error exceeds threshold: "
                        f"episode={episode_index}, frame={frame_index}, group={group.name}, "
                        f"error={position_error:g}, threshold={context.position_tolerance_m:g}"
                    )
                if orientation_error > context.orientation_tolerance_rad:
                    raise ValueError(
                        f"{stream_name} FK orientation error exceeds threshold: "
                        f"episode={episode_index}, frame={frame_index}, group={group.name}, "
                        f"error={orientation_error:g}, "
                        f"threshold={context.orientation_tolerance_rad:g}"
                    )
                max_position_error = max(max_position_error, position_error)
                max_orientation_error = max(max_orientation_error, orientation_error)
            checked_rows += 1
    if seen_episodes != set(config.episodes):
        raise ValueError(
            "FK semantic recheck did not observe every selected episode: "
            f"expected={tuple(sorted(config.episodes))}, observed={tuple(sorted(seen_episodes))}"
        )
    return (
        f"FK verified {checked_rows} rows for observation.state and action; "
        f"max_position_error_m={max_position_error:.4g}, "
        f"max_orientation_error_rad={max_orientation_error:.4g}"
    )


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
    report_status: Literal["FAILED", "BLOCKED"] = "FAILED",
    check_status: AcceptanceCheckStatus = "FAILED",
) -> LeRobotAcceptanceReport:
    def make_check(name: AcceptanceCheckName) -> LeRobotAcceptanceCheck:
        if name == "config_contract":
            return _check(name, "PASSED", "verified READY training dataset config")
        if name == check_name:
            return _check(name, check_status, f"{type(error).__name__}: {error}")
        if name in passed_details:
            return _check(name, "PASSED", passed_details[name])
        return _check(name, "SKIPPED", f"skipped after {check_name} failure")

    checks = tuple(make_check(name) for name in _CHECK_NAMES)
    return _report(
        config=config,
        config_path=config_path,
        config_sha256=config_sha256,
        status=report_status,
        checks=checks,
        blocking_reasons=(
            f"acceptance_check_{report_status.lower()}:{check_name}",
        ),
        warnings=config.warnings,
    )


def run_lerobot_acceptance(config_path: Path) -> LeRobotAcceptanceReport:
    """Run five explicit checks against a READY LeRobot dataset configuration.

    This function intentionally reports missing optional dependencies instead of importing
    them at package import time. The final FK check consumes the verified replay lineage
    bound by the training configuration and supports the explicitly recorded identity
    ``dataset_native`` pose mapping in this release.
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

    try:
        fk_detail = _fk_semantic_recheck(dataset, config)
    except _AcceptanceSemanticBlocked as exc:
        return _runtime_failure(
            config=config,
            config_path=config_path,
            config_sha256=config_sha256,
            check_name="fk_semantic_recheck",
            error=exc,
            passed_details={
                "episode_allowlist": episode_detail,
                "time_window": time_detail,
                "normalization_batch": normalization_detail,
            },
            report_status="BLOCKED",
            check_status="BLOCKED",
        )
    except Exception as exc:
        return _runtime_failure(
            config=config,
            config_path=config_path,
            config_sha256=config_sha256,
            check_name="fk_semantic_recheck",
            error=exc,
            passed_details={
                "episode_allowlist": episode_detail,
                "time_window": time_detail,
                "normalization_batch": normalization_detail,
            },
        )

    return _report(
        config=config,
        config_path=config_path,
        config_sha256=config_sha256,
        status="PASSED",
        checks=(
            _check("config_contract", "PASSED", config_detail),
            _check("episode_allowlist", "PASSED", episode_detail),
            _check("time_window", "PASSED", time_detail),
            _check("normalization_batch", "PASSED", normalization_detail),
            _check("fk_semantic_recheck", "PASSED", fk_detail),
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
    if report.status == "PASSED" and config.target_table_binding_manifest_path is None:
        raise ValueError("passed acceptance report requires FK replay binding in its config")
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
