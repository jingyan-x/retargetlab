"""Build, persist, and verify metadata-only LeRobot v3 export artifacts."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from retargetlab.contracts import (
    ExportInputGate,
    ExportProfile,
    FeatureDeclaration,
    LeRobotEpisodeMetadata,
    LeRobotEpisodeReplayBinding,
    LeRobotEpisodeRetargetMask,
    LeRobotEpisodeTargetTableBinding,
    LeRobotLoaderPreflight,
    LeRobotMetadataPlan,
    LeRobotMetadataPlanVerification,
    LeRobotMetadataSkeletonVerification,
    LeRobotMetadataSkeletonWrite,
    LeRobotMultiEpisodeDatasetVerification,
    LeRobotMultiEpisodeDatasetWrite,
    LeRobotPartialDatasetVerification,
    LeRobotPartialDatasetWrite,
    LeRobotReplayBindingManifest,
    LeRobotReplayBindingVerification,
    LeRobotRetargetMask,
    LeRobotRetargetMaskVerification,
    LeRobotStatisticsVerification,
    LeRobotStatisticsWrite,
    LeRobotTargetTableBindingManifest,
    LeRobotTargetTableBindingVerification,
    LeRobotTaskMetadata,
    LeRobotTrainingDatasetConfig,
    SyntheticTableWriteReport,
    TargetReplayBundle,
)
from retargetlab.robot.assets import sha256_file
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes

_SKELETON_OMISSIONS = ("data_shards", "video_shards", "meta/stats.json")
_PARTIAL_DATASET_OMISSIONS = ("video_shards", "meta/stats.json")
_STATS_DATASET_OMISSIONS = ("video_shards",)
_DEFAULT_CHUNKS_SIZE = 1000
_MASK_POLICY = "carry_forward_previous_valid_then_first_valid"
_ALL_INVALID_POLICY = "retain_candidate_values_and_mark_fail"
_DEFAULT_NORMALIZATION_EXCLUDE = ("valid.retarget",)
_NUMERIC_STATISTICS_DTYPES = {
    "float",
    "float32",
    "float64",
    "double",
    "int",
    "int32",
    "int64",
    "uint8",
    "uint64",
}


def build_lerobot_metadata_plan(
    *,
    export_input_gate_path: Path,
    export_profile_path: Path,
    fps: float,
    features: Mapping[str, FeatureDeclaration],
    tasks: Sequence[LeRobotTaskMetadata],
    episodes: Sequence[LeRobotEpisodeMetadata],
    stats_features: Sequence[str] = ("observation.state", "action"),
    video_keys: Sequence[str] = (),
    video_path_templates: Mapping[str, str] | None = None,
) -> LeRobotMetadataPlan:
    """Build a value-free v3 metadata plan without opening dataset rows/videos."""

    gate = ExportInputGate.model_validate_json(
        export_input_gate_path.read_text(encoding="utf-8")
    )
    export_profile = ExportProfile.model_validate_json(
        export_profile_path.read_text(encoding="utf-8")
    )
    export_profile_sha256 = sha256_bytes(canonical_json_bytes(export_profile))
    if gate.export_profile_sha256 != export_profile_sha256:
        raise ValueError("export input gate profile hash does not match export profile")
    if gate.robot_id != export_profile.robot_id:
        raise ValueError("export input gate robot id does not match export profile")

    task_values = tuple(tasks)
    episode_values = tuple(episodes)
    if sum(episode.length for episode in episode_values) != gate.target_replay_frame_count:
        raise ValueError("metadata episode lengths do not match target replay frame count")
    if tuple(episode.episode_index for episode in episode_values) != (
        tuple(gate.training_episode_allowlist)
    ):
        raise ValueError("metadata episodes must match the export gate episode allowlist")

    return LeRobotMetadataPlan(
        dataset_alias=gate.dataset_alias,
        source_revision=gate.source_revision,
        export_input_gate_path=str(export_input_gate_path),
        export_input_gate_sha256=sha256_file(export_input_gate_path),
        export_profile_path=str(export_profile_path),
        export_profile_sha256=export_profile_sha256,
        robot_id=export_profile.robot_id,
        target_layout=export_profile.target_layout,
        fps=fps,
        total_episodes=len(episode_values),
        total_frames=sum(episode.length for episode in episode_values),
        total_tasks=len(task_values),
        features=dict(features),
        tasks=task_values,
        episodes=episode_values,
        training_episode_allowlist=tuple(gate.training_episode_allowlist),
        stats_features=tuple(stats_features),
        video_keys=tuple(video_keys),
        video_path_templates=dict(video_path_templates or {}),
    )


def write_lerobot_metadata_plan(
    path: Path,
    plan: LeRobotMetadataPlan,
) -> LeRobotMetadataPlan:
    """Write one exclusive metadata-only LeRobot plan."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(plan.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return plan


def verify_lerobot_metadata_plan(path: Path) -> LeRobotMetadataPlanVerification:
    """Rebuild a metadata plan from its gate, profile, and embedded declarations."""

    plan = LeRobotMetadataPlan.model_validate_json(path.read_text(encoding="utf-8"))
    expected = build_lerobot_metadata_plan(
        export_input_gate_path=Path(plan.export_input_gate_path),
        export_profile_path=Path(plan.export_profile_path),
        fps=plan.fps,
        features=plan.features,
        tasks=plan.tasks,
        episodes=plan.episodes,
        stats_features=plan.stats_features,
        video_keys=plan.video_keys,
        video_path_templates=plan.video_path_templates,
    )
    if expected != plan:
        raise ValueError("LeRobot metadata plan does not match its bound inputs")
    return LeRobotMetadataPlanVerification(
        dataset_alias=plan.dataset_alias,
        source_revision=plan.source_revision,
        robot_id=plan.robot_id,
        plan_sha256=sha256_bytes(canonical_json_bytes(plan)),
        export_input_gate_sha256=plan.export_input_gate_sha256,
        export_profile_sha256=plan.export_profile_sha256,
        total_episodes=plan.total_episodes,
        total_frames=plan.total_frames,
        total_tasks=plan.total_tasks,
    )


def _load_verified_plan(path: Path) -> tuple[LeRobotMetadataPlan, LeRobotMetadataPlanVerification]:
    """Verify the plan and then load the same immutable payload for execution."""

    path = path.resolve()
    verification = verify_lerobot_metadata_plan(path)
    plan = LeRobotMetadataPlan.model_validate_json(path.read_text(encoding="utf-8"))
    if verification.plan_sha256 != sha256_bytes(canonical_json_bytes(plan)):
        raise ValueError("LeRobot metadata plan hash changed during verification")
    return plan, verification


def build_lerobot_retarget_mask(
    *,
    plan_path: Path,
    valid_frames_by_episode: Mapping[int, Sequence[bool]],
) -> LeRobotRetargetMask:
    """Build a deterministic row-preserving mask without opening target rows."""

    plan_path = plan_path.resolve()
    plan, plan_verification = _load_verified_plan(plan_path)
    expected_episode_indices = {episode.episode_index for episode in plan.episodes}
    if set(valid_frames_by_episode) != expected_episode_indices:
        raise ValueError("retarget mask episodes must match the metadata plan")

    episode_masks: list[LeRobotEpisodeRetargetMask] = []
    for episode in plan.episodes:
        raw_values = tuple(valid_frames_by_episode[episode.episode_index])
        if len(raw_values) != episode.length:
            raise ValueError(
                "retarget mask frame count does not match episode "
                f"{episode.episode_index}"
            )
        if any(not isinstance(value, bool) for value in raw_values):
            raise ValueError("retarget mask values must be booleans")
        valid_indices = [index for index, value in enumerate(raw_values) if value]
        episode_masks.append(
            LeRobotEpisodeRetargetMask(
                episode_index=episode.episode_index,
                frame_count=episode.length,
                valid_frames=raw_values,
                retarget_status=(
                    "FAIL"
                    if not valid_indices
                    else "PASS"
                    if len(valid_indices) == episode.length
                    else "WARN"
                ),
                valid_frame_count=len(valid_indices),
                first_valid_frame_index=valid_indices[0] if valid_indices else None,
            )
        )
    pass_indices = {
        episode.episode_index
        for episode in episode_masks
        if episode.retarget_status == "PASS"
    }
    training_allowlist = tuple(
        episode_index
        for episode_index in plan.training_episode_allowlist
        if episode_index in pass_indices
    )
    return LeRobotRetargetMask(
        dataset_alias=plan.dataset_alias,
        source_revision=plan.source_revision,
        robot_id=plan.robot_id,
        plan_path=plan_path.as_posix(),
        plan_sha256=plan_verification.plan_sha256,
        episodes=tuple(episode_masks),
        training_episode_allowlist=training_allowlist,
        normalization_exclude=_DEFAULT_NORMALIZATION_EXCLUDE,
        total_episodes=plan.total_episodes,
        total_frames=plan.total_frames,
        total_valid_frames=sum(item.valid_frame_count for item in episode_masks),
    )


def write_lerobot_retarget_mask(
    path: Path,
    mask: LeRobotRetargetMask,
) -> LeRobotRetargetMask:
    """Persist one exclusive retarget mask artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(mask.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return mask


def verify_lerobot_retarget_mask(path: Path) -> LeRobotRetargetMaskVerification:
    """Rebuild a row-validity mask from its plan and declared booleans."""

    path = path.resolve()
    mask = LeRobotRetargetMask.model_validate_json(path.read_text(encoding="utf-8"))
    expected = build_lerobot_retarget_mask(
        plan_path=Path(mask.plan_path),
        valid_frames_by_episode={
            episode.episode_index: episode.valid_frames for episode in mask.episodes
        },
    )
    if expected != mask:
        raise ValueError("retarget mask does not match its bound metadata plan")
    return LeRobotRetargetMaskVerification(
        dataset_alias=mask.dataset_alias,
        source_revision=mask.source_revision,
        robot_id=mask.robot_id,
        plan_path=mask.plan_path,
        plan_sha256=mask.plan_sha256,
        mask_sha256=sha256_bytes(canonical_json_bytes(mask)),
        total_episodes=mask.total_episodes,
        total_frames=mask.total_frames,
        total_valid_frames=mask.total_valid_frames,
        training_episode_allowlist=mask.training_episode_allowlist,
    )


def _default_lerobot_retarget_mask(
    plan: LeRobotMetadataPlan,
    *,
    plan_path: Path,
    plan_sha256: str,
) -> LeRobotRetargetMask:
    """Represent the legacy all-valid path with the same explicit semantics."""

    return LeRobotRetargetMask(
        dataset_alias=plan.dataset_alias,
        source_revision=plan.source_revision,
        robot_id=plan.robot_id,
        plan_path=plan_path.as_posix(),
        plan_sha256=plan_sha256,
        episodes=tuple(
            LeRobotEpisodeRetargetMask(
                episode_index=episode.episode_index,
                frame_count=episode.length,
                valid_frames=(True,) * episode.length,
                retarget_status="PASS",
                valid_frame_count=episode.length,
                first_valid_frame_index=0,
            )
            for episode in plan.episodes
        ),
        training_episode_allowlist=tuple(plan.training_episode_allowlist),
        normalization_exclude=_DEFAULT_NORMALIZATION_EXCLUDE,
        total_episodes=plan.total_episodes,
        total_frames=plan.total_frames,
        total_valid_frames=plan.total_frames,
    )


def _load_retarget_mask_for_plan(
    mask_path: Path | None,
    *,
    plan: LeRobotMetadataPlan,
    plan_path: Path,
    plan_sha256: str,
) -> tuple[LeRobotRetargetMask, str | None]:
    if mask_path is None:
        return (
            _default_lerobot_retarget_mask(
                plan,
                plan_path=plan_path,
                plan_sha256=plan_sha256,
            ),
            None,
        )
    mask_path = mask_path.resolve()
    if not mask_path.is_file():
        raise FileNotFoundError(f"retarget mask does not exist: {mask_path}")
    verify_lerobot_retarget_mask(mask_path)
    mask = LeRobotRetargetMask.model_validate_json(
        mask_path.read_text(encoding="utf-8")
    )
    if mask.plan_path != plan_path.as_posix() or mask.plan_sha256 != plan_sha256:
        raise ValueError("retarget mask plan binding does not match the metadata plan")
    if mask.dataset_alias != plan.dataset_alias or mask.robot_id != plan.robot_id:
        raise ValueError("retarget mask identity does not match the metadata plan")
    if tuple(item.episode_index for item in mask.episodes) != tuple(
        episode.episode_index for episode in plan.episodes
    ):
        raise ValueError("retarget mask episodes do not match the metadata plan")
    return mask, sha256_file(mask_path)


def build_lerobot_replay_binding_manifest(
    *,
    plan_path: Path,
    target_replay_bundle_paths: Mapping[int, Path],
) -> LeRobotReplayBindingManifest:
    """Bind every planned episode to one independently verified replay bundle."""

    plan_path = plan_path.resolve()
    plan, plan_verification = _load_verified_plan(plan_path)
    expected_episode_indices = set(plan.training_episode_allowlist)
    if set(target_replay_bundle_paths) != expected_episode_indices:
        raise ValueError("replay bundle paths must match the plan episode allowlist")

    from retargetlab.run.replay import verify_target_replay_bundle

    bindings: list[LeRobotEpisodeReplayBinding] = []
    for episode in plan.episodes:
        bundle_path = target_replay_bundle_paths[episode.episode_index].resolve()
        if not bundle_path.is_file():
            raise FileNotFoundError(f"target replay bundle does not exist: {bundle_path}")
        bundle_verification = verify_target_replay_bundle(bundle_path)
        bundle = TargetReplayBundle.model_validate_json(
            bundle_path.read_text(encoding="utf-8")
        )
        if bundle_verification.frame_count != episode.length:
            raise ValueError(
                f"replay bundle frame count does not match episode {episode.episode_index}"
            )
        if bundle.robot_id != plan.robot_id or bundle_verification.robot_id != plan.robot_id:
            raise ValueError(
                f"replay bundle robot does not match episode {episode.episode_index}"
            )
        if bundle.layout != plan.target_layout:
            raise ValueError(
                f"replay bundle layout does not match episode {episode.episode_index}"
            )
        if bundle.export_profile_sha256 != plan.export_profile_sha256:
            raise ValueError(
                f"replay bundle profile does not match episode {episode.episode_index}"
            )
        bindings.append(
            LeRobotEpisodeReplayBinding(
                episode_index=episode.episode_index,
                dataset_from_index=episode.dataset_from_index,
                dataset_to_index=episode.dataset_to_index,
                target_replay_bundle_path=bundle_path.as_posix(),
                target_replay_bundle_sha256=bundle_verification.bundle_sha256,
                replay_id=bundle.replay_id,
                robot_id=bundle.robot_id,
                export_profile_sha256=bundle.export_profile_sha256,
                layout=bundle.layout,
                frame_count=bundle.frame_count,
            )
        )
    return LeRobotReplayBindingManifest(
        dataset_alias=plan.dataset_alias,
        source_revision=plan.source_revision,
        robot_id=plan.robot_id,
        plan_path=plan_path.as_posix(),
        plan_sha256=plan_verification.plan_sha256,
        target_layout=plan.target_layout,
        total_frames=plan.total_frames,
        bindings=tuple(bindings),
    )


def write_lerobot_replay_binding_manifest(
    path: Path,
    manifest: LeRobotReplayBindingManifest,
) -> LeRobotReplayBindingManifest:
    """Write one exclusive value-free multi-episode replay binding manifest."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(manifest.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return manifest


def verify_lerobot_replay_binding_manifest(
    path: Path,
) -> LeRobotReplayBindingVerification:
    """Rebuild all episode bindings from the verified plan and replay bundles."""

    path = path.resolve()
    manifest = LeRobotReplayBindingManifest.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    expected = build_lerobot_replay_binding_manifest(
        plan_path=Path(manifest.plan_path),
        target_replay_bundle_paths={
            binding.episode_index: Path(binding.target_replay_bundle_path)
            for binding in manifest.bindings
        },
    )
    if expected != manifest:
        raise ValueError("replay binding manifest does not match its bound inputs")
    return LeRobotReplayBindingVerification(
        dataset_alias=manifest.dataset_alias,
        source_revision=manifest.source_revision,
        robot_id=manifest.robot_id,
        plan_path=manifest.plan_path,
        plan_sha256=manifest.plan_sha256,
        binding_manifest_sha256=sha256_bytes(canonical_json_bytes(manifest)),
        binding_count=len(manifest.bindings),
        total_frames=manifest.total_frames,
    )


def build_lerobot_target_table_binding_manifest(
    *,
    plan_path: Path,
    replay_binding_manifest_path: Path,
    target_table_report_paths: Mapping[int, Path],
) -> LeRobotTargetTableBindingManifest:
    """Bind each episode's verified target-table report to its replay binding."""

    plan_path = plan_path.resolve()
    replay_binding_manifest_path = replay_binding_manifest_path.resolve()
    plan, plan_verification = _load_verified_plan(plan_path)
    verify_lerobot_replay_binding_manifest(replay_binding_manifest_path)
    replay_manifest = LeRobotReplayBindingManifest.model_validate_json(
        replay_binding_manifest_path.read_text(encoding="utf-8")
    )
    if replay_manifest.plan_path != plan_path.as_posix():
        raise ValueError("replay binding manifest plan path does not match metadata plan")
    if replay_manifest.plan_sha256 != plan_verification.plan_sha256:
        raise ValueError("replay binding manifest plan hash does not match metadata plan")
    if replay_manifest.target_layout != plan.target_layout:
        raise ValueError("replay binding manifest layout does not match metadata plan")
    expected_episode_indices = set(plan.training_episode_allowlist)
    if set(target_table_report_paths) != expected_episode_indices:
        raise ValueError("target-table report paths must match the plan episode allowlist")

    replay_by_episode = {
        binding.episode_index: binding for binding in replay_manifest.bindings
    }
    from retargetlab.run.export_table import verify_synthetic_table_write_report

    bindings: list[LeRobotEpisodeTargetTableBinding] = []
    for episode in plan.episodes:
        replay_binding = replay_by_episode[episode.episode_index]
        report_path = target_table_report_paths[episode.episode_index].resolve()
        if not report_path.is_file():
            raise FileNotFoundError(f"target table report does not exist: {report_path}")
        report = SyntheticTableWriteReport.model_validate_json(
            report_path.read_text(encoding="utf-8")
        )
        target_verification = verify_synthetic_table_write_report(report_path)
        if report.write.target_replay_bundle_path != replay_binding.target_replay_bundle_path:
            raise ValueError(
                f"target table report bundle path does not match episode {episode.episode_index}"
            )
        if report.write.target_replay_bundle_sha256 != replay_binding.target_replay_bundle_sha256:
            raise ValueError(
                f"target table report bundle hash does not match episode {episode.episode_index}"
            )
        if report.write.replay_id != replay_binding.replay_id:
            raise ValueError(
                f"target table report replay id does not match episode {episode.episode_index}"
            )
        if report.write.robot_id != plan.robot_id or target_verification.robot_id != plan.robot_id:
            raise ValueError(
                f"target table report robot does not match episode {episode.episode_index}"
            )
        if report.write.layout != plan.target_layout:
            raise ValueError(
                f"target table report layout does not match episode {episode.episode_index}"
            )
        if report.write.frame_count != episode.length:
            raise ValueError(
                f"target table report frame count does not match episode {episode.episode_index}"
            )
        if report.write.selected_episode_indices != (episode.episode_index,):
            raise ValueError(
                f"target table report selection does not match episode {episode.episode_index}"
            )
        bindings.append(
            LeRobotEpisodeTargetTableBinding(
                episode_index=episode.episode_index,
                dataset_from_index=episode.dataset_from_index,
                dataset_to_index=episode.dataset_to_index,
                target_table_report_path=report_path.as_posix(),
                target_table_report_sha256=sha256_file(report_path),
                target_replay_bundle_path=replay_binding.target_replay_bundle_path,
                target_replay_bundle_sha256=replay_binding.target_replay_bundle_sha256,
                replay_id=replay_binding.replay_id,
                frame_count=episode.length,
            )
        )
    return LeRobotTargetTableBindingManifest(
        dataset_alias=plan.dataset_alias,
        source_revision=plan.source_revision,
        robot_id=plan.robot_id,
        plan_path=plan_path.as_posix(),
        plan_sha256=plan_verification.plan_sha256,
        replay_binding_manifest_path=replay_binding_manifest_path.as_posix(),
        replay_binding_manifest_sha256=sha256_file(replay_binding_manifest_path),
        target_layout=plan.target_layout,
        total_frames=plan.total_frames,
        bindings=tuple(bindings),
    )


def write_lerobot_target_table_binding_manifest(
    path: Path,
    manifest: LeRobotTargetTableBindingManifest,
) -> LeRobotTargetTableBindingManifest:
    """Write one exclusive value-free target-table binding manifest."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(manifest.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return manifest


def verify_lerobot_target_table_binding_manifest(
    path: Path,
) -> LeRobotTargetTableBindingVerification:
    """Rebuild target-table bindings from the plan, replay manifest, and reports."""

    path = path.resolve()
    manifest = LeRobotTargetTableBindingManifest.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    expected = build_lerobot_target_table_binding_manifest(
        plan_path=Path(manifest.plan_path),
        replay_binding_manifest_path=Path(manifest.replay_binding_manifest_path),
        target_table_report_paths={
            binding.episode_index: Path(binding.target_table_report_path)
            for binding in manifest.bindings
        },
    )
    if expected != manifest:
        raise ValueError("target-table binding manifest does not match its bound inputs")
    return LeRobotTargetTableBindingVerification(
        dataset_alias=manifest.dataset_alias,
        source_revision=manifest.source_revision,
        robot_id=manifest.robot_id,
        plan_path=manifest.plan_path,
        plan_sha256=manifest.plan_sha256,
        target_table_binding_manifest_sha256=sha256_bytes(
            canonical_json_bytes(manifest)
        ),
        binding_count=len(manifest.bindings),
        total_frames=manifest.total_frames,
    )


def _load_pyarrow() -> tuple[Any, Any]:
    try:
        import pyarrow as pa  # type: ignore[import-untyped]
        import pyarrow.parquet as parquet  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("pyarrow is required for LeRobot metadata skeleton writing") from exc
    return pa, parquet


def _safe_output_path(output_root: Path, relative_path: str, *, label: str) -> Path:
    if not relative_path.strip():
        raise ValueError(f"{label} must not be blank")
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ValueError(f"{label} must be a relative path")
    resolved = (output_root / candidate).resolve()
    try:
        resolved.relative_to(output_root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes the skeleton output root") from exc
    if resolved == output_root:
        raise ValueError(f"{label} must identify a file below the skeleton output root")
    return resolved


def _format_output_path(
    output_root: Path,
    template: str,
    *,
    chunk_index: int,
    file_index: int,
    label: str,
) -> Path:
    try:
        relative_path = template.format(
            chunk_index=chunk_index,
            file_index=file_index,
        )
    except (IndexError, KeyError, ValueError) as exc:
        raise ValueError(f"{label} template cannot be formatted") from exc
    return _safe_output_path(output_root, relative_path, label=label)


def _episode_groups(
    plan: LeRobotMetadataPlan,
) -> dict[tuple[int, int], tuple[LeRobotEpisodeMetadata, ...]]:
    grouped: defaultdict[tuple[int, int], list[LeRobotEpisodeMetadata]] = defaultdict(list)
    for episode in plan.episodes:
        grouped[(episode.data_chunk_index, episode.data_file_index)].append(episode)
    return {
        key: tuple(sorted(value, key=lambda item: item.episode_index))
        for key, value in grouped.items()
    }


def _planned_paths(
    plan: LeRobotMetadataPlan,
    output_root: Path,
) -> tuple[Path, Path, Path, dict[tuple[int, int], Path]]:
    """Resolve all metadata paths and reject collisions before writing anything."""

    info_path = _safe_output_path(output_root, plan.info_path, label="info path")
    tasks_path = _safe_output_path(output_root, plan.tasks_path, label="tasks path")
    stats_path = _safe_output_path(output_root, plan.stats_path, label="stats path")
    groups = _episode_groups(plan)
    episode_paths = {
        key: _format_output_path(
            output_root,
            plan.episodes_path_template,
            chunk_index=key[0],
            file_index=key[1],
            label="episodes path",
        )
        for key in groups
    }
    data_paths = {
        _format_output_path(
            output_root,
            plan.data_path_template,
            chunk_index=key[0],
            file_index=key[1],
            label="data path",
        )
        for key in groups
    }
    metadata_paths = {info_path, tasks_path, *episode_paths.values()}
    if len(metadata_paths) != 2 + len(episode_paths):
        raise ValueError("LeRobot metadata skeleton paths must be unique")
    if stats_path in metadata_paths or data_paths.intersection(metadata_paths):
        raise ValueError("LeRobot data/stats paths collide with metadata skeleton paths")
    return info_path, tasks_path, stats_path, episode_paths


def _feature_payload(feature: FeatureDeclaration) -> dict[str, Any]:
    payload = feature.model_dump(mode="json")
    payload.pop("storage", None)
    return payload


def _info_payload(
    plan: LeRobotMetadataPlan,
    *,
    plan_sha256: str,
    data_shards_written: bool = False,
    stats_written: bool = False,
    retarget_mask: LeRobotRetargetMask | None = None,
    retarget_mask_sha256: str | None = None,
) -> dict[str, Any]:
    if stats_written and not data_shards_written:
        raise ValueError("statistics cannot be written before data shards")
    omissions: tuple[str, ...]
    written_components: tuple[str, ...]
    if stats_written:
        omissions = _STATS_DATASET_OMISSIONS
        written_components = ("metadata", "data_shards", "stats")
    elif data_shards_written:
        omissions = _PARTIAL_DATASET_OMISSIONS
        written_components = ("metadata", "data_shards")
    else:
        omissions = _SKELETON_OMISSIONS
        written_components = ("metadata",)
    episode_statuses = {
        str(episode.episode_index): (
            retarget_mask.episodes[index].retarget_status
            if retarget_mask is not None
            else "PASS"
        )
        for index, episode in enumerate(plan.episodes)
    }
    effective_allowlist = (
        retarget_mask.training_episode_allowlist
        if retarget_mask is not None
        else plan.training_episode_allowlist
    )
    retarget_metadata: dict[str, Any] = {
        "artifact_type": "lerobot_metadata_skeleton",
        "status": "PARTIAL",
        "source_scope": plan.source_scope,
        "plan_sha256": plan_sha256,
        "episode_index_policy": plan.episode_index_policy,
        "training_episode_allowlist": list(effective_allowlist),
        "episode_statuses": episode_statuses,
        "normalization_exclude": list(
            retarget_mask.normalization_exclude
            if retarget_mask is not None
            else _DEFAULT_NORMALIZATION_EXCLUDE
        ),
        "mask_policy": (
            retarget_mask.mask_policy if retarget_mask is not None else _MASK_POLICY
        ),
        "all_invalid_policy": (
            retarget_mask.all_invalid_policy
            if retarget_mask is not None
            else _ALL_INVALID_POLICY
        ),
        "episodes_path": plan.episodes_path_template,
        "stats_features": list(plan.stats_features),
        "written_components": list(written_components),
        "omitted_components": list(omissions),
    }
    if retarget_mask_sha256 is not None:
        retarget_metadata["mask_sha256"] = retarget_mask_sha256
    return {
        "codebase_version": plan.codebase_version,
        "dataset_name": plan.dataset_alias,
        "robot_type": plan.robot_id,
        "total_episodes": plan.total_episodes,
        "total_frames": plan.total_frames,
        "total_tasks": plan.total_tasks,
        "total_videos": 0,
        "total_chunks": len({episode.data_chunk_index for episode in plan.episodes}),
        "chunks_size": _DEFAULT_CHUNKS_SIZE,
        "data_files_size_in_mb": 100,
        "video_files_size_in_mb": 200,
        "fps": plan.fps,
        "splits": {"train": f"0:{plan.total_episodes}"},
        "data_path": plan.data_path_template,
        "video_path": None,
        "features": {
            name: _feature_payload(feature) for name, feature in plan.features.items()
        },
        "retargetlab": retarget_metadata,
    }


def _tasks_table(pa: Any, plan: LeRobotMetadataPlan) -> Any:
    table = pa.table(
        {
            "task_index": pa.array(
                [task.task_index for task in plan.tasks],
                type=pa.int64(),
            ),
            "__index_level_0__": pa.array(
                [task.task for task in plan.tasks],
                type=pa.string(),
            ),
        }
    )
    pandas_metadata = {
        "index_columns": ["__index_level_0__"],
        "column_indexes": [
            {
                "name": None,
                "field_name": None,
                "pandas_type": "unicode",
                "numpy_type": "object",
                "metadata": None,
            }
        ],
        "columns": [
            {
                "name": "task_index",
                "field_name": "task_index",
                "pandas_type": "int64",
                "numpy_type": "int64",
                "metadata": None,
            },
            {
                "name": "task",
                "field_name": "__index_level_0__",
                "pandas_type": "unicode",
                "numpy_type": "object",
                "metadata": None,
            },
        ],
        "attributes": {},
    }
    return table.replace_schema_metadata(
        {b"pandas": json.dumps(pandas_metadata, separators=(",", ":")).encode("utf-8")}
    )


def _episodes_table(
    pa: Any,
    episodes: Sequence[LeRobotEpisodeMetadata],
    task_by_index: Mapping[int, str],
    retarget_statuses: Mapping[int, str] | None = None,
) -> Any:
    return pa.table(
        {
            "episode_index": pa.array(
                [episode.episode_index for episode in episodes],
                type=pa.int64(),
            ),
            "tasks": pa.array(
                [
                    [task_by_index[index] for index in episode.task_indices]
                    for episode in episodes
                ],
                type=pa.list_(pa.string()),
            ),
            "length": pa.array([episode.length for episode in episodes], type=pa.int64()),
            "dataset_from_index": pa.array(
                [episode.dataset_from_index for episode in episodes],
                type=pa.int64(),
            ),
            "dataset_to_index": pa.array(
                [episode.dataset_to_index for episode in episodes],
                type=pa.int64(),
            ),
            "data/chunk_index": pa.array(
                [episode.data_chunk_index for episode in episodes],
                type=pa.int64(),
            ),
            "data/file_index": pa.array(
                [episode.data_file_index for episode in episodes],
                type=pa.int64(),
            ),
            "retarget.status": pa.array(
                [
                    (
                        retarget_statuses[episode.episode_index]
                        if retarget_statuses is not None
                        else "PASS"
                    )
                    for episode in episodes
                ],
                type=pa.string(),
            ),
        }
    )


def _write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _write_parquet_exclusive(parquet: Any, table: Any, path: Path) -> None:
    reserved = False
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x+b") as handle:
            reserved = True
            parquet.write_table(table, handle)
    except Exception:
        if reserved:
            path.unlink(missing_ok=True)
        raise


def _replace_parquet(parquet: Any, table: Any, path: Path) -> None:
    """Replace one staged Parquet metadata file without exposing a partial write."""

    staged_path = path.with_name(f"{path.name}.next")
    if staged_path.exists():
        raise FileExistsError(f"staged parquet path already exists: {staged_path}")
    try:
        parquet.write_table(table, staged_path)
        staged_path.replace(path)
    except Exception:
        staged_path.unlink(missing_ok=True)
        raise


def _relative_files(output_root: Path, paths: Sequence[Path]) -> tuple[str, ...]:
    return tuple(
        sorted(path.relative_to(output_root).as_posix() for path in paths)
    )


def _skeleton_manifest(
    *,
    plan: LeRobotMetadataPlan,
    plan_path: Path,
    plan_sha256: str,
    output_root: Path,
    episode_paths: Mapping[tuple[int, int], Path],
    info_path: Path,
    tasks_path: Path,
) -> LeRobotMetadataSkeletonWrite:
    return LeRobotMetadataSkeletonWrite(
        dataset_alias=plan.dataset_alias,
        source_revision=plan.source_revision,
        robot_id=plan.robot_id,
        plan_path=str(plan_path),
        plan_sha256=plan_sha256,
        output_root=str(output_root),
        written_files=_relative_files(
            output_root,
            (info_path, tasks_path, *episode_paths.values()),
        ),
        omitted_components=_SKELETON_OMISSIONS,
        total_episodes=plan.total_episodes,
        total_frames=plan.total_frames,
        total_tasks=plan.total_tasks,
    )


def write_lerobot_metadata_skeleton(
    *,
    plan_path: Path,
    output_root: Path,
) -> LeRobotMetadataSkeletonWrite:
    """Write only plan-derived metadata files after re-verifying the plan.

    The result is intentionally ``PARTIAL``: data shards, video shards, and
    statistics values are not synthesized by this function.
    """

    plan_path = plan_path.resolve()
    output_root = output_root.resolve()
    plan, plan_verification = _load_verified_plan(plan_path)
    if plan.video_keys:
        raise ValueError("metadata skeleton writer currently supports video-free plans only")
    info_path, tasks_path, _stats_path, episode_paths = _planned_paths(plan, output_root)
    groups = _episode_groups(plan)
    task_by_index = {task.task_index: task.task for task in plan.tasks}
    pa, parquet = _load_pyarrow()
    info = _info_payload(plan, plan_sha256=plan_verification.plan_sha256)
    tasks = _tasks_table(pa, plan)
    episodes = {
        key: _episodes_table(pa, grouped, task_by_index)
        for key, grouped in groups.items()
    }

    if output_root.exists():
        if not output_root.is_dir():
            raise FileExistsError(f"skeleton output root is not a directory: {output_root}")
        if any(output_root.iterdir()):
            raise FileExistsError(f"skeleton output root is not empty: {output_root}")
    else:
        output_root.mkdir(parents=True)

    _write_json_exclusive(info_path, info)
    _write_parquet_exclusive(parquet, tasks, tasks_path)
    for key in sorted(episodes):
        _write_parquet_exclusive(parquet, episodes[key], episode_paths[key])
    return _skeleton_manifest(
        plan=plan,
        plan_path=plan_path,
        plan_sha256=plan_verification.plan_sha256,
        output_root=output_root,
        episode_paths=episode_paths,
        info_path=info_path,
        tasks_path=tasks_path,
    )


def write_lerobot_metadata_skeleton_report(
    path: Path,
    manifest: LeRobotMetadataSkeletonWrite,
) -> LeRobotMetadataSkeletonWrite:
    """Persist one exclusive skeleton write manifest outside the dataset root."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(manifest.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return manifest


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return raw


def _actual_files(output_root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(output_root).as_posix()
            for path in output_root.rglob("*")
            if path.is_file()
        )
    )


def _assert_table_matches(actual: Any, expected: Any, *, label: str) -> None:
    if actual.column_names != expected.column_names:
        raise ValueError(f"{label} columns do not match the metadata plan")
    if actual.schema.metadata != expected.schema.metadata:
        raise ValueError(f"{label} schema metadata does not match the metadata plan")
    for name in expected.column_names:
        if actual[name].type != expected[name].type:
            raise ValueError(f"{label} column type does not match: {name}")
        if actual[name].to_pylist() != expected[name].to_pylist():
            raise ValueError(f"{label} values do not match: {name}")


def verify_lerobot_metadata_skeleton(
    *,
    plan_path: Path,
    output_root: Path,
) -> LeRobotMetadataSkeletonVerification:
    """Verify a partial skeleton's files and reject extra materialized files."""

    plan_path = plan_path.resolve()
    output_root = output_root.resolve()
    plan, plan_verification = _load_verified_plan(plan_path)
    if plan.video_keys:
        raise ValueError("metadata skeleton verifier currently supports video-free plans only")
    if not output_root.is_dir():
        raise FileNotFoundError(f"skeleton output root does not exist: {output_root}")
    info_path, tasks_path, _stats_path, episode_paths = _planned_paths(plan, output_root)
    expected_manifest = _skeleton_manifest(
        plan=plan,
        plan_path=plan_path,
        plan_sha256=plan_verification.plan_sha256,
        output_root=output_root,
        episode_paths=episode_paths,
        info_path=info_path,
        tasks_path=tasks_path,
    )
    if _actual_files(output_root) != expected_manifest.written_files:
        raise ValueError("skeleton output contains unexpected or missing files")

    expected_info = _info_payload(plan, plan_sha256=plan_verification.plan_sha256)
    if _read_json_object(info_path, label="skeleton info") != expected_info:
        raise ValueError("skeleton info.json does not match the metadata plan")

    pa, parquet = _load_pyarrow()
    _assert_table_matches(
        parquet.read_table(tasks_path),
        _tasks_table(pa, plan),
        label="skeleton tasks",
    )
    task_by_index = {task.task_index: task.task for task in plan.tasks}
    for key, grouped in _episode_groups(plan).items():
        _assert_table_matches(
            parquet.read_table(episode_paths[key]),
            _episodes_table(pa, grouped, task_by_index),
            label=f"skeleton episodes {key}",
        )

    return LeRobotMetadataSkeletonVerification(
        dataset_alias=plan.dataset_alias,
        source_revision=plan.source_revision,
        robot_id=plan.robot_id,
        plan_path=plan_path.as_posix(),
        plan_sha256=plan_verification.plan_sha256,
        output_root=output_root.as_posix(),
        written_files=expected_manifest.written_files,
        omitted_components=expected_manifest.omitted_components,
        total_episodes=plan.total_episodes,
        total_frames=plan.total_frames,
        total_tasks=plan.total_tasks,
    )


def _arrow_type(pa: Any, feature: FeatureDeclaration) -> Any:
    dtype = feature.dtype.strip().lower()
    scalar_types = {
        "bool": pa.bool_(),
        "float": pa.float32(),
        "float32": pa.float32(),
        "double": pa.float64(),
        "float64": pa.float64(),
        "int": pa.int64(),
        "int32": pa.int32(),
        "int64": pa.int64(),
        "uint8": pa.uint8(),
        "uint64": pa.uint64(),
    }
    try:
        scalar_type = scalar_types[dtype]
    except KeyError as exc:
        raise ValueError(f"unsupported parquet feature dtype: {feature.dtype}") from exc
    if feature.shape is None:
        raise ValueError("partial dataset writer does not support external features")
    if feature.shape == ():
        return scalar_type
    if len(feature.shape) != 1 or feature.shape[0] <= 0:
        raise ValueError("partial dataset writer supports only scalar or one-dimensional features")
    return pa.list_(scalar_type, feature.shape[0])


def _normalize_declared_table(pa: Any, table: Any, plan: LeRobotMetadataPlan) -> Any:
    """Cast declared Parquet features to the physical types in the plan."""

    for name, feature in plan.features.items():
        if feature.storage != "parquet":
            raise ValueError(f"video/external feature is not supported: {name}")
        if name not in table.column_names:
            raise ValueError(f"target table is missing planned feature: {name}")
        values = table[name].to_pylist()
        if any(value is None for value in values):
            raise ValueError(f"target table contains null values in planned feature: {name}")
        try:
            column = pa.array(values, type=_arrow_type(pa, feature))
        except Exception as exc:
            raise ValueError(f"target table feature cannot match plan: {name}") from exc
        table = table.set_column(table.column_names.index(name), name, column)
    return table


def _apply_episode_retarget_mask(
    pa: Any,
    table: Any,
    mask: LeRobotEpisodeRetargetMask,
) -> Any:
    """Keep every row, carrying valid target values across failed frames."""

    if table.num_rows != mask.frame_count:
        raise ValueError("retarget mask frame count does not match target table rows")
    valid_values = list(mask.valid_frames)
    if mask.retarget_status != "FAIL":
        first_valid = mask.first_valid_frame_index
        if first_valid is None:
            raise ValueError("non-FAIL retarget mask must have a first valid frame")
        for feature_name in ("observation.state", "action"):
            values = table[feature_name].to_pylist()
            previous = values[first_valid]
            for frame_index, is_valid in enumerate(valid_values):
                if is_valid:
                    previous = values[frame_index]
                else:
                    values[frame_index] = previous
            table = table.set_column(
                table.column_names.index(feature_name),
                feature_name,
                pa.array(values, type=table[feature_name].type),
            )
    return table.set_column(
        table.column_names.index("valid.retarget"),
        "valid.retarget",
        pa.array(valid_values, type=pa.bool_()),
    )


def _validate_episode_table(table: Any, episode: LeRobotEpisodeMetadata) -> None:
    if table.num_rows != episode.length:
        raise ValueError("target table row count does not match the metadata episode")
    episode_values = [int(value) for value in table["episode_index"].to_pylist()]
    if episode_values != [episode.episode_index] * episode.length:
        raise ValueError("target table episode_index does not match the metadata episode")
    frame_values = [int(value) for value in table["frame_index"].to_pylist()]
    if frame_values != list(range(episode.length)):
        raise ValueError("target table frame_index does not match the metadata episode")
    task_values = [int(value) for value in table["task_index"].to_pylist()]
    if any(value not in episode.task_indices for value in task_values):
        raise ValueError("target table task_index does not match episode task metadata")


def _validate_single_episode_table(table: Any, plan: LeRobotMetadataPlan) -> None:
    if len(plan.episodes) != 1:
        raise ValueError(
            "partial dataset writer currently binds exactly one synthetic episode; "
            "multi-episode materialization is not implemented"
        )
    if table.num_rows != plan.total_frames:
        raise ValueError("target table row count does not match the metadata plan")
    _validate_episode_table(table, plan.episodes[0])


def _load_verified_target_table(
    *,
    plan: LeRobotMetadataPlan,
    target_table_report_path: Path,
) -> tuple[SyntheticTableWriteReport, Any, Any]:
    from retargetlab.run.export_table import verify_synthetic_table_write_report

    report = SyntheticTableWriteReport.model_validate_json(
        target_table_report_path.read_text(encoding="utf-8")
    )
    verification = verify_synthetic_table_write_report(target_table_report_path)
    if report.write.layout != plan.target_layout:
        raise ValueError("target table layout does not match the metadata plan")
    if report.write.robot_id != plan.robot_id or verification.robot_id != plan.robot_id:
        raise ValueError("target table robot does not match the metadata plan")
    if report.write.frame_count != plan.total_frames:
        raise ValueError("target table frame count does not match the metadata plan")
    if report.write.selected_episode_indices != plan.training_episode_allowlist:
        raise ValueError("target table episode selection does not match the metadata plan")
    pa, parquet = _load_pyarrow()
    table = parquet.read_table(report.write.output_table_path)
    _validate_single_episode_table(table, plan)
    normalized = _normalize_declared_table(pa, table, plan)
    return report, normalized, pa


def _load_verified_multi_target_tables(
    *,
    plan: LeRobotMetadataPlan,
    plan_path: Path,
    target_table_binding_manifest_path: Path,
    retarget_mask: LeRobotRetargetMask | None = None,
) -> tuple[dict[tuple[int, int], Any], str]:
    target_table_binding_manifest_path = target_table_binding_manifest_path.resolve()
    target_binding_verification = verify_lerobot_target_table_binding_manifest(
        target_table_binding_manifest_path
    )
    target_binding_manifest = LeRobotTargetTableBindingManifest.model_validate_json(
        target_table_binding_manifest_path.read_text(encoding="utf-8")
    )
    plan_verification = verify_lerobot_metadata_plan(plan_path)
    if target_binding_manifest.plan_path != plan_path.as_posix():
        raise ValueError("target-table binding manifest plan path does not match dataset plan")
    if target_binding_manifest.plan_sha256 != plan_verification.plan_sha256:
        raise ValueError("target-table binding manifest plan hash does not match dataset plan")
    if target_binding_manifest.target_layout != plan.target_layout:
        raise ValueError("target-table binding manifest layout does not match dataset plan")
    if target_binding_verification.total_frames != plan.total_frames:
        raise ValueError("target-table binding manifest frame count does not match dataset plan")
    binding_by_episode = {
        binding.episode_index: binding for binding in target_binding_manifest.bindings
    }
    from retargetlab.run.export_table import verify_synthetic_table_write_report

    pa, parquet = _load_pyarrow()
    grouped: defaultdict[tuple[int, int], list[Any]] = defaultdict(list)
    effective_mask = retarget_mask or _default_lerobot_retarget_mask(
        plan,
        plan_path=plan_path.resolve(),
        plan_sha256=plan_verification.plan_sha256,
    )
    mask_by_episode = {
        item.episode_index: item for item in effective_mask.episodes
    }
    for episode in plan.episodes:
        binding = binding_by_episode[episode.episode_index]
        report_path = Path(binding.target_table_report_path).resolve()
        if sha256_file(report_path) != binding.target_table_report_sha256:
            raise ValueError(
                f"target-table report hash changed for episode {episode.episode_index}"
            )
        report = SyntheticTableWriteReport.model_validate_json(
            report_path.read_text(encoding="utf-8")
        )
        report_verification = verify_synthetic_table_write_report(report_path)
        if report.write.frame_count != episode.length:
            raise ValueError(
                f"target-table report frame count does not match episode {episode.episode_index}"
            )
        if report.write.selected_episode_indices != (episode.episode_index,):
            raise ValueError(
                f"target-table report selection does not match episode {episode.episode_index}"
            )
        if report.write.target_replay_bundle_sha256 != binding.target_replay_bundle_sha256:
            raise ValueError(
                f"target-table report bundle hash does not match episode {episode.episode_index}"
            )
        if report.write.replay_id != binding.replay_id:
            raise ValueError(
                f"target-table report replay id does not match episode {episode.episode_index}"
            )
        if report.write.robot_id != plan.robot_id or report_verification.robot_id != plan.robot_id:
            raise ValueError(
                f"target-table report robot does not match episode {episode.episode_index}"
            )
        if report.write.layout != plan.target_layout:
            raise ValueError(
                f"target-table report layout does not match episode {episode.episode_index}"
            )
        table = parquet.read_table(report.write.output_table_path)
        _validate_episode_table(table, episode)
        normalized = _normalize_declared_table(pa, table, plan)
        normalized = _apply_episode_retarget_mask(
            pa,
            normalized,
            mask_by_episode[episode.episode_index],
        ).replace_schema_metadata(None)
        grouped[(episode.data_chunk_index, episode.data_file_index)].append(normalized)

    combined: dict[tuple[int, int], Any] = {}
    for key, tables in grouped.items():
        try:
            combined[key] = pa.concat_tables(tables)
        except Exception as exc:
            raise ValueError(f"target tables cannot be combined for data shard {key}") from exc
    return combined, sha256_file(target_table_binding_manifest_path)


def _data_metadata(
    table: Any,
    *,
    plan: LeRobotMetadataPlan,
    plan_sha256: str,
    target_table_report_sha256: str,
) -> Any:
    metadata = dict(table.schema.metadata or {})
    metadata.update(
        {
            b"retargetlab.artifact_type": b"lerobot_partial_data_shard",
            b"retargetlab.source_scope": b"synthetic_public_only",
            b"retargetlab.plan_sha256": plan_sha256.encode("ascii"),
            b"retargetlab.target_table_report_sha256": target_table_report_sha256.encode(
                "ascii"
            ),
            b"retargetlab.robot_id": plan.robot_id.encode("utf-8"),
        }
    )
    return table.replace_schema_metadata(metadata)


def _multi_data_metadata(
    table: Any,
    *,
    plan: LeRobotMetadataPlan,
    plan_sha256: str,
    target_table_binding_manifest_sha256: str,
) -> Any:
    metadata = dict(table.schema.metadata or {})
    metadata.update(
        {
            b"retargetlab.artifact_type": b"lerobot_multi_episode_data_shard",
            b"retargetlab.source_scope": b"synthetic_public_only",
            b"retargetlab.plan_sha256": plan_sha256.encode("ascii"),
            b"retargetlab.target_table_binding_manifest_sha256": (
                target_table_binding_manifest_sha256.encode("ascii")
            ),
            b"retargetlab.robot_id": plan.robot_id.encode("utf-8"),
        }
    )
    return table.replace_schema_metadata(metadata)


def _replace_json(path: Path, payload: Mapping[str, Any]) -> None:
    staged_path = path.with_name(f"{path.name}.next")
    if staged_path.exists():
        raise FileExistsError(f"staged metadata path already exists: {staged_path}")
    try:
        with staged_path.open("x", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        staged_path.replace(path)
    except Exception:
        staged_path.unlink(missing_ok=True)
        raise


def _partial_manifest(
    *,
    plan: LeRobotMetadataPlan,
    plan_path: Path,
    plan_sha256: str,
    output_root: Path,
    target_table_report_path: Path,
    target_table_report_sha256: str,
    info_path: Path,
    tasks_path: Path,
    episode_paths: Mapping[tuple[int, int], Path],
    data_path: Path,
) -> LeRobotPartialDatasetWrite:
    return LeRobotPartialDatasetWrite(
        dataset_alias=plan.dataset_alias,
        source_revision=plan.source_revision,
        robot_id=plan.robot_id,
        plan_path=plan_path.as_posix(),
        plan_sha256=plan_sha256,
        output_root=output_root.as_posix(),
        target_table_report_path=target_table_report_path.as_posix(),
        target_table_report_sha256=target_table_report_sha256,
        written_files=_relative_files(
            output_root,
            (info_path, tasks_path, *episode_paths.values(), data_path),
        ),
        omitted_components=_PARTIAL_DATASET_OMISSIONS,
        total_episodes=plan.total_episodes,
        total_frames=plan.total_frames,
        total_tasks=plan.total_tasks,
    )


def write_lerobot_partial_dataset(
    *,
    plan_path: Path,
    output_root: Path,
    target_table_report_path: Path,
) -> LeRobotPartialDatasetWrite:
    """Bind one verified synthetic target table to the plan's data shard path."""

    plan_path = plan_path.resolve()
    output_root = output_root.resolve()
    target_table_report_path = target_table_report_path.resolve()
    plan, plan_verification = _load_verified_plan(plan_path)
    if plan.video_keys:
        raise ValueError("partial dataset writer currently supports video-free plans only")
    if not target_table_report_path.is_file():
        raise FileNotFoundError(
            f"synthetic target table report does not exist: {target_table_report_path}"
        )
    if not output_root.is_dir():
        raise FileNotFoundError(
            f"metadata skeleton output root does not exist: {output_root}"
        )
    verify_lerobot_metadata_skeleton(plan_path=plan_path, output_root=output_root)
    info_path, tasks_path, _stats_path, episode_paths = _planned_paths(plan, output_root)
    if len(plan.episodes) != 1:
        raise ValueError(
            "partial dataset writer currently binds exactly one synthetic episode; "
            "multi-episode materialization is not implemented"
        )
    episode = plan.episodes[0]
    data_path = _format_output_path(
        output_root,
        plan.data_path_template,
        chunk_index=episode.data_chunk_index,
        file_index=episode.data_file_index,
        label="data path",
    )
    report, normalized, _pa = _load_verified_target_table(
        plan=plan,
        target_table_report_path=target_table_report_path,
    )
    target_table_report_sha256 = sha256_file(target_table_report_path)
    data_table = _data_metadata(
        normalized,
        plan=plan,
        plan_sha256=plan_verification.plan_sha256,
        target_table_report_sha256=target_table_report_sha256,
    )
    _validate_single_episode_table(data_table, plan)
    parquet = _load_pyarrow()[1]
    if Path(report.write.output_table_path).resolve() == data_path:
        raise ValueError("target table output and LeRobot data shard paths must be different")
    _write_parquet_exclusive(parquet, data_table, data_path)
    _replace_json(
        info_path,
        _info_payload(
            plan,
            plan_sha256=plan_verification.plan_sha256,
            data_shards_written=True,
        ),
    )
    return _partial_manifest(
        plan=plan,
        plan_path=plan_path,
        plan_sha256=plan_verification.plan_sha256,
        output_root=output_root,
        target_table_report_path=target_table_report_path,
        target_table_report_sha256=target_table_report_sha256,
        info_path=info_path,
        tasks_path=tasks_path,
        episode_paths=episode_paths,
        data_path=data_path,
    )


def write_lerobot_partial_dataset_report(
    path: Path,
    manifest: LeRobotPartialDatasetWrite,
) -> LeRobotPartialDatasetWrite:
    """Persist one exclusive partial dataset write manifest."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(manifest.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return manifest


def verify_lerobot_partial_dataset(
    *,
    plan_path: Path,
    output_root: Path,
    target_table_report_path: Path,
) -> LeRobotPartialDatasetVerification:
    """Verify metadata plus one synthetic data shard, still without stats/videos."""

    plan_path = plan_path.resolve()
    output_root = output_root.resolve()
    target_table_report_path = target_table_report_path.resolve()
    plan, plan_verification = _load_verified_plan(plan_path)
    if plan.video_keys:
        raise ValueError("partial dataset verifier currently supports video-free plans only")
    if not output_root.is_dir():
        raise FileNotFoundError(f"partial dataset output root does not exist: {output_root}")
    if len(plan.episodes) != 1:
        raise ValueError(
            "partial dataset verifier currently binds exactly one synthetic episode; "
            "multi-episode materialization is not implemented"
        )
    info_path, tasks_path, _stats_path, episode_paths = _planned_paths(plan, output_root)
    _report, normalized, pa = _load_verified_target_table(
        plan=plan,
        target_table_report_path=target_table_report_path,
    )
    episode = plan.episodes[0]
    data_path = _format_output_path(
        output_root,
        plan.data_path_template,
        chunk_index=episode.data_chunk_index,
        file_index=episode.data_file_index,
        label="data path",
    )
    if not data_path.is_file():
        raise FileNotFoundError(f"partial dataset data shard does not exist: {data_path}")
    expected_files = _relative_files(
        output_root,
        (info_path, tasks_path, *episode_paths.values(), data_path),
    )
    if _actual_files(output_root) != expected_files:
        raise ValueError("partial dataset output contains unexpected or missing files")
    expected_info = _info_payload(
        plan,
        plan_sha256=plan_verification.plan_sha256,
        data_shards_written=True,
    )
    if _read_json_object(info_path, label="partial dataset info") != expected_info:
        raise ValueError("partial dataset info.json does not match the plan")
    parquet = _load_pyarrow()[1]
    _assert_table_matches(
        parquet.read_table(tasks_path),
        _tasks_table(pa, plan),
        label="partial dataset tasks",
    )
    task_by_index = {task.task_index: task.task for task in plan.tasks}
    for key, grouped in _episode_groups(plan).items():
        _assert_table_matches(
            parquet.read_table(episode_paths[key]),
            _episodes_table(pa, grouped, task_by_index),
            label=f"partial dataset episodes {key}",
        )
    actual_data = parquet.read_table(data_path)
    expected_data = _data_metadata(
        normalized,
        plan=plan,
        plan_sha256=plan_verification.plan_sha256,
        target_table_report_sha256=sha256_file(target_table_report_path),
    )
    _assert_table_matches(actual_data, expected_data, label="partial dataset data")
    metadata = actual_data.schema.metadata or {}
    expected_metadata = expected_data.schema.metadata or {}
    for metadata_key in (
        b"retargetlab.artifact_type",
        b"retargetlab.source_scope",
        b"retargetlab.plan_sha256",
        b"retargetlab.target_table_report_sha256",
        b"retargetlab.robot_id",
    ):
        if metadata.get(metadata_key) != expected_metadata.get(metadata_key):
            raise ValueError(
                "partial dataset data metadata does not match: "
                f"{metadata_key.decode()}"
            )
    return LeRobotPartialDatasetVerification(
        dataset_alias=plan.dataset_alias,
        source_revision=plan.source_revision,
        robot_id=plan.robot_id,
        plan_path=plan_path.as_posix(),
        plan_sha256=plan_verification.plan_sha256,
        output_root=output_root.as_posix(),
        target_table_report_path=target_table_report_path.as_posix(),
        target_table_report_sha256=sha256_file(target_table_report_path),
        written_files=expected_files,
        omitted_components=_PARTIAL_DATASET_OMISSIONS,
        total_episodes=plan.total_episodes,
        total_frames=plan.total_frames,
        total_tasks=plan.total_tasks,
    )


def _data_shard_paths(
    plan: LeRobotMetadataPlan,
    output_root: Path,
) -> dict[tuple[int, int], Path]:
    groups = _episode_groups(plan)
    paths = {
        key: _format_output_path(
            output_root,
            plan.data_path_template,
            chunk_index=key[0],
            file_index=key[1],
            label="data path",
        )
        for key in groups
    }
    if len(set(paths.values())) != len(paths):
        raise ValueError("multi-episode data shard paths must be unique")
    return paths


def _multi_dataset_manifest(
    *,
    plan: LeRobotMetadataPlan,
    plan_path: Path,
    plan_sha256: str,
    output_root: Path,
    target_table_binding_manifest_path: Path,
    target_table_binding_manifest_sha256: str,
    retarget_mask_path: Path | None,
    retarget_mask_sha256: str | None,
    info_path: Path,
    tasks_path: Path,
    episode_paths: Mapping[tuple[int, int], Path],
    data_paths: Mapping[tuple[int, int], Path],
) -> LeRobotMultiEpisodeDatasetWrite:
    return LeRobotMultiEpisodeDatasetWrite(
        dataset_alias=plan.dataset_alias,
        source_revision=plan.source_revision,
        robot_id=plan.robot_id,
        plan_path=plan_path.as_posix(),
        plan_sha256=plan_sha256,
        output_root=output_root.as_posix(),
        target_table_binding_manifest_path=(
            target_table_binding_manifest_path.as_posix()
        ),
        target_table_binding_manifest_sha256=target_table_binding_manifest_sha256,
        retarget_mask_path=(
            retarget_mask_path.as_posix() if retarget_mask_path is not None else None
        ),
        retarget_mask_sha256=retarget_mask_sha256,
        written_files=_relative_files(
            output_root,
            (
                info_path,
                tasks_path,
                *episode_paths.values(),
                *data_paths.values(),
            ),
        ),
        omitted_components=_PARTIAL_DATASET_OMISSIONS,
        total_episodes=plan.total_episodes,
        total_frames=plan.total_frames,
        total_tasks=plan.total_tasks,
    )


def write_lerobot_multi_episode_dataset(
    *,
    plan_path: Path,
    output_root: Path,
    target_table_binding_manifest_path: Path,
    retarget_mask_path: Path | None = None,
) -> LeRobotMultiEpisodeDatasetWrite:
    """Write grouped synthetic data shards for every verified plan episode."""

    plan_path = plan_path.resolve()
    output_root = output_root.resolve()
    target_table_binding_manifest_path = target_table_binding_manifest_path.resolve()
    plan, plan_verification = _load_verified_plan(plan_path)
    if retarget_mask_path is not None:
        _assert_external_artifact_path(
            retarget_mask_path,
            output_root.as_posix(),
            label="retarget mask",
        )
    retarget_mask, retarget_mask_sha256 = _load_retarget_mask_for_plan(
        retarget_mask_path,
        plan=plan,
        plan_path=plan_path,
        plan_sha256=plan_verification.plan_sha256,
    )
    if plan.video_keys:
        raise ValueError("multi-episode dataset writer currently supports video-free plans only")
    if not output_root.is_dir():
        raise FileNotFoundError(
            f"metadata skeleton output root does not exist: {output_root}"
        )
    if not target_table_binding_manifest_path.is_file():
        raise FileNotFoundError(
            "target-table binding manifest does not exist: "
            f"{target_table_binding_manifest_path}"
        )
    verify_lerobot_metadata_skeleton(plan_path=plan_path, output_root=output_root)
    info_path, tasks_path, _stats_path, episode_paths = _planned_paths(plan, output_root)
    data_paths = _data_shard_paths(plan, output_root)
    combined, binding_sha256 = _load_verified_multi_target_tables(
        plan=plan,
        plan_path=plan_path,
        target_table_binding_manifest_path=target_table_binding_manifest_path,
        retarget_mask=retarget_mask,
    )
    pa, parquet = _load_pyarrow()
    for key in sorted(combined):
        _write_parquet_exclusive(
            parquet,
            _multi_data_metadata(
                combined[key],
                plan=plan,
                plan_sha256=plan_verification.plan_sha256,
                target_table_binding_manifest_sha256=binding_sha256,
            ),
            data_paths[key],
        )
    retarget_statuses = {
        item.episode_index: item.retarget_status for item in retarget_mask.episodes
    }
    task_by_index = {task.task_index: task.task for task in plan.tasks}
    for key, grouped in _episode_groups(plan).items():
        _replace_parquet(
            parquet,
            _episodes_table(pa, grouped, task_by_index, retarget_statuses),
            episode_paths[key],
        )
    _replace_json(
        info_path,
        _info_payload(
            plan,
            plan_sha256=plan_verification.plan_sha256,
            data_shards_written=True,
            retarget_mask=retarget_mask,
            retarget_mask_sha256=retarget_mask_sha256,
        ),
    )
    return _multi_dataset_manifest(
        plan=plan,
        plan_path=plan_path,
        plan_sha256=plan_verification.plan_sha256,
        output_root=output_root,
        target_table_binding_manifest_path=target_table_binding_manifest_path,
        target_table_binding_manifest_sha256=binding_sha256,
        retarget_mask_path=retarget_mask_path,
        retarget_mask_sha256=retarget_mask_sha256,
        info_path=info_path,
        tasks_path=tasks_path,
        episode_paths=episode_paths,
        data_paths=data_paths,
    )


def write_lerobot_multi_episode_dataset_report(
    path: Path,
    manifest: LeRobotMultiEpisodeDatasetWrite,
) -> LeRobotMultiEpisodeDatasetWrite:
    """Persist one exclusive multi-episode dataset write manifest."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(manifest.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return manifest


def _verify_lerobot_multi_episode_dataset_files(
    *,
    plan_path: Path,
    output_root: Path,
    target_table_binding_manifest_path: Path,
    stats_written: bool,
    retarget_mask_path: Path | None = None,
) -> tuple[
    LeRobotMetadataPlan,
    LeRobotMetadataPlanVerification,
    tuple[str, ...],
    dict[tuple[int, int], Any],
    str,
    Path,
    dict[tuple[int, int], Path],
    LeRobotRetargetMask,
    str | None,
]:
    """Verify shared dataset files, optionally allowing a verified stats file."""

    plan_path = plan_path.resolve()
    output_root = output_root.resolve()
    target_table_binding_manifest_path = target_table_binding_manifest_path.resolve()
    plan, plan_verification = _load_verified_plan(plan_path)
    if retarget_mask_path is not None:
        _assert_external_artifact_path(
            retarget_mask_path,
            output_root.as_posix(),
            label="retarget mask",
        )
    retarget_mask, retarget_mask_sha256 = _load_retarget_mask_for_plan(
        retarget_mask_path,
        plan=plan,
        plan_path=plan_path,
        plan_sha256=plan_verification.plan_sha256,
    )
    if plan.video_keys:
        raise ValueError("multi-episode dataset verifier currently supports video-free plans only")
    if not output_root.is_dir():
        raise FileNotFoundError(f"partial dataset output root does not exist: {output_root}")
    info_path, tasks_path, stats_path, episode_paths = _planned_paths(plan, output_root)
    data_paths = _data_shard_paths(plan, output_root)
    combined, binding_sha256 = _load_verified_multi_target_tables(
        plan=plan,
        plan_path=plan_path,
        target_table_binding_manifest_path=target_table_binding_manifest_path,
        retarget_mask=retarget_mask,
    )
    expected_paths = (info_path, tasks_path, *episode_paths.values(), *data_paths.values())
    if stats_written:
        expected_paths = (*expected_paths, stats_path)
    expected_files = _relative_files(output_root, expected_paths)
    if _actual_files(output_root) != expected_files:
        raise ValueError("multi-episode dataset output contains unexpected or missing files")
    expected_info = _info_payload(
        plan,
        plan_sha256=plan_verification.plan_sha256,
        data_shards_written=True,
        stats_written=stats_written,
        retarget_mask=retarget_mask,
        retarget_mask_sha256=retarget_mask_sha256,
    )
    if _read_json_object(info_path, label="multi-episode dataset info") != expected_info:
        raise ValueError("multi-episode dataset info.json does not match the plan")
    pa, parquet = _load_pyarrow()
    _assert_table_matches(
        parquet.read_table(tasks_path),
        _tasks_table(pa, plan),
        label="multi-episode dataset tasks",
    )
    task_by_index = {task.task_index: task.task for task in plan.tasks}
    for key, grouped in _episode_groups(plan).items():
        _assert_table_matches(
            parquet.read_table(episode_paths[key]),
            _episodes_table(
                pa,
                grouped,
                task_by_index,
                {
                    item.episode_index: item.retarget_status
                    for item in retarget_mask.episodes
                },
            ),
            label=f"multi-episode dataset episodes {key}",
        )
    expected_metadata_keys = (
        b"retargetlab.artifact_type",
        b"retargetlab.source_scope",
        b"retargetlab.plan_sha256",
        b"retargetlab.target_table_binding_manifest_sha256",
        b"retargetlab.robot_id",
    )
    actual_tables: dict[tuple[int, int], Any] = {}
    for key, expected_table in combined.items():
        expected_data = _multi_data_metadata(
            expected_table,
            plan=plan,
            plan_sha256=plan_verification.plan_sha256,
            target_table_binding_manifest_sha256=binding_sha256,
        )
        actual_data = parquet.read_table(data_paths[key])
        _assert_table_matches(actual_data, expected_data, label=f"data shard {key}")
        actual_metadata = actual_data.schema.metadata or {}
        expected_metadata = expected_data.schema.metadata or {}
        for metadata_key in expected_metadata_keys:
            if actual_metadata.get(metadata_key) != expected_metadata.get(metadata_key):
                raise ValueError(
                    "multi-episode data metadata does not match: "
                    f"{metadata_key.decode()}"
                )
        actual_tables[key] = actual_data
    return (
        plan,
        plan_verification,
        expected_files,
        actual_tables,
        binding_sha256,
        stats_path,
        data_paths,
        retarget_mask,
        retarget_mask_sha256,
    )


def verify_lerobot_multi_episode_dataset(
    *,
    plan_path: Path,
    output_root: Path,
    target_table_binding_manifest_path: Path,
    retarget_mask_path: Path | None = None,
) -> LeRobotMultiEpisodeDatasetVerification:
    """Verify grouped synthetic data shards against all bound episode reports."""

    (
        plan,
        plan_verification,
        expected_files,
        _actual_tables,
        binding_sha256,
        _stats_path,
        _data_paths,
        _retarget_mask,
        retarget_mask_sha256,
    ) = _verify_lerobot_multi_episode_dataset_files(
        plan_path=plan_path,
        output_root=output_root,
        target_table_binding_manifest_path=target_table_binding_manifest_path,
        stats_written=False,
        retarget_mask_path=retarget_mask_path,
    )
    return LeRobotMultiEpisodeDatasetVerification(
        dataset_alias=plan.dataset_alias,
        source_revision=plan.source_revision,
        robot_id=plan.robot_id,
        plan_path=plan_path.resolve().as_posix(),
        plan_sha256=plan_verification.plan_sha256,
        output_root=output_root.resolve().as_posix(),
        target_table_binding_manifest_path=target_table_binding_manifest_path.resolve().as_posix(),
        target_table_binding_manifest_sha256=binding_sha256,
        retarget_mask_path=(
            retarget_mask_path.resolve().as_posix()
            if retarget_mask_path is not None
            else None
        ),
        retarget_mask_sha256=retarget_mask_sha256,
        written_files=expected_files,
        omitted_components=_PARTIAL_DATASET_OMISSIONS,
        total_episodes=plan.total_episodes,
        total_frames=plan.total_frames,
        total_tasks=plan.total_tasks,
    )


def _statistics_matrix(table: Any, plan: LeRobotMetadataPlan, feature_name: str) -> np.ndarray:
    feature = plan.features[feature_name]
    if feature.storage != "parquet":
        raise ValueError(f"statistics feature must be stored in parquet: {feature_name}")
    if feature.dtype.strip().lower() not in _NUMERIC_STATISTICS_DTYPES:
        raise ValueError(f"statistics feature must be numeric: {feature_name}")
    if feature.shape is None or len(feature.shape) > 1:
        raise ValueError(
            "statistics currently supports scalar and one-dimensional features only: "
            f"{feature_name}"
        )
    if feature_name not in table.column_names:
        raise ValueError(f"data shard is missing statistics feature: {feature_name}")
    try:
        matrix = np.asarray(table[feature_name].to_pylist(), dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"statistics feature cannot be converted to float: {feature_name}"
        ) from exc
    if feature.shape == ():
        matrix = matrix.reshape(-1, 1)
    else:
        dimension = feature.shape[0]
        if dimension <= 0 or matrix.shape != (table.num_rows, dimension):
            raise ValueError(
                "statistics feature shape does not match its declaration: "
                f"{feature_name}"
            )
    if matrix.shape[0] == 0:
        raise ValueError(f"statistics feature has no rows: {feature_name}")
    if not np.isfinite(matrix).all():
        raise ValueError(f"statistics feature contains non-finite values: {feature_name}")
    return matrix


def _compute_numeric_statistics(
    *,
    plan: LeRobotMetadataPlan,
    data_tables: Mapping[tuple[int, int], Any],
    retarget_mask: LeRobotRetargetMask | None = None,
) -> dict[str, dict[str, list[float] | list[int]]]:
    """Compute exact stats over the effective training episode/frame view."""

    training_episode_allowlist = set(
        retarget_mask.training_episode_allowlist
        if retarget_mask is not None
        else plan.training_episode_allowlist
    )
    filtered_tables: list[tuple[Any, np.ndarray]] = []
    for _key, table in sorted(data_tables.items()):
        episode_values = table["episode_index"].to_pylist()
        valid_values = table["valid.retarget"].to_pylist()
        if len(episode_values) != len(valid_values):
            raise ValueError("statistics mask columns have different row counts")
        keep = np.asarray(
            [
                isinstance(valid, bool)
                and valid
                and int(episode_index) in training_episode_allowlist
                for episode_index, valid in zip(episode_values, valid_values, strict=True)
            ],
            dtype=bool,
        )
        if keep.any():
            filtered_tables.append((table, keep))
    if not filtered_tables:
        raise ValueError("training view contains no valid retarget frames")

    result: dict[str, dict[str, list[float] | list[int]]] = {}
    for feature_name in plan.stats_features:
        matrices = [
            _statistics_matrix(table, plan, feature_name)[keep]
            for table, keep in filtered_tables
        ]
        matrix = np.concatenate(matrices, axis=0)
        result[feature_name] = {
            "min": np.min(matrix, axis=0).tolist(),
            "max": np.max(matrix, axis=0).tolist(),
            "mean": np.mean(matrix, axis=0).tolist(),
            "std": np.std(matrix, axis=0).tolist(),
            "count": [int(matrix.shape[0])],
            "q01": np.quantile(matrix, 0.01, axis=0).tolist(),
            "q10": np.quantile(matrix, 0.10, axis=0).tolist(),
            "q50": np.quantile(matrix, 0.50, axis=0).tolist(),
            "q90": np.quantile(matrix, 0.90, axis=0).tolist(),
            "q99": np.quantile(matrix, 0.99, axis=0).tolist(),
        }
    return result


def _statistics_manifest(
    *,
    plan: LeRobotMetadataPlan,
    plan_path: Path,
    plan_sha256: str,
    output_root: Path,
    target_table_binding_manifest_path: Path,
    target_table_binding_manifest_sha256: str,
    retarget_mask_path: Path | None,
    retarget_mask_sha256: str | None,
    stats_path: Path,
    written_files: tuple[str, ...],
) -> LeRobotStatisticsWrite:
    return LeRobotStatisticsWrite(
        dataset_alias=plan.dataset_alias,
        source_revision=plan.source_revision,
        robot_id=plan.robot_id,
        plan_path=plan_path.as_posix(),
        plan_sha256=plan_sha256,
        output_root=output_root.as_posix(),
        target_table_binding_manifest_path=target_table_binding_manifest_path.as_posix(),
        target_table_binding_manifest_sha256=target_table_binding_manifest_sha256,
        retarget_mask_path=(
            retarget_mask_path.as_posix() if retarget_mask_path is not None else None
        ),
        retarget_mask_sha256=retarget_mask_sha256,
        stats_path=stats_path.as_posix(),
        stats_relative_path=stats_path.relative_to(output_root).as_posix(),
        stats_sha256=sha256_file(stats_path),
        stats_features=plan.stats_features,
        written_files=written_files,
        omitted_components=_STATS_DATASET_OMISSIONS,
        total_episodes=plan.total_episodes,
        total_frames=plan.total_frames,
        total_tasks=plan.total_tasks,
    )


def write_lerobot_statistics(
    *,
    plan_path: Path,
    output_root: Path,
    target_table_binding_manifest_path: Path,
    retarget_mask_path: Path | None = None,
) -> LeRobotStatisticsWrite:
    """Write exact numeric stats after verifying the grouped partial dataset."""

    plan_path = plan_path.resolve()
    output_root = output_root.resolve()
    target_table_binding_manifest_path = target_table_binding_manifest_path.resolve()
    plan, plan_verification = _load_verified_plan(plan_path)
    if retarget_mask_path is not None:
        _assert_external_artifact_path(
            retarget_mask_path,
            output_root.as_posix(),
            label="retarget mask",
        )
    retarget_mask, _retarget_mask_sha256 = _load_retarget_mask_for_plan(
        retarget_mask_path,
        plan=plan,
        plan_path=plan_path,
        plan_sha256=plan_verification.plan_sha256,
    )
    if plan.video_keys:
        raise ValueError("statistics writer currently supports video-free plans only")
    if not output_root.is_dir():
        raise FileNotFoundError(f"partial dataset output root does not exist: {output_root}")
    if not target_table_binding_manifest_path.is_file():
        raise FileNotFoundError(
            "target-table binding manifest does not exist: "
            f"{target_table_binding_manifest_path}"
        )
    verify_lerobot_multi_episode_dataset(
        plan_path=plan_path,
        output_root=output_root,
        target_table_binding_manifest_path=target_table_binding_manifest_path,
        retarget_mask_path=retarget_mask_path,
    )
    info_path, _tasks_path, stats_path, _episode_paths = _planned_paths(plan, output_root)
    data_paths = _data_shard_paths(plan, output_root)
    parquet = _load_pyarrow()[1]
    data_tables = {key: parquet.read_table(path) for key, path in data_paths.items()}
    stats_payload = _compute_numeric_statistics(
        plan=plan,
        data_tables=data_tables,
        retarget_mask=retarget_mask,
    )
    _write_json_exclusive(stats_path, stats_payload)
    _replace_json(
        info_path,
        _info_payload(
            plan,
            plan_sha256=plan_verification.plan_sha256,
            data_shards_written=True,
            stats_written=True,
            retarget_mask=retarget_mask,
            retarget_mask_sha256=_retarget_mask_sha256,
        ),
    )
    verification = verify_lerobot_statistics(
        plan_path=plan_path,
        output_root=output_root,
        target_table_binding_manifest_path=target_table_binding_manifest_path,
        retarget_mask_path=retarget_mask_path,
    )
    return LeRobotStatisticsWrite(
        dataset_alias=verification.dataset_alias,
        source_revision=verification.source_revision,
        robot_id=verification.robot_id,
        plan_path=verification.plan_path,
        plan_sha256=verification.plan_sha256,
        output_root=verification.output_root,
        target_table_binding_manifest_path=verification.target_table_binding_manifest_path,
        target_table_binding_manifest_sha256=verification.target_table_binding_manifest_sha256,
        retarget_mask_path=verification.retarget_mask_path,
        retarget_mask_sha256=verification.retarget_mask_sha256,
        stats_path=verification.stats_path,
        stats_relative_path=verification.stats_relative_path,
        stats_sha256=verification.stats_sha256,
        stats_features=verification.stats_features,
        written_files=verification.written_files,
        omitted_components=verification.omitted_components,
        total_episodes=verification.total_episodes,
        total_frames=verification.total_frames,
        total_tasks=verification.total_tasks,
    )


def write_lerobot_statistics_report(
    path: Path,
    manifest: LeRobotStatisticsWrite,
) -> LeRobotStatisticsWrite:
    """Persist one exclusive statistics write manifest."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(manifest.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return manifest


def verify_lerobot_statistics(
    *,
    plan_path: Path,
    output_root: Path,
    target_table_binding_manifest_path: Path,
    retarget_mask_path: Path | None = None,
) -> LeRobotStatisticsVerification:
    """Verify exact numeric stats and the complete video-free partial dataset."""

    (
        plan,
        plan_verification,
        expected_files,
        actual_tables,
        binding_sha256,
        stats_path,
        _data_paths,
        retarget_mask,
        retarget_mask_sha256,
    ) = _verify_lerobot_multi_episode_dataset_files(
        plan_path=plan_path,
        output_root=output_root,
        target_table_binding_manifest_path=target_table_binding_manifest_path,
        stats_written=True,
        retarget_mask_path=retarget_mask_path,
    )
    actual_stats = _read_json_object(stats_path, label="LeRobot stats")
    expected_stats = _compute_numeric_statistics(
        plan=plan,
        data_tables=actual_tables,
        retarget_mask=retarget_mask,
    )
    if actual_stats != expected_stats:
        raise ValueError("LeRobot stats.json does not match the written data shards")
    output_root = output_root.resolve()
    stats_path = stats_path.resolve()
    target_table_binding_manifest_path = target_table_binding_manifest_path.resolve()
    return LeRobotStatisticsVerification(
        dataset_alias=plan.dataset_alias,
        source_revision=plan.source_revision,
        robot_id=plan.robot_id,
        plan_path=plan_path.resolve().as_posix(),
        plan_sha256=plan_verification.plan_sha256,
        output_root=output_root.as_posix(),
        target_table_binding_manifest_path=target_table_binding_manifest_path.as_posix(),
        target_table_binding_manifest_sha256=binding_sha256,
        retarget_mask_path=(
            retarget_mask_path.resolve().as_posix()
            if retarget_mask_path is not None
            else None
        ),
        retarget_mask_sha256=retarget_mask_sha256,
        stats_path=stats_path.as_posix(),
        stats_relative_path=stats_path.relative_to(output_root).as_posix(),
        stats_sha256=sha256_file(stats_path),
        stats_features=plan.stats_features,
        written_files=expected_files,
        omitted_components=_STATS_DATASET_OMISSIONS,
        total_episodes=plan.total_episodes,
        total_frames=plan.total_frames,
        total_tasks=plan.total_tasks,
    )


def build_lerobot_loader_preflight(
    *,
    plan_path: Path,
    output_root: Path,
    target_table_binding_manifest_path: Path,
    retarget_mask_path: Path | None = None,
) -> LeRobotLoaderPreflight:
    """Check the local v3 numeric file contract without importing LeRobot."""

    plan_path = plan_path.resolve()
    output_root = output_root.resolve()
    target_table_binding_manifest_path = target_table_binding_manifest_path.resolve()
    plan, plan_verification = _load_verified_plan(plan_path)
    if retarget_mask_path is not None:
        _assert_external_artifact_path(
            retarget_mask_path,
            output_root.as_posix(),
            label="retarget mask",
        )
    retarget_mask, retarget_mask_sha256 = _load_retarget_mask_for_plan(
        retarget_mask_path,
        plan=plan,
        plan_path=plan_path,
        plan_sha256=plan_verification.plan_sha256,
    )
    statistics = verify_lerobot_statistics(
        plan_path=plan_path,
        output_root=output_root,
        target_table_binding_manifest_path=target_table_binding_manifest_path,
        retarget_mask_path=retarget_mask_path,
    )
    info_path, tasks_path, _stats_path, episode_paths = _planned_paths(plan, output_root)
    info = _read_json_object(info_path, label="loader preflight info")
    if info.get("codebase_version") != "v3.0":
        raise ValueError("loader preflight requires LeRobot codebase version v3.0")
    if info.get("data_path") != plan.data_path_template:
        raise ValueError("loader preflight data path does not match the metadata plan")
    if info.get("video_path") is not None:
        raise ValueError("loader preflight expects a video-free dataset")
    retarget_info = info.get("retargetlab")
    if not isinstance(retarget_info, dict):
        raise ValueError("loader preflight requires retarget metadata")
    if retarget_info.get("training_episode_allowlist") != list(
        retarget_mask.training_episode_allowlist
    ):
        raise ValueError("loader preflight training allowlist does not match retarget mask")
    if retarget_info.get("normalization_exclude") != list(
        retarget_mask.normalization_exclude
    ):
        raise ValueError("loader preflight normalization exclusions do not match retarget mask")
    if retarget_info.get("mask_policy") != retarget_mask.mask_policy:
        raise ValueError("loader preflight mask policy does not match retarget mask")
    if retarget_mask_sha256 is not None and retarget_info.get("mask_sha256") != (
        retarget_mask_sha256
    ):
        raise ValueError("loader preflight mask hash does not match dataset metadata")

    pa, parquet = _load_pyarrow()
    tasks_table = parquet.read_table(tasks_path)
    task_metadata_raw = (tasks_table.schema.metadata or {}).get(b"pandas")
    if task_metadata_raw is None:
        raise ValueError("loader preflight tasks parquet lacks pandas index metadata")
    try:
        task_metadata = json.loads(task_metadata_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("loader preflight tasks pandas metadata is invalid") from exc
    if task_metadata.get("index_columns") != ["__index_level_0__"]:
        raise ValueError("loader preflight tasks index is not the LeRobot named index")
    task_columns = {
        column.get("field_name"): column.get("name")
        for column in task_metadata.get("columns", [])
        if isinstance(column, dict)
    }
    if task_columns.get("__index_level_0__") != "task":
        raise ValueError("loader preflight tasks index name is not task")
    if task_columns.get("task_index") != "task_index":
        raise ValueError("loader preflight task_index column metadata is invalid")

    for key, episode_path in episode_paths.items():
        episode_table = parquet.read_table(episode_path)
        required_columns = {
            "episode_index",
            "tasks",
            "length",
            "dataset_from_index",
            "dataset_to_index",
            "data/chunk_index",
            "data/file_index",
            "retarget.status",
        }
        if not required_columns.issubset(episode_table.column_names):
            raise ValueError(f"loader preflight episode metadata is incomplete: {key}")
        for episode_index, status in zip(
            episode_table["episode_index"].to_pylist(),
            episode_table["retarget.status"].to_pylist(),
            strict=True,
        ):
            expected_status = next(
                item.retarget_status
                for item in retarget_mask.episodes
                if item.episode_index == episode_index
            )
            if status != expected_status:
                raise ValueError(
                    "loader preflight episode retarget status does not match mask"
                )

    physical_episode_indices = tuple(episode.episode_index for episode in plan.episodes)
    blocking_reasons: list[str] = []
    if physical_episode_indices != tuple(range(plan.total_episodes)):
        blocking_reasons.append(
            "preserve_source_episode_indices_are_not_zero_based_for_explicit_loader_selection",
        )
    if not retarget_mask.training_episode_allowlist:
        blocking_reasons.append("no_pass_episode_available_for_training")
    return LeRobotLoaderPreflight(
        status="BLOCKED" if blocking_reasons else "READY",
        dataset_alias=plan.dataset_alias,
        source_revision=plan.source_revision,
        robot_id=plan.robot_id,
        plan_path=plan_path.as_posix(),
        plan_sha256=plan_verification.plan_sha256,
        output_root=output_root.as_posix(),
        target_table_binding_manifest_path=target_table_binding_manifest_path.as_posix(),
        target_table_binding_manifest_sha256=statistics.target_table_binding_manifest_sha256,
        retarget_mask_path=(
            retarget_mask_path.as_posix() if retarget_mask_path is not None else None
        ),
        retarget_mask_sha256=retarget_mask_sha256,
        episode_indices=tuple(retarget_mask.training_episode_allowlist),
        stats_features=plan.stats_features,
        checked_files=_actual_files(output_root),
        passed_checks=(
            "info_v3_fields",
            "tasks_named_index",
            "episode_metadata_data_links",
            "data_feature_schema",
            "numeric_stats_schema",
            "video_free_inventory",
            "retarget_mask_schema",
        ),
        blocking_reasons=tuple(blocking_reasons),
        warnings=("upstream_training_compatibility_not_claimed",),
        total_episodes=plan.total_episodes,
        total_frames=plan.total_frames,
        total_tasks=plan.total_tasks,
    )


def _assert_external_artifact_path(
    path: Path,
    output_root: str,
    *,
    label: str,
) -> None:
    try:
        path.resolve().relative_to(Path(output_root).resolve())
    except ValueError:
        return
    raise ValueError(f"{label} must be outside the dataset output root")


def write_lerobot_loader_preflight(
    path: Path,
    preflight: LeRobotLoaderPreflight,
) -> LeRobotLoaderPreflight:
    """Persist one exclusive loader-contract preflight outside the dataset root."""

    _assert_external_artifact_path(path, preflight.output_root, label="loader preflight")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(preflight.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return preflight


def verify_lerobot_loader_preflight(path: Path) -> LeRobotLoaderPreflight:
    """Rebuild a loader preflight from its current dataset inputs."""

    path = path.resolve()
    preflight = LeRobotLoaderPreflight.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    expected = build_lerobot_loader_preflight(
        plan_path=Path(preflight.plan_path),
        output_root=Path(preflight.output_root),
        target_table_binding_manifest_path=Path(
            preflight.target_table_binding_manifest_path
        ),
        retarget_mask_path=(
            Path(preflight.retarget_mask_path)
            if preflight.retarget_mask_path is not None
            else None
        ),
    )
    if expected != preflight:
        raise ValueError("loader preflight does not match its bound dataset inputs")
    return preflight


def build_lerobot_training_dataset_config(
    *,
    preflight_path: Path,
) -> LeRobotTrainingDatasetConfig:
    """Build a direct ``LeRobotDataset`` configuration from a verified preflight."""

    preflight_path = preflight_path.resolve()
    preflight = verify_lerobot_loader_preflight(preflight_path)
    return LeRobotTrainingDatasetConfig(
        status=preflight.status,
        dataset_alias=preflight.dataset_alias,
        repo_id=preflight.dataset_alias,
        root=preflight.output_root,
        episodes=preflight.episode_indices,
        plan_path=preflight.plan_path,
        plan_sha256=preflight.plan_sha256,
        preflight_path=preflight_path.as_posix(),
        preflight_sha256=sha256_file(preflight_path),
        target_table_binding_manifest_path=(
            preflight.target_table_binding_manifest_path
        ),
        target_table_binding_manifest_sha256=(
            preflight.target_table_binding_manifest_sha256
        ),
        retarget_mask_path=preflight.retarget_mask_path,
        retarget_mask_sha256=preflight.retarget_mask_sha256,
        blocking_reasons=preflight.blocking_reasons,
        warnings=(*preflight.warnings, "dataset_config_is_not_a_training_run"),
    )


def write_lerobot_training_dataset_config(
    path: Path,
    config: LeRobotTrainingDatasetConfig,
) -> LeRobotTrainingDatasetConfig:
    """Persist one exclusive dataset-loader configuration outside the dataset root."""

    _assert_external_artifact_path(path, config.root, label="training dataset config")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(config.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return config


def verify_lerobot_training_dataset_config(
    path: Path,
) -> LeRobotTrainingDatasetConfig:
    """Rebuild a loader configuration from its verified preflight input."""

    path = path.resolve()
    config = LeRobotTrainingDatasetConfig.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    expected = build_lerobot_training_dataset_config(
        preflight_path=Path(config.preflight_path),
    )
    if expected != config:
        raise ValueError("training dataset config does not match its bound preflight")
    return config
