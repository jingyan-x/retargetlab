"""Read-only joint-space command timing analysis."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from retargetlab.contracts import CommandTimingReport, TimingShiftResult
from retargetlab.robot.assets import sha256_file

_TIMING_COLUMNS = ("episode_index", "frame_index", "observation.state.position", "action.position")


def _vector(row: dict[str, Any], name: str, *, episode: int, frame: int) -> tuple[float, ...]:
    value = row.get(name)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} is not a vector at episode {episode}, frame {frame}")
    result = tuple(float(item) for item in value)
    if not result or any(not math.isfinite(item) for item in result):
        raise ValueError(f"{name} contains invalid values at episode {episode}, frame {frame}")
    return result


def _load_rows(path: Path, episode_indices: tuple[int, ...]) -> dict[int, list[dict[str, Any]]]:
    try:
        import pyarrow.parquet as parquet  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("pyarrow is required for command timing analysis") from exc
    if not path.is_file():
        raise FileNotFoundError(f"Parquet file does not exist: {path}")
    parquet_file = parquet.ParquetFile(path)
    missing = sorted(set(_TIMING_COLUMNS) - set(parquet_file.schema_arrow.names))
    if missing:
        raise ValueError(f"timing analysis is missing columns: {missing}")
    table = parquet.read_table(
        path,
        columns=list(_TIMING_COLUMNS),
        filters=[("episode_index", "in", list(episode_indices))],
    )
    rows: dict[int, list[dict[str, Any]]] = {episode: [] for episode in episode_indices}
    for row in table.to_pylist():
        episode = int(row["episode_index"])
        if episode not in rows:
            raise ValueError("timing filter returned an unrequested episode")
        rows[episode].append(row)
    for episode, episode_rows in rows.items():
        episode_rows.sort(key=lambda row: int(row["frame_index"]))
        frame_indices = [int(row["frame_index"]) for row in episode_rows]
        if frame_indices != list(range(len(episode_rows))):
            raise ValueError(f"episode {episode} frame indices are not contiguous")
    return rows


def analyze_command_timing(
    path: Path,
    *,
    dataset_alias: str,
    source_revision: str,
    episode_indices: tuple[int, ...],
    joint_indices: tuple[int, ...],
    action_scales: tuple[float, ...] | None = None,
    action_offsets: tuple[float, ...] | None = None,
    max_shift: int = 8,
    expected_shift_range: tuple[int, int] = (4, 5),
) -> CommandTimingReport:
    """Rank action[t] against state[t+k] inside explicitly selected episodes."""

    if not episode_indices:
        raise ValueError("timing analysis requires at least one episode")
    if len(set(episode_indices)) != len(episode_indices):
        raise ValueError("timing episode indices must be unique")
    if any(index < 0 for index in episode_indices):
        raise ValueError("timing episode indices must be non-negative")
    if not joint_indices:
        raise ValueError("timing analysis requires at least one joint")
    if len(set(joint_indices)) != len(joint_indices):
        raise ValueError("timing joint indices must be unique")
    if any(index < 0 for index in joint_indices):
        raise ValueError("timing joint indices must be non-negative")
    if action_scales is None:
        if action_offsets is not None:
            raise ValueError("action scales and offsets must be supplied together")
        scales = (1.0,) * len(joint_indices)
        offsets = (0.0,) * len(joint_indices)
    else:
        if action_offsets is None:
            raise ValueError("action scales and offsets must be supplied together")
        scales = action_scales
        offsets = action_offsets
    if len(scales) != len(joint_indices) or len(offsets) != len(joint_indices):
        raise ValueError("action transforms must match joint indices")
    if any(not math.isfinite(value) or value == 0.0 for value in scales):
        raise ValueError("action scales must be finite and non-zero")
    if any(not math.isfinite(value) for value in offsets):
        raise ValueError("action offsets must be finite")
    if max_shift < 0:
        raise ValueError("max_shift must be non-negative")
    expected_min, expected_max = expected_shift_range
    if expected_min < 0 or expected_max < expected_min:
        raise ValueError("expected timing shift range is invalid")
    if expected_max > max_shift:
        raise ValueError("expected timing shift exceeds max_shift")

    rows = _load_rows(path, episode_indices)
    all_vectors: list[tuple[list[tuple[float, ...]], list[tuple[float, ...]]]] = []
    source_joint_count: int | None = None
    frame_count = 0
    for episode in episode_indices:
        episode_rows = rows[episode]
        if len(episode_rows) <= max_shift:
            raise ValueError(f"episode {episode} has too few frames for max_shift={max_shift}")
        state_vectors: list[tuple[float, ...]] = []
        action_vectors: list[tuple[float, ...]] = []
        for row in episode_rows:
            frame = int(row["frame_index"])
            state = _vector(row, "observation.state.position", episode=episode, frame=frame)
            action = _vector(row, "action.position", episode=episode, frame=frame)
            if len(state) != len(action):
                raise ValueError(
                    f"state/action dimensions differ at episode {episode}, frame {frame}"
                )
            if source_joint_count is None:
                source_joint_count = len(state)
            elif len(state) != source_joint_count:
                raise ValueError("timing joint dimensions differ across episodes")
            if any(index >= len(state) for index in joint_indices):
                raise ValueError("timing joint index exceeds source vector dimension")
            state_vectors.append(state)
            action_vectors.append(action)
        all_vectors.append((state_vectors, action_vectors))
        frame_count += len(episode_rows)

    if source_joint_count is None:  # pragma: no cover - guarded by episode length checks
        raise ValueError("timing analysis found no rows")

    shift_results: list[TimingShiftResult] = []
    for shift in range(max_shift + 1):
        squared_errors = [0.0] * len(joint_indices)
        pair_count = 0
        for state_vectors, action_vectors in all_vectors:
            for index in range(len(action_vectors) - shift):
                action = action_vectors[index]
                state = state_vectors[index + shift]
                for joint, source_index in enumerate(joint_indices):
                    action_value = action[source_index] * scales[joint] + offsets[joint]
                    state_value = state[source_index]
                    squared_errors[joint] += (action_value - state_value) ** 2
                pair_count += 1
        per_joint_rmse = tuple(math.sqrt(value / pair_count) for value in squared_errors)
        rmse = math.sqrt(sum(squared_errors) / (pair_count * len(joint_indices)))
        shift_results.append(
            TimingShiftResult(
                shift=shift,
                pair_count=pair_count,
                rmse=rmse,
                per_joint_rmse=per_joint_rmse,
            )
        )

    best_result = min(shift_results, key=lambda item: (item.rmse, item.shift))
    return CommandTimingReport(
        status=("SUPPORTED" if expected_min <= best_result.shift <= expected_max else "CONFLICTED"),
        dataset_alias=dataset_alias,
        source_revision=source_revision,
        data_sha256=sha256_file(path),
        episode_indices=episode_indices,
        episode_count=len(episode_indices),
        frame_count=frame_count,
        joint_indices=joint_indices,
        joint_count=len(joint_indices),
        action_scales=scales,
        action_offsets=offsets,
        max_shift=max_shift,
        expected_shift_min=expected_min,
        expected_shift_max=expected_max,
        best_shift=best_result.shift,
        best_rmse=best_result.rmse,
        shifts=tuple(shift_results),
    )
