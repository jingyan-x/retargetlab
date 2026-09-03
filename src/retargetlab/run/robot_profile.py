"""Persistence helpers for versioned target robot profiles."""

from __future__ import annotations

import json
from pathlib import Path

from retargetlab.contracts import RobotProfile


def write_robot_profile(path: Path, profile: RobotProfile) -> RobotProfile:
    """Write one exclusive target robot profile artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(profile.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return profile
