"""A LeRobot reader which selects only intact eligible action windows."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def valid_window_indices(episodes, frames, valid, horizon: int) -> list[int]:
    """Return row anchors without crossing an episode, frame gap or failed row."""
    if not isinstance(horizon, int) or horizon < 1:
        raise ValueError("action horizon must be a positive integer")
    episodes = np.asarray(episodes)
    frames = np.asarray(frames)
    valid = np.asarray(valid, dtype=bool)
    if episodes.ndim != 1 or frames.shape != episodes.shape or valid.shape != episodes.shape:
        raise ValueError("episode, frame and mask arrays must have equal one-dimensional shape")
    boundaries = np.r_[
        0,
        np.flatnonzero((episodes[1:] != episodes[:-1]) | (frames[1:] != frames[:-1] + 1)) + 1,
        len(valid),
    ]
    selected = []
    for start, stop in zip(boundaries[:-1], boundaries[1:], strict=True):
        if stop - start < horizon:
            continue
        bad = np.r_[0, np.cumsum(~valid[start:stop])]
        accepted = np.flatnonzero(bad[horizon:] - bad[:-horizon] == 0)
        selected.extend((accepted + start).tolist())
    return selected


class MaskedLeRobotDataset:
    """Map-style PyTorch dataset backed by the actual optional LeRobot loader.

    Source rows stay present in the export. Only anchors whose entire future
    action window passes the paired quality mask are offered to training.
    """

    def __init__(self, root: Path, action_horizon: int = 16):
        import pyarrow.parquet as pq
        from lerobot.datasets.lerobot_dataset import LeRobotDataset

        root = Path(root)
        info = json.loads((root / "meta/info.json").read_text())
        reader = json.loads((root / "retarget/reader-config.json").read_text())
        table = pq.read_table(
            root / "data", columns=["index", "episode_index", "frame_index", "valid.retarget"]
        )
        rows = table.to_pydict()
        if rows["index"] != list(range(len(table))):
            raise ValueError("training export must be ordered by contiguous global index")
        raw_mask = np.asarray(rows["valid.retarget"]).reshape(-1)
        if not np.isin(raw_mask, [0, 1]).all():
            raise ValueError("training eligibility mask must contain only zero or one")
        valid = raw_mask.astype(bool)
        self.indices = valid_window_indices(
            rows["episode_index"], rows["frame_index"], valid, action_horizon
        )
        if not self.indices:
            raise ValueError("no intact eligible training window for the requested horizon")
        self.dataset = LeRobotDataset(
            repo_id=reader["repo_id"],
            root=root,
            download_videos=False,
            video_backend=reader["video_backend"],
            delta_timestamps={"action": [i / info["fps"] for i in range(action_horizon)]},
        )
        self.action_horizon = action_horizon

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, index):
        return self.dataset[self.indices[index]]
