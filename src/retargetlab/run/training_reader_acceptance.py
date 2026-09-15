"""Exercise the actual LeRobot loader and masked action windows offline."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path

import numpy as np

from retargetlab.run.training_dataset import MaskedLeRobotDataset


def verify_training_reader(root: Path, horizon: int = 16) -> dict:
    import pyarrow.parquet as pq
    import torch
    from torch.utils.data import DataLoader

    wrapped = MaskedLeRobotDataset(root, action_horizon=horizon)
    table = pq.read_table(
        root / "data",
        columns=[
            "episode_index",
            "frame_index",
            "observation.state",
            "action",
            "valid.retarget",
            "task_index",
        ],
    )
    data = table.to_pydict()
    info = json.loads((root / "meta/info.json").read_text())
    camera_shapes = {
        k: [v["shape"][2], *v["shape"][:2]]
        for k, v in info["features"].items()
        if v["dtype"] == "video"
    }
    tasks = {
        r["task_index"]: r["task"] for r in pq.read_table(root / "meta/tasks.parquet").to_pylist()
    }
    selected = []
    for ep in sorted(set(data["episode_index"])):
        positions = [i for i, row in enumerate(wrapped.indices) if data["episode_index"][row] == ep]
        if positions:
            selected.extend([positions[0], positions[len(positions) // 2], positions[-1]])
    checked, image_shapes = [], {}
    for position in sorted(set(selected)):
        index = wrapped.indices[position]
        item = wrapped[position]
        assert item["task"] == tasks[data["task_index"][index]]
        assert all(key in item for key in camera_shapes)
        state = item["observation.state"].cpu().numpy()
        action = item["action"].cpu().numpy()
        assert np.array_equal(state, np.asarray(data["observation.state"][index], dtype=np.float32))
        expected_actions = np.asarray(data["action"][index : index + horizon], dtype=np.float32)
        assert np.array_equal(action, expected_actions)
        assert len(set(data["episode_index"][index : index + horizon])) == 1
        assert all(v == 1 for v in data["valid.retarget"][index : index + horizon])
        assert (
            torch.isfinite(item["observation.state"]).all() and torch.isfinite(item["action"]).all()
        )
        if "action_is_pad" in item:
            assert not item["action_is_pad"].any()
        for key, value in item.items():
            if key.startswith("observation.images."):
                assert torch.isfinite(value).all() and value.ndim == 3 and value.shape[0] == 3
                assert list(value.shape) == camera_shapes[key]
                assert value.min() >= 0 and value.max() <= 1
                image_shapes[key] = list(value.shape)
        checked.append(
            {
                "episode_index": data["episode_index"][index],
                "frame_index": data["frame_index"][index],
                "export_index": index,
            }
        )
    batch = next(iter(DataLoader(wrapped, batch_size=2, num_workers=0, shuffle=False)))
    batch_size = min(2, len(wrapped))
    assert tuple(batch["observation.state"].shape) == (batch_size, 16)
    assert tuple(batch["action"].shape) == (batch_size, horizon, 16)
    stats = json.loads((root / "meta/stats.json").read_text())
    normalized_shapes = {}
    for key in ["observation.state", "action"]:
        mean = torch.tensor(stats[key]["mean"], dtype=batch[key].dtype)
        std = torch.tensor(stats[key]["std"], dtype=batch[key].dtype).clamp_min(1e-6)
        normalized = (batch[key] - mean) / std
        assert torch.isfinite(normalized).all()
        normalized_shapes[key] = list(normalized.shape)
    return {
        "status": "PASSED",
        "loader": "lerobot.datasets.lerobot_dataset.LeRobotDataset",
        "versions": {
            n: importlib.metadata.version(n)
            for n in ["lerobot", "torch", "torchvision", "datasets", "pyarrow", "av"]
        },
        "dataset_rows": len(table),
        "masked_training_windows": len(wrapped),
        "action_horizon": horizon,
        "checked_batch_size": batch_size,
        "episodes_with_checked_windows": len({r["episode_index"] for r in checked}),
        "checked_windows": checked,
        "image_shapes": image_shapes,
        "normalized_batch_shapes": normalized_shapes,
        "checks": [
            "source video files decoded offline",
            "state/action match exported Parquet values",
            "no window crosses an excluded row or episode boundary",
            "future actions contain no padding",
            "task text and image feature shapes match metadata",
            "DataLoader collation",
            "joint normalization batch is finite",
        ],
        "training_run_performed": False,
        "source_baseline_evidence": json.loads((root / "retarget/policy.json").read_text())[
            "baseline_evidence"
        ],
    }


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--horizon", type=int, default=16)
    args = parser.parse_args()
    report = verify_training_reader(args.dataset, args.horizon)
    with args.output.open("x") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
