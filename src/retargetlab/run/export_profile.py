"""Exclusive persistence for target-side export profiles."""

from __future__ import annotations

import json
from pathlib import Path

from retargetlab.contracts import ExportProfile


def write_export_profile(path: Path, profile: ExportProfile) -> ExportProfile:
    """Write one immutable export profile without overwriting an artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(profile.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return profile
