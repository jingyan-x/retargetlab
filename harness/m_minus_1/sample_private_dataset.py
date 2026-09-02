"""Create the deterministic M-1.3 calibration sample manifest.

The sampler reads only dataset metadata plus calibration rows selected by the
frozen split.  It emits indices and structure, never private feature values or
source paths, so the result can be attached to an ignored run directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import yaml

SCHEMA = "m_minus_1.private_sample_sampling.v1"
REQUIRED_DATA_COLUMNS = (
    "episode_index",
    "frame_index",
    "timestamp",
    "observation.state",
    "action",
    "observation.state.position",
    "action.position",
    "control_mode",
)
REQUIRED_EPISODE_COLUMNS = (
    "episode_index",
    "length",
    "dataset_from_index",
    "dataset_to_index",
)
STATE_POSITION_SLICES = ((5, 8), (13, 16))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_splits(path: Path) -> dict[str, list[int]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    result: dict[str, list[int]] = {}
    for name in ("calibration", "held_out"):
        values = document.get(name, {}).get("episode_index")
        if not isinstance(values, list) or not all(isinstance(v, int) for v in values):
            raise ValueError(f"split {name}.episode_index must be a list of integers")
        result[name] = values
    if set(result["calibration"]) & set(result["held_out"]):
        raise ValueError("calibration and held_out episode indices overlap")
    return result


def schema_summary(schema: Any) -> list[dict[str, str]]:
    return [
        {"name": name, "type": str(schema.field(name).type)}
        for name in schema.names
    ]


def load_episode_metadata(path: Path) -> dict[int, dict[str, int]]:
    table = pq.read_table(path, columns=list(REQUIRED_EPISODE_COLUMNS))
    records: dict[int, dict[str, int]] = {}
    for row in table.to_pylist():
        episode = int(row["episode_index"])
        records[episode] = {
            key: int(row[key])
            for key in REQUIRED_EPISODE_COLUMNS
            if key != "episode_index"
        }
    return records


def read_calibration_rows(
    path: Path,
    calibration: list[int],
) -> dict[int, list[dict[str, Any]]]:
    table = pq.read_table(
        path,
        columns=["episode_index", "frame_index", "observation.state"],
        filters=[("episode_index", "in", calibration)],
    )
    rows: dict[int, list[dict[str, Any]]] = {episode: [] for episode in calibration}
    for row in table.to_pylist():
        episode = int(row["episode_index"])
        if episode not in rows:
            raise ValueError("filtered parquet rows include a held_out episode")
        rows[episode].append(row)
    for episode in calibration:
        rows[episode].sort(key=lambda row: int(row["frame_index"]))
    return rows


def extrema_frame_indices(rows: list[dict[str, Any]]) -> set[int]:
    selected: set[int] = set()
    for start, stop in STATE_POSITION_SLICES:
        for axis in range(start, stop):
            valid = [
                row
                for row in rows
                if row["observation.state"] is not None
                and len(row["observation.state"]) > axis
            ]
            if not valid:
                continue
            selected.add(
                min(valid, key=lambda row: float(row["observation.state"][axis]))[
                    "frame_index"
                ]
            )
            selected.add(
                max(valid, key=lambda row: float(row["observation.state"][axis]))[
                    "frame_index"
                ]
            )
    return {int(index) for index in selected}


def evenly_spaced_indices(length: int, count: int) -> set[int]:
    if length < count:
        raise ValueError(f"episode length {length} is shorter than sample count {count}")
    return {
        round(index * (length - 1) / (count - 1))
        for index in range(count)
    }


def single_frame_indices(
    episode: int,
    rows: list[dict[str, Any]],
    frames_per_episode: int,
) -> list[int]:
    length = len(rows)
    selected = {0, length - 1}
    selected.update(extrema_frame_indices(rows))
    if len(selected) > frames_per_episode:
        raise ValueError(
            f"episode {episode} has {len(selected)} mandatory frames, "
            f"more than the requested {frames_per_episode}"
        )
    for index in sorted(evenly_spaced_indices(length, frames_per_episode)):
        if len(selected) == frames_per_episode:
            break
        selected.add(index)
    if len(selected) != frames_per_episode:
        raise ValueError(
            f"episode {episode} produced {len(selected)} unique frames, "
            f"expected {frames_per_episode}"
        )
    return sorted(selected)


def continuous_segments(
    calibration: list[int],
    episode_lengths: dict[int, int],
    segment_count: int,
    segment_length: int,
) -> list[dict[str, int]]:
    segments: list[dict[str, int]] = []
    base, extra = divmod(segment_count, len(calibration))
    for order, episode in enumerate(calibration):
        count = base + (1 if order < extra else 0)
        max_start = episode_lengths[episode] - segment_length
        if max_start < 0:
            raise ValueError(f"episode {episode} is shorter than a segment")
        starts = (
            [max_start // 2]
            if count == 1
            else [
                round(index * max_start / (count - 1))
                for index in range(count)
            ]
        )
        for segment_order, start in enumerate(starts):
            segments.append(
                {
                    "segment_index": len(segments),
                    "episode_index": episode,
                    "segment_order_in_episode": segment_order,
                    "start_frame_index": int(start),
                    "end_frame_index": int(start + segment_length - 1),
                    "length": segment_length,
                }
            )
    if len(segments) != segment_count:
        raise AssertionError("deterministic segment allocation produced wrong count")
    return segments


def build_report(
    dataset_root: Path,
    splits_path: Path,
    frames_per_episode: int,
    segment_count: int,
    segment_length: int,
) -> dict[str, Any]:
    dataset_root = dataset_root.resolve()
    info_path = dataset_root / "meta" / "info.json"
    data_path = dataset_root / "data" / "chunk-000" / "file-000.parquet"
    episodes_path = dataset_root / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    info = json.loads(info_path.read_text(encoding="utf-8"))
    splits = read_splits(splits_path.resolve())
    calibration = splits["calibration"]

    data_file = pq.ParquetFile(data_path)
    episodes_file = pq.ParquetFile(episodes_path)
    missing_data = sorted(set(REQUIRED_DATA_COLUMNS) - set(data_file.schema_arrow.names))
    missing_episodes = sorted(
        set(REQUIRED_EPISODE_COLUMNS) - set(episodes_file.schema_arrow.names)
    )
    if missing_data or missing_episodes:
        raise ValueError(
            f"missing columns: data={missing_data}, episodes={missing_episodes}"
        )

    episode_metadata = load_episode_metadata(episodes_path)
    missing_calibration = sorted(set(calibration) - set(episode_metadata))
    if missing_calibration:
        raise ValueError(f"calibration episodes are missing metadata: {missing_calibration}")
    rows = read_calibration_rows(data_path, calibration)
    lengths = {episode: episode_metadata[episode]["length"] for episode in calibration}
    for episode in calibration:
        if len(rows[episode]) != lengths[episode]:
            raise ValueError(f"episode {episode} row count does not match metadata")
        expected = list(range(lengths[episode]))
        actual = [int(row["frame_index"]) for row in rows[episode]]
        if actual != expected:
            raise ValueError(f"episode {episode} frame indices are not contiguous")

    singles = {
        str(episode): {
            "episode_index": episode,
            "data_row_start": episode_metadata[episode]["dataset_from_index"],
            "data_row_end_exclusive": episode_metadata[episode]["dataset_to_index"],
            "frame_indices": single_frame_indices(
                episode, rows[episode], frames_per_episode
            ),
        }
        for episode in calibration
    }
    segments = continuous_segments(
        calibration,
        lengths,
        segment_count,
        segment_length,
    )
    return {
        "schema_version": SCHEMA,
        "status": "PASS",
        "dataset_alias": "private-sample-20",
        "source_paths_emitted": False,
        "held_out_values_read": False,
        "dataset": {
            "total_episodes": int(info["total_episodes"]),
            "total_frames": int(info["total_frames"]),
            "fps": float(info["fps"]),
            "data_rows": int(data_file.metadata.num_rows),
            "data_row_groups": int(data_file.metadata.num_row_groups),
            "episode_metadata_rows": int(episodes_file.metadata.num_rows),
            "calibration_episode_count": len(calibration),
            "calibration_frame_count": sum(lengths.values()),
            "data_sha256": sha256_file(data_path),
            "info_sha256": sha256_file(info_path),
            "episodes_sha256": sha256_file(episodes_path),
            "data_schema": schema_summary(data_file.schema_arrow),
            "episode_schema": schema_summary(episodes_file.schema_arrow),
        },
        "sampling": {
            "single_frames_per_episode": frames_per_episode,
            "single_frame_total": len(calibration) * frames_per_episode,
            "single_frame_selection": "uniform_grid_plus_endpoints_and_eef_axis_extrema",
            "continuous_segment_count": segment_count,
            "continuous_segment_length": segment_length,
            "continuous_segments": segments,
            "single_frames": singles,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--splits", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frames-per-episode", type=int, default=50)
    parser.add_argument("--segment-count", type=int, default=20)
    parser.add_argument("--segment-length", type=int, default=60)
    args = parser.parse_args()
    try:
        report = build_report(
            args.dataset_root,
            args.splits,
            args.frames_per_episode,
            args.segment_count,
            args.segment_length,
        )
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        report = {
            "schema_version": SCHEMA,
            "status": "ERROR",
            "source_paths_emitted": False,
            "failures": [f"sampling failed ({type(exc).__name__})"],
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
