"""Persistence helpers for value-free dataset coverage artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from retargetlab.contracts import DatasetCoverage


def write_dataset_coverage(path: Path, coverage: DatasetCoverage) -> DatasetCoverage:
    """Write one exclusive value-free coverage artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(coverage.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return coverage
