"""Bounded, provenance-preserving Parquet row selection."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from retargetlab.contracts import CalibrationSelection, EpisodeRange
from retargetlab.robot.assets import sha256_file

DEFAULT_CALIBRATION_COLUMNS = (
    "episode_index",
    "frame_index",
    "index",
    "timestamp",
    "observation.state",
    "action",
)


def _import_parquet() -> Any:
    try:
        import pyarrow.parquet as parquet  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("pyarrow is required for bounded Parquet selection") from exc
    return parquet


def _uniform_indices(start: int, length: int, count: int) -> list[int]:
    if length < count:
        raise ValueError(f"episode length {length} is shorter than requested {count} frames")
    if count == 1:
        return [start]
    return [start + round(index * (length - 1) / (count - 1)) for index in range(count)]


def _episode_ranges(
    episodes_path: Path,
    episode_indices: Sequence[int],
    *,
    parquet: Any,
) -> tuple[EpisodeRange, ...]:
    table = parquet.read_table(
        episodes_path,
        columns=["episode_index", "dataset_from_index", "dataset_to_index"],
        filters=[("episode_index", "in", list(episode_indices))],
    )
    records: dict[int, EpisodeRange] = {}
    for row in table.to_pylist():
        episode = int(row["episode_index"])
        start = int(row["dataset_from_index"])
        end = int(row["dataset_to_index"])
        records[episode] = EpisodeRange(
            episode_index=episode,
            start_row=start,
            end_row_exclusive=end,
            length=end - start,
        )
    missing = [episode for episode in episode_indices if episode not in records]
    if missing:
        raise ValueError(f"episode metadata is missing requested episodes: {missing}")
    return tuple(records[episode] for episode in episode_indices)


def select_calibration_rows(
    data_path: Path,
    episodes_path: Path,
    *,
    dataset_alias: str,
    source_revision: str,
    episode_indices: Sequence[int],
    frames_per_episode: int,
    max_frames: int = 60,
    columns: Sequence[str] = DEFAULT_CALIBRATION_COLUMNS,
) -> tuple[list[dict[str, object]], CalibrationSelection]:
    """Read only a bounded, deterministic calibration slice from Parquet."""

    if not data_path.is_file():
        raise FileNotFoundError(f"data Parquet file does not exist: {data_path}")
    if not episodes_path.is_file():
        raise FileNotFoundError(f"episode Parquet file does not exist: {episodes_path}")
    requested = tuple(episode_indices)
    if not requested or any(index < 0 for index in requested):
        raise ValueError("episode_indices must contain non-negative episode ids")
    if len(set(requested)) != len(requested):
        raise ValueError("episode_indices must be unique")
    if frames_per_episode <= 0 or frames_per_episode > 60:
        raise ValueError("frames_per_episode must be between 1 and 60")
    if max_frames <= 0 or max_frames > 60:
        raise ValueError("max_frames must be between 1 and 60")
    if len(requested) * frames_per_episode > max_frames:
        raise ValueError(f"selected calibration rows must not exceed {max_frames} frames")
    selected_columns = tuple(dict.fromkeys(columns))
    required = {"episode_index", "frame_index", "index"}
    if not required.issubset(selected_columns):
        raise ValueError(f"columns must include {sorted(required)}")

    parquet = _import_parquet()
    ranges = _episode_ranges(episodes_path, requested, parquet=parquet)
    selected_by_index: dict[int, int] = {}
    selected_frame_by_index: dict[int, int] = {}
    for episode_range in ranges:
        for relative_frame in _uniform_indices(
            0,
            episode_range.length,
            frames_per_episode,
        ):
            row_index = episode_range.start_row + relative_frame
            if row_index in selected_by_index:
                raise ValueError(f"episode ranges overlap at row index {row_index}")
            selected_by_index[row_index] = episode_range.episode_index
            selected_frame_by_index[row_index] = relative_frame
    selected_indices = tuple(sorted(selected_by_index))
    table = parquet.read_table(
        data_path,
        columns=list(selected_columns),
        filters=[("index", "in", list(selected_indices))],
    )
    rows: list[dict[str, object]] = [dict(row) for row in table.to_pylist()]
    rows_by_index: dict[int, dict[str, object]] = {}
    for row in rows:
        if "index" not in row:
            raise ValueError("selected data rows do not contain index")
        value = row["index"]
        if not isinstance(value, int):
            raise ValueError("selected data row index is not an integer")
        index = value
        if index in rows_by_index:
            raise ValueError(f"duplicate selected data row index: {index}")
        episode_value = row.get("episode_index")
        frame_value = row.get("frame_index")
        if not isinstance(episode_value, int) or not isinstance(frame_value, int):
            raise ValueError("selected data row episode/frame indices must be integers")
        if selected_by_index.get(index) != episode_value:
            raise ValueError(f"selected data row crosses an episode boundary: {index}")
        if selected_frame_by_index.get(index) != frame_value:
            raise ValueError(f"selected data row has an unexpected frame index: {index}")
        rows_by_index[index] = row
    if tuple(sorted(rows_by_index)) != selected_indices:
        raise ValueError("selected data rows do not match requested episode ranges")
    ordered_rows = [rows_by_index[index] for index in selected_indices]
    selection = CalibrationSelection(
        dataset_alias=dataset_alias,
        source_revision=source_revision,
        data_sha256=sha256_file(data_path),
        episodes_sha256=sha256_file(episodes_path),
        frames_per_episode=frames_per_episode,
        episode_ranges=ranges,
        selected_row_indices=selected_indices,
        selected_frame_count=len(selected_indices),
    )
    return ordered_rows, selection
