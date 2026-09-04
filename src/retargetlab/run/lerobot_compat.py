"""Materialize and verify an explicit zero-based LeRobot loader view."""

from __future__ import annotations

import copy
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from retargetlab.contracts import (
    LeRobotEpisodeIndexMapping,
    LeRobotFileHash,
    LeRobotLoaderCompatibleDatasetVerification,
    LeRobotLoaderCompatibleDatasetWrite,
    LeRobotLoaderPreflight,
    LeRobotMetadataPlan,
)
from retargetlab.robot.assets import sha256_file

from . import lerobot_export as export

_SOURCE_INDEX_BLOCKER = (
    "preserve_source_episode_indices_are_not_zero_based_for_explicit_loader_selection"
)


@dataclass(frozen=True)
class _SourceContext:
    preflight_path: Path
    preflight: LeRobotLoaderPreflight
    plan_path: Path
    plan: LeRobotMetadataPlan
    plan_sha256: str
    source_root: Path
    info_path: Path
    tasks_path: Path
    stats_path: Path
    episode_paths: dict[tuple[int, int], Path]
    data_paths: dict[tuple[int, int], Path]
    relative_files: tuple[str, ...]
    mapping: tuple[LeRobotEpisodeIndexMapping, ...]


def _assert_external_manifest_path(path: Path, output_root: str) -> None:
    try:
        path.resolve().relative_to(Path(output_root).resolve())
    except ValueError:
        return
    raise ValueError("loader compatibility manifest must be outside the dataset root")


def _assert_disjoint_roots(source_root: Path, output_root: Path) -> None:
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    if source_root == output_root:
        raise ValueError("loader compatibility source and output roots must differ")
    for parent, child, label in (
        (source_root, output_root, "output root"),
        (output_root, source_root, "source root"),
    ):
        try:
            child.relative_to(parent)
        except ValueError:
            continue
        raise ValueError(f"loader compatibility {label} must not be nested")


def _mapping_for_plan(
    plan: LeRobotMetadataPlan,
) -> tuple[LeRobotEpisodeIndexMapping, ...]:
    source_indices = tuple(episode.episode_index for episode in plan.episodes)
    if source_indices == tuple(range(plan.total_episodes)):
        raise ValueError(
            "loader compatibility view is only needed for non-zero-based source episodes"
        )
    return tuple(
        LeRobotEpisodeIndexMapping(
            source_episode_index=episode.episode_index,
            loader_episode_index=loader_index,
            length=episode.length,
            dataset_from_index=episode.dataset_from_index,
            dataset_to_index=episode.dataset_to_index,
        )
        for loader_index, episode in enumerate(plan.episodes)
    )


def _relative_files(
    output_root: Path,
    paths: tuple[Path, ...],
) -> tuple[str, ...]:
    return tuple(sorted(path.relative_to(output_root).as_posix() for path in paths))


def _source_context(preflight_path: Path) -> _SourceContext:
    preflight_path = preflight_path.resolve()
    preflight = export.verify_lerobot_loader_preflight(preflight_path)
    if preflight.episode_index_mapping_path is not None:
        raise ValueError("compatibility materializer requires a source preflight")
    plan_path = Path(preflight.plan_path).resolve()
    plan, plan_verification = export._load_verified_plan(plan_path)
    if preflight.plan_sha256.lower() != plan_verification.plan_sha256.lower():
        raise ValueError("source preflight plan hash does not match the plan")
    source_root = Path(preflight.output_root).resolve()
    info_path, tasks_path, stats_path, episode_paths = export._planned_paths(
        plan,
        source_root,
    )
    data_paths = export._data_shard_paths(plan, source_root)
    expected_files = _relative_files(
        source_root,
        (info_path, tasks_path, stats_path, *episode_paths.values(), *data_paths.values()),
    )
    if expected_files != preflight.checked_files:
        raise ValueError("source preflight file inventory does not match the plan")
    if export._actual_files(source_root) != expected_files:
        raise ValueError("source dataset file inventory changed after preflight")
    return _SourceContext(
        preflight_path=preflight_path,
        preflight=preflight,
        plan_path=plan_path,
        plan=plan,
        plan_sha256=plan_verification.plan_sha256,
        source_root=source_root,
        info_path=info_path,
        tasks_path=tasks_path,
        stats_path=stats_path,
        episode_paths=episode_paths,
        data_paths=data_paths,
        relative_files=expected_files,
        mapping=_mapping_for_plan(plan),
    )


def _mapping_by_source(
    mapping: tuple[LeRobotEpisodeIndexMapping, ...],
) -> dict[int, LeRobotEpisodeIndexMapping]:
    return {item.source_episode_index: item for item in mapping}


def _mapping_by_loader(
    mapping: tuple[LeRobotEpisodeIndexMapping, ...],
) -> dict[int, LeRobotEpisodeIndexMapping]:
    return {item.loader_episode_index: item for item in mapping}


def _remap_table(
    table: Any,
    mapping: tuple[LeRobotEpisodeIndexMapping, ...],
    *,
    label: str,
) -> Any:
    if "episode_index" not in table.column_names:
        raise ValueError(f"{label} is missing episode_index")
    by_source = _mapping_by_source(mapping)
    source_values = [int(value) for value in table["episode_index"].to_pylist()]
    try:
        loader_values = [by_source[value].loader_episode_index for value in source_values]
    except KeyError as exc:
        raise ValueError(f"{label} contains an unmapped source episode") from exc
    pa, _parquet = export._load_pyarrow()
    column = table["episode_index"]
    return table.set_column(
        table.column_names.index("episode_index"),
        "episode_index",
        pa.array(
            loader_values,
            type=column.type,
        ),
    )


def _compatible_info(
    source_info: dict[str, Any],
    context: _SourceContext,
) -> dict[str, Any]:
    result = copy.deepcopy(source_info)
    retarget_info = result.get("retargetlab")
    if not isinstance(retarget_info, dict):
        raise ValueError("source dataset info lacks retarget metadata")
    source_statuses = retarget_info.get("episode_statuses")
    if not isinstance(source_statuses, dict):
        raise ValueError("source dataset info lacks episode statuses")
    source_allowlist = tuple(int(index) for index in context.preflight.episode_indices)
    by_source = _mapping_by_source(context.mapping)
    if any(index not in by_source for index in source_allowlist):
        raise ValueError("source preflight allowlist contains an unmapped episode")
    loader_allowlist = tuple(by_source[index].loader_episode_index for index in source_allowlist)
    loader_statuses: dict[str, Any] = {}
    for item in context.mapping:
        source_key = str(item.source_episode_index)
        if source_key not in source_statuses:
            raise ValueError("source dataset info lacks a mapped episode status")
        loader_statuses[str(item.loader_episode_index)] = source_statuses[source_key]
    retarget_info.update(
        {
            "episode_index_policy": "reindex_zero_based_for_loader",
            "source_episode_index_policy": context.plan.episode_index_policy,
            "loader_episode_index_policy": "zero_based_contiguous",
            "source_episode_index_mapping": [
                item.model_dump(mode="json") for item in context.mapping
            ],
            "source_training_episode_allowlist": list(source_allowlist),
            "training_episode_allowlist": list(loader_allowlist),
            "source_episode_statuses": dict(source_statuses),
            "episode_statuses": loader_statuses,
            "source_plan_sha256": context.plan_sha256,
            "source_preflight_sha256": sha256_file(context.preflight_path),
        }
    )
    return result


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _copy_file_exclusive(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as source_handle, target.open("xb") as target_handle:
        shutil.copyfileobj(source_handle, target_handle)


def _file_hashes(root: Path, relative_files: tuple[str, ...]) -> tuple[LeRobotFileHash, ...]:
    return tuple(
        LeRobotFileHash(path=relative, sha256=sha256_file(root / relative))
        for relative in relative_files
    )


def _materialize(context: _SourceContext, output_root: Path) -> None:
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"loader compatibility output root already exists: {output_root}")
    _assert_disjoint_roots(context.source_root, output_root)
    staging_root = output_root.with_name(f"{output_root.name}.staging")
    if staging_root.exists():
        raise FileExistsError(f"loader compatibility staging root already exists: {staging_root}")
    pa, parquet = export._load_pyarrow()
    source_info = export._read_json_object(context.info_path, label="source dataset info")
    info_relative = context.info_path.relative_to(context.source_root).as_posix()
    episode_relative = {
        path.relative_to(context.source_root).as_posix() for path in context.episode_paths.values()
    }
    data_relative = {
        path.relative_to(context.source_root).as_posix() for path in context.data_paths.values()
    }
    try:
        staging_root.mkdir(parents=True, exist_ok=False)
        _write_json_exclusive(
            staging_root / info_relative,
            _compatible_info(source_info, context),
        )
        for relative in context.relative_files:
            if relative == info_relative:
                continue
            source_path = context.source_root / relative
            target_path = staging_root / relative
            if relative in episode_relative or relative in data_relative:
                table = parquet.read_table(source_path)
                remapped = _remap_table(
                    table,
                    context.mapping,
                    label=f"source table {relative}",
                )
                export._write_parquet_exclusive(parquet, remapped, target_path)
            else:
                _copy_file_exclusive(source_path, target_path)
        staging_root.replace(output_root)
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise


def _manifest(
    context: _SourceContext,
    output_root: Path,
) -> LeRobotLoaderCompatibleDatasetWrite:
    output_root = output_root.resolve()
    source_hashes = _file_hashes(context.source_root, context.relative_files)
    output_hashes = _file_hashes(output_root, context.relative_files)
    source_allowlist = tuple(int(index) for index in context.preflight.episode_indices)
    by_source = _mapping_by_source(context.mapping)
    loader_allowlist = tuple(by_source[index].loader_episode_index for index in source_allowlist)
    return LeRobotLoaderCompatibleDatasetWrite(
        dataset_alias=context.plan.dataset_alias,
        source_revision=context.plan.source_revision,
        robot_id=context.plan.robot_id,
        source_plan_path=context.plan_path.as_posix(),
        source_plan_sha256=context.plan_sha256,
        source_preflight_path=context.preflight_path.as_posix(),
        source_preflight_sha256=sha256_file(context.preflight_path),
        source_output_root=context.source_root.as_posix(),
        output_root=output_root.as_posix(),
        episode_index_mapping=context.mapping,
        source_training_episode_allowlist=source_allowlist,
        loader_training_episode_allowlist=loader_allowlist,
        source_file_hashes=source_hashes,
        output_file_hashes=output_hashes,
        written_files=context.relative_files,
        omitted_components=("video_shards",),
        total_episodes=context.plan.total_episodes,
        total_frames=context.plan.total_frames,
        total_tasks=context.plan.total_tasks,
    )


def write_lerobot_loader_compatible_dataset(
    *,
    source_preflight_path: Path,
    output_root: Path,
) -> LeRobotLoaderCompatibleDatasetWrite:
    """Materialize a zero-based view from a fully verified source-preserving dataset."""

    context = _source_context(source_preflight_path)
    _materialize(context, output_root)
    return _manifest(context, output_root)


def _verify_output_tables(context: _SourceContext, output_root: Path) -> None:
    _pa, parquet = export._load_pyarrow()
    for path in (*context.episode_paths.values(), *context.data_paths.values()):
        relative = path.relative_to(context.source_root).as_posix()
        actual = parquet.read_table(output_root / relative)
        expected = _remap_table(
            parquet.read_table(path),
            context.mapping,
            label=f"source table {relative}",
        )
        export._assert_table_matches(actual, expected, label=f"compatible table {relative}")
    expected_info = _compatible_info(
        export._read_json_object(context.info_path, label="source dataset info"),
        context,
    )
    actual_info = export._read_json_object(
        output_root / context.info_path.relative_to(context.source_root),
        label="compatible dataset info",
    )
    if actual_info != expected_info:
        raise ValueError("loader-compatible info.json does not match the source mapping")


def verify_lerobot_loader_compatible_dataset(
    path: Path,
) -> LeRobotLoaderCompatibleDatasetVerification:
    """Rebuild source and target content and verify the compatibility receipt."""

    path = path.resolve()
    manifest = LeRobotLoaderCompatibleDatasetWrite.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    _assert_external_manifest_path(path, manifest.output_root)
    context = _source_context(Path(manifest.source_preflight_path))
    expected = _manifest(context, Path(manifest.output_root))
    if expected != manifest:
        raise ValueError("loader-compatible manifest does not match its source or output")
    _verify_output_tables(context, Path(manifest.output_root).resolve())
    return LeRobotLoaderCompatibleDatasetVerification(
        dataset_alias=manifest.dataset_alias,
        source_revision=manifest.source_revision,
        robot_id=manifest.robot_id,
        source_plan_path=manifest.source_plan_path,
        source_plan_sha256=manifest.source_plan_sha256,
        source_preflight_path=manifest.source_preflight_path,
        source_preflight_sha256=manifest.source_preflight_sha256,
        source_output_root=manifest.source_output_root,
        output_root=manifest.output_root,
        compatibility_manifest_sha256=sha256_file(path),
        episode_index_mapping=manifest.episode_index_mapping,
        source_training_episode_allowlist=manifest.source_training_episode_allowlist,
        loader_training_episode_allowlist=manifest.loader_training_episode_allowlist,
        source_file_hashes=manifest.source_file_hashes,
        output_file_hashes=manifest.output_file_hashes,
        written_files=manifest.written_files,
        omitted_components=manifest.omitted_components,
        total_episodes=manifest.total_episodes,
        total_frames=manifest.total_frames,
        total_tasks=manifest.total_tasks,
    )


def write_lerobot_loader_compatible_dataset_report(
    path: Path,
    manifest: LeRobotLoaderCompatibleDatasetWrite,
) -> LeRobotLoaderCompatibleDatasetWrite:
    """Persist one exclusive compatibility receipt outside the output root."""

    _assert_external_manifest_path(path, manifest.output_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(manifest.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return manifest


def build_lerobot_loader_compatible_preflight(
    *,
    compatibility_manifest_path: Path,
) -> LeRobotLoaderPreflight:
    """Build the loader preflight for a verified zero-based compatibility view."""

    compatibility_manifest_path = compatibility_manifest_path.resolve()
    verification = verify_lerobot_loader_compatible_dataset(compatibility_manifest_path)
    manifest = LeRobotLoaderCompatibleDatasetWrite.model_validate_json(
        compatibility_manifest_path.read_text(encoding="utf-8")
    )
    source_preflight = export.verify_lerobot_loader_preflight(
        Path(manifest.source_preflight_path)
    )
    if _SOURCE_INDEX_BLOCKER not in source_preflight.blocking_reasons:
        raise ValueError(
            "compatibility view requires the source preflight episode-index blocker"
        )
    remaining_reasons = tuple(
        reason for reason in source_preflight.blocking_reasons if reason != _SOURCE_INDEX_BLOCKER
    )
    passed_checks = tuple(
        dict.fromkeys(
            (
                *source_preflight.passed_checks,
                "source_episode_index_remap",
                "loader_episode_indices_zero_based",
            )
        )
    )
    warnings = tuple(
        dict.fromkeys(
            (
                *source_preflight.warnings,
                "loader_view_reindexes_source_episode_indices",
            )
        )
    )
    return LeRobotLoaderPreflight(
        status="BLOCKED" if remaining_reasons else "READY",
        dataset_alias=manifest.dataset_alias,
        source_revision=manifest.source_revision,
        robot_id=manifest.robot_id,
        plan_path=manifest.source_plan_path,
        plan_sha256=manifest.source_plan_sha256,
        output_root=manifest.output_root,
        target_table_binding_manifest_path=source_preflight.target_table_binding_manifest_path,
        target_table_binding_manifest_sha256=(
            source_preflight.target_table_binding_manifest_sha256
        ),
        episode_index_mapping_path=compatibility_manifest_path.as_posix(),
        episode_index_mapping_sha256=verification.compatibility_manifest_sha256,
        retarget_mask_path=source_preflight.retarget_mask_path,
        retarget_mask_sha256=source_preflight.retarget_mask_sha256,
        episode_indices=manifest.loader_training_episode_allowlist,
        stats_features=source_preflight.stats_features,
        checked_files=manifest.written_files,
        passed_checks=passed_checks,
        blocking_reasons=remaining_reasons,
        warnings=warnings,
        total_episodes=manifest.total_episodes,
        total_frames=manifest.total_frames,
        total_tasks=manifest.total_tasks,
    )
