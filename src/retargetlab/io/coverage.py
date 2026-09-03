"""Read-only coverage scan for a LeRobot-style dataset revision."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from retargetlab.contracts import DatasetCoverage, DatasetRevision, EpisodeCoverage
from retargetlab.io.compare import compare_info_to_structure
from retargetlab.io.probe.lerobot import probe_lerobot_info
from retargetlab.io.probe.parquet import probe_parquet
from retargetlab.robot.assets import sha256_file


def _import_parquet() -> Any:
    try:
        import pyarrow.parquet as parquet  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("pyarrow is required for dataset coverage scanning") from exc
    return parquet


def _episode_ranges(path: Path, *, parquet: Any) -> tuple[EpisodeCoverage, ...]:
    table = parquet.read_table(
        path,
        columns=["episode_index", "dataset_from_index", "dataset_to_index"],
    )
    rows: list[EpisodeCoverage] = []
    for row in table.to_pylist():
        start = int(row["dataset_from_index"])
        end = int(row["dataset_to_index"])
        rows.append(
            EpisodeCoverage(
                episode_index=int(row["episode_index"]),
                start_row=start,
                end_row_exclusive=end,
                length=end - start,
            )
        )
    return tuple(sorted(rows, key=lambda item: item.episode_index))


def _coverage_reasons(
    *,
    declared_episodes: int,
    declared_frames: int,
    declared_tasks: int,
    observed_episodes: int,
    observed_frames: int,
    data_rows: int,
    observed_tasks: int,
    ranges: Sequence[EpisodeCoverage],
    structure_compatible: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if observed_episodes != declared_episodes:
        reasons.append("episode count differs from info.json")
    if observed_frames != declared_frames:
        reasons.append("episode interval sum differs from info.json")
    if data_rows != declared_frames:
        reasons.append("data row count differs from info.json")
    if observed_tasks != declared_tasks:
        reasons.append("task row count differs from info.json")
    expected_start = 0
    for item in ranges:
        if item.start_row != expected_start:
            reasons.append("episode intervals are not contiguous")
            break
        expected_start = item.end_row_exclusive
    if ranges and ranges[-1].end_row_exclusive != data_rows:
        reasons.append("episode intervals do not cover the data row count")
    if not structure_compatible:
        reasons.append("declared features are incompatible with the data schema")
    return tuple(dict.fromkeys(reasons))


def scan_lerobot_coverage(
    *,
    info_path: Path,
    data_path: Path,
    episodes_path: Path,
    tasks_path: Path,
    stats_path: Path,
    dataset_alias: str,
    source_revision: str,
    validation_scope: str,
    reader_version: str = "lerobot==0.6.1",
) -> DatasetCoverage:
    """Scan structure, episode intervals, and metadata counts without source rows."""

    info = probe_lerobot_info(
        info_path,
        dataset_alias=dataset_alias,
        source_revision=source_revision,
    )
    data = probe_parquet(data_path, dataset_alias=dataset_alias, source_revision=source_revision)
    episodes = probe_parquet(
        episodes_path,
        dataset_alias=dataset_alias,
        source_revision=source_revision,
    )
    tasks = probe_parquet(tasks_path, dataset_alias=dataset_alias, source_revision=source_revision)
    stats_raw = json.loads(stats_path.read_text(encoding="utf-8"))
    if not isinstance(stats_raw, dict) or any(not isinstance(key, str) for key in stats_raw):
        raise ValueError("stats manifest must contain a JSON object with string feature keys")

    ranges = _episode_ranges(episodes_path, parquet=_import_parquet())
    comparison = compare_info_to_structure(info, data)
    reasons = _coverage_reasons(
        declared_episodes=info.total_episodes,
        declared_frames=info.total_frames,
        declared_tasks=info.total_tasks,
        observed_episodes=len(ranges),
        observed_frames=sum(item.length for item in ranges),
        data_rows=data.row_count,
        observed_tasks=tasks.row_count,
        ranges=ranges,
        structure_compatible=comparison.compatible,
    )
    revision = DatasetRevision(
        info_sha256=sha256_file(info_path),
        data_sha256=sha256_file(data_path),
        episodes_sha256=sha256_file(episodes_path),
        tasks_sha256=sha256_file(tasks_path),
        stats_sha256=sha256_file(stats_path),
    )
    return DatasetCoverage(
        status="COMPLETE" if not reasons else "INCONSISTENT",
        dataset_alias=dataset_alias,
        source_revision=source_revision,
        reader_version=reader_version,
        revision=revision,
        declared_total_episodes=info.total_episodes,
        declared_total_frames=info.total_frames,
        declared_total_tasks=info.total_tasks,
        declared_total_chunks=info.total_chunks,
        observed_episode_count=len(ranges),
        observed_frame_count=sum(item.length for item in ranges),
        data_row_count=data.row_count,
        observed_task_count=tasks.row_count,
        episode_ranges=ranges,
        data_fields=tuple(sorted(data.fields)),
        episode_fields=tuple(sorted(episodes.fields)),
        task_fields=tuple(sorted(tasks.fields)),
        declared_features=tuple(sorted(info.features)),
        stats_features=tuple(sorted(stats_raw)),
        structure_compatible=comparison.compatible,
        structure_fully_verified=comparison.fully_verified,
        shape_unverified=comparison.shape_unverified,
        shape_normalized=comparison.shape_normalized,
        coverage_complete=not reasons,
        validation_scope=validation_scope,
        blocking_reasons=reasons,
    )
