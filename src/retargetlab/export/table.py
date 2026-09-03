"""Synthetic/public Parquet table writer for verified target replay values."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from retargetlab.contracts import (
    SyntheticTableWritePreflight,
    SyntheticTargetTableExport,
    TargetReplayBundle,
    TargetReplayTrajectory,
)
from retargetlab.robot.assets import sha256_file

_REQUIRED_SOURCE_COLUMNS = (
    "timestamp",
    "frame_index",
    "episode_index",
    "task_index",
    "observation.state",
    "action",
)
_REPLACED_COLUMNS = ("observation.state", "action")


def _load_pyarrow() -> tuple[Any, Any]:
    try:
        import pyarrow as pa  # type: ignore[import-untyped]
        import pyarrow.parquet as parquet  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("pyarrow is required for synthetic table writing") from exc
    return pa, parquet


def _finite_float(value: Any, *, column: str, row: int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{column} must contain numeric values at row {row}")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{column} must contain finite values at row {row}")
    return converted


def _integer(value: Any, *, column: str, row: int) -> int:
    converted = _finite_float(value, column=column, row=row)
    if not converted.is_integer():
        raise ValueError(f"{column} must contain integer values at row {row}")
    return int(converted)


def _read_verified_bundle(
    bundle_path: Path,
) -> tuple[TargetReplayBundle, Any, TargetReplayTrajectory, TargetReplayTrajectory]:
    """Verify the bundle before opening the synthetic source table."""

    from retargetlab.run.replay import verify_target_replay_bundle

    verification = verify_target_replay_bundle(bundle_path)
    bundle = TargetReplayBundle.model_validate_json(bundle_path.read_text(encoding="utf-8"))
    state = TargetReplayTrajectory.model_validate_json(
        Path(bundle.observation_state_path).read_text(encoding="utf-8")
    )
    action = TargetReplayTrajectory.model_validate_json(
        Path(bundle.action_path).read_text(encoding="utf-8")
    )
    return bundle, verification, state, action


def _validate_source_table(table: Any, bundle: TargetReplayBundle, state: Any) -> tuple[str, ...]:
    source_columns = tuple(str(column) for column in table.column_names)
    missing = [column for column in _REQUIRED_SOURCE_COLUMNS if column not in source_columns]
    if missing:
        raise ValueError(f"synthetic table is missing required columns: {missing}")
    if "valid.retarget" in source_columns:
        raise ValueError("source table must not already contain valid.retarget")
    if table.num_rows != bundle.frame_count:
        raise ValueError(
            "synthetic table row count does not match the verified replay bundle frame count"
        )

    episode_indices = [
        _integer(value, column="episode_index", row=row)
        for row, value in enumerate(table["episode_index"].to_pylist())
    ]
    if len(set(episode_indices)) != 1:
        raise ValueError("synthetic table writer accepts exactly one episode trajectory")
    frame_indices = [
        _integer(value, column="frame_index", row=row)
        for row, value in enumerate(table["frame_index"].to_pylist())
    ]
    if frame_indices != list(range(bundle.frame_count)):
        raise ValueError("synthetic table frame_index must be contiguous from zero")

    timestamps = [
        _finite_float(value, column="timestamp", row=row)
        for row, value in enumerate(table["timestamp"].to_pylist())
    ]
    if any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
        raise ValueError("synthetic table timestamps must be strictly increasing")
    for row, (observed, expected) in enumerate(
        zip(timestamps, (frame.timestamp_s for frame in state.frames), strict=True)
    ):
        if not math.isclose(observed, expected, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(f"synthetic table timestamp does not match replay frame {row}")
    return source_columns


def _target_array(pa: Any, replay: TargetReplayTrajectory) -> Any:
    dimension = replay.layout.dimension
    values = [value for frame in replay.frames for value in frame.joint_positions]
    flat = pa.array(values, type=pa.float32())
    return pa.FixedSizeListArray.from_arrays(flat, dimension)


def _write_exclusive(parquet: Any, table: Any, output_path: Path) -> None:
    reserved = False
    try:
        with output_path.open("x+b") as handle:
            reserved = True
            parquet.write_table(table, handle)
    except Exception:
        if reserved:
            output_path.unlink(missing_ok=True)
        raise


def write_synthetic_target_table(
    *,
    source_path: Path,
    target_replay_bundle_path: Path,
    output_path: Path,
    preflight_path: Path | None = None,
) -> SyntheticTargetTableExport:
    """Rewrite one synthetic/public trajectory table with verified target vectors.

    This prototype intentionally writes a single Parquet table only. It does not
    copy videos, generate LeRobot metadata, or infer source semantics.
    """

    source_path = source_path.resolve()
    target_replay_bundle_path = target_replay_bundle_path.resolve()
    output_path = output_path.resolve()
    if source_path == output_path:
        raise ValueError("synthetic table source and output paths must be different")
    preflight_sha256: str | None = None
    preflight_path_string: str | None = None
    if preflight_path is not None:
        preflight_path = preflight_path.resolve()
        from retargetlab.run.export_table import verify_synthetic_table_write_preflight

        preflight_verification = verify_synthetic_table_write_preflight(preflight_path)
        preflight = SyntheticTableWritePreflight.model_validate_json(
            preflight_path.read_text(encoding="utf-8")
        )
        if Path(preflight.source_table_path).resolve() != source_path:
            raise ValueError("synthetic table preflight source path does not match writer input")
        if Path(preflight.target_replay_bundle_path).resolve() != target_replay_bundle_path:
            raise ValueError("synthetic table preflight bundle path does not match writer input")
        if Path(preflight.output_table_path).resolve() != output_path:
            raise ValueError("synthetic table preflight output path does not match writer input")
        preflight_sha256 = preflight_verification.preflight_sha256
        preflight_path_string = str(preflight_path)
    bundle, bundle_verification, state, action = _read_verified_bundle(
        target_replay_bundle_path
    )
    if state.stream_name != "observation.state" or action.stream_name != "action":
        raise ValueError("verified replay bundle must contain distinct state and action streams")
    if state.layout != bundle.layout or action.layout != bundle.layout:
        raise ValueError("replay artifact layout does not match the bundle")
    if len(state.frames) != bundle.frame_count or len(action.frames) != bundle.frame_count:
        raise ValueError("replay artifact frame counts do not match the bundle")

    pa, parquet = _load_pyarrow()
    if not source_path.is_file():
        raise FileNotFoundError(f"synthetic source table does not exist: {source_path}")
    table = parquet.read_table(source_path)
    source_columns = _validate_source_table(table, bundle, state)

    for column_name, replay in (("observation.state", state), ("action", action)):
        table = table.set_column(
            table.column_names.index(column_name),
            column_name,
            _target_array(pa, replay),
        )
    table = table.append_column(
        "valid.retarget",
        pa.array([True] * bundle.frame_count, type=pa.bool_()),
    )
    metadata = dict(table.schema.metadata or {})
    metadata.update(
        {
            b"retargetlab.artifact_type": b"synthetic_target_table",
            b"retargetlab.source_scope": b"synthetic_public_only",
            b"retargetlab.target_replay_bundle_sha256": bundle_verification.bundle_sha256.encode(
                "ascii"
            ),
            b"retargetlab.robot_id": bundle.robot_id.encode("utf-8"),
            b"retargetlab.replay_id": bundle.replay_id.encode("utf-8"),
        }
    )
    table = table.replace_schema_metadata(metadata)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_exclusive(parquet, table, output_path)
    output_columns = tuple(str(column) for column in table.column_names)
    return SyntheticTargetTableExport(
        source_table_path=str(source_path),
        output_table_path=str(output_path),
        target_replay_bundle_path=str(target_replay_bundle_path),
        target_replay_bundle_sha256=bundle_verification.bundle_sha256,
        preflight_path=preflight_path_string,
        preflight_sha256=preflight_sha256,
        replay_id=bundle.replay_id,
        robot_id=bundle.robot_id,
        frame_count=bundle.frame_count,
        layout=bundle.layout,
        source_columns=source_columns,
        output_columns=output_columns,
        preserved_columns=tuple(
            column for column in source_columns if column not in _REPLACED_COLUMNS
        ),
        valid_retarget_count=bundle.frame_count,
        output_table_sha256=sha256_file(output_path),
    )
