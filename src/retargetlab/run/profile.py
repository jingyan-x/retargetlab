"""Persistence helpers for reviewable dataset profiles."""

from __future__ import annotations

import json
from pathlib import Path

from retargetlab.contracts import DataProfile


def write_data_profile(path: Path, profile: DataProfile) -> DataProfile:
    """Write one exclusive value-free dataset profile."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(profile.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return profile
