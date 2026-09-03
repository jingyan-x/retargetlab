"""Build, persist, and verify metadata-only LeRobot v3 export artifacts."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from retargetlab.contracts import (
    ExportInputGate,
    ExportProfile,
    FeatureDeclaration,
    LeRobotEpisodeMetadata,
    LeRobotMetadataPlan,
    LeRobotMetadataPlanVerification,
    LeRobotMetadataSkeletonVerification,
    LeRobotMetadataSkeletonWrite,
    LeRobotTaskMetadata,
)
from retargetlab.robot.assets import sha256_file
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes

_SKELETON_OMISSIONS = ("data_shards", "video_shards", "meta/stats.json")
_DEFAULT_CHUNKS_SIZE = 1000


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


def _info_payload(plan: LeRobotMetadataPlan, *, plan_sha256: str) -> dict[str, Any]:
    episode_indices = plan.training_episode_allowlist
    split_start = min(episode_indices)
    split_end = max(episode_indices) + 1
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
        "fps": plan.fps,
        "splits": {"train": f"{split_start}:{split_end}"},
        "data_path": plan.data_path_template,
        "features": {
            name: _feature_payload(feature) for name, feature in plan.features.items()
        },
        "retargetlab": {
            "artifact_type": "lerobot_metadata_skeleton",
            "status": "PARTIAL",
            "source_scope": plan.source_scope,
            "plan_sha256": plan_sha256,
            "episode_index_policy": plan.episode_index_policy,
            "training_episode_allowlist": list(plan.training_episode_allowlist),
            "episodes_path": plan.episodes_path_template,
            "stats_features": list(plan.stats_features),
            "omitted_components": list(_SKELETON_OMISSIONS),
        },
    }


def _tasks_table(pa: Any, plan: LeRobotMetadataPlan) -> Any:
    return pa.table(
        {
            "task": pa.array([task.task for task in plan.tasks], type=pa.string()),
            "task_index": pa.array(
                [task.task_index for task in plan.tasks],
                type=pa.int64(),
            ),
        }
    )


def _episodes_table(
    pa: Any,
    episodes: Sequence[LeRobotEpisodeMetadata],
    task_by_index: Mapping[int, str],
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
