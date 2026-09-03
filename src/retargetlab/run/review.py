"""Persist bounded calibration audit artifacts without source rows."""

from __future__ import annotations

import json
from pathlib import Path

from retargetlab.contracts import (
    CalibrationReport,
    CalibrationSelection,
    MappingSpec,
    ReviewRunArtifact,
    StructureComparison,
)
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes


def write_review_run_artifact(
    path: Path,
    *,
    mapping: MappingSpec,
    comparison: StructureComparison,
    selection: CalibrationSelection,
    calibration: CalibrationReport,
) -> ReviewRunArtifact:
    """Write one exclusive audit JSON containing no trajectory arrays."""

    if mapping.metadata.get("candidate_status") != "APPROVED":
        raise ValueError("review artifact requires an approved mapping")
    if not comparison.compatible:
        raise ValueError("review artifact requires a compatible structure comparison")
    reviewer = mapping.metadata.get("reviewer")
    evidence_text = mapping.metadata.get("review_evidence")
    if not reviewer or not evidence_text:
        raise ValueError("approved mapping is missing reviewer or evidence metadata")
    artifact = ReviewRunArtifact(
        dataset_alias=mapping.dataset_alias,
        source_revision=mapping.source_revision,
        mapping_sha256=sha256_bytes(canonical_json_bytes(mapping)),
        comparison_sha256=sha256_bytes(canonical_json_bytes(comparison)),
        reviewer=reviewer,
        review_evidence=tuple(item for item in evidence_text.split(";") if item),
        coordinate_frame=mapping.coordinate_frame,
        selection=selection,
        calibration=calibration,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(artifact.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return artifact
