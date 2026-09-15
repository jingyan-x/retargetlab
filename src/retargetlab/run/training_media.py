"""Decode calibration videos and measure sampled RGB statistics for export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from retargetlab.run.training_export import _json, _sha


def audit_media(processing_run: Path, output: Path) -> dict:
    import av
    import pyarrow.parquet as pq
    import yaml

    config = json.loads((processing_run / "processing-config.json").read_text())
    binding = json.loads((processing_run / "input-binding.json").read_text())
    if config["source_format"] != "mq03_eef":
        raise ValueError("this media adapter requires the MQ03 calibration layout")
    split_path = Path(config["split"])
    if _sha(split_path) != binding["split_sha256"]:
        raise ValueError("calibration split changed")
    split = yaml.safe_load(split_path.read_text())
    episodes = binding["episode_indices"]
    if not set(episodes) <= set(split["calibration"]["episode_index"]) or set(episodes) & set(
        split["held_out"]["episode_index"]
    ):
        raise ValueError("media selection must be calibration-only")
    root = Path(config["dataset"])
    if _sha(root / "meta/info.json") != binding["metadata_sha256"]:
        raise ValueError("source metadata changed")
    info = json.loads((root / "meta/info.json").read_text())
    meta = pq.read_table(
        root / "meta/episodes", filters=[("episode_index", "in", episodes)]
    ).to_pylist()
    cameras = [k for k, v in info["features"].items() if v["dtype"] == "video"]
    report = {
        "status": "COMPLETED",
        "episode_indices": episodes,
        "held_out_read": False,
        "statistics_method": "32 uniform frames; RGB stride 16; scaled to [0,1]",
        "videos": {},
    }
    for row in meta:
        for camera in cameras:
            relative = info["video_path"].format(
                video_key=camera,
                chunk_index=row[f"videos/{camera}/chunk_index"],
                file_index=row[f"videos/{camera}/file_index"],
            )
            samples = set(
                np.linspace(0, row["length"] - 1, min(32, row["length"]), dtype=int).tolist()
            )
            minimum, maximum = np.ones(3), np.zeros(3)
            total, squares, pixels, count, max_time_error = np.zeros(3), np.zeros(3), 0, 0, 0.0
            with av.open(str(root / relative)) as container:
                for index, frame in enumerate(container.decode(video=0)):
                    count += 1
                    expected_time = row[f"videos/{camera}/from_timestamp"] + index / info["fps"]
                    max_time_error = max(max_time_error, abs(float(frame.time) - expected_time))
                    if index in samples:
                        rgb = frame.to_ndarray(format="rgb24")[::16, ::16].reshape(-1, 3) / 255.0
                        total += rgb.sum(axis=0)
                        squares += (rgb * rgb).sum(axis=0)
                        pixels += len(rgb)
                        minimum = np.minimum(minimum, rgb.min(axis=0))
                        maximum = np.maximum(maximum, rgb.max(axis=0))
            if count != row["length"] or max_time_error > 1 / info["fps"]:
                raise ValueError(f"video time axis mismatch: {relative}")
            mean = total / pixels
            stats = {
                "min": minimum,
                "max": maximum,
                "mean": mean,
                "std": np.sqrt(np.maximum(0, squares / pixels - mean * mean)),
            }
            stats = {k: v.reshape(3, 1, 1).tolist() for k, v in stats.items()}
            stats["count"] = [len(samples)]
            report["videos"][relative] = {
                "sha256": _sha(root / relative),
                "decoded_frames": count,
                "max_pts_error_s": max_time_error,
                "sampled_frames": sorted(samples),
                "stats": stats,
            }
            print(f"media audit: {len(report['videos'])}/{len(meta) * len(cameras)}", flush=True)
    if output.exists():
        raise FileExistsError(output)
    _json(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--processing-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit_media(args.processing_run, args.output)


if __name__ == "__main__":
    main()
