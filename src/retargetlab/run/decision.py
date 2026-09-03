"""Persist explicit semantic review decisions without source values."""

from __future__ import annotations

import json
from pathlib import Path

from retargetlab.contracts import (
    MappingReview,
    MappingSpec,
    ReviewDecisionArtifact,
    StructureComparison,
)
from retargetlab.io.review import apply_mapping_review
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes


def write_review_decision_artifact(
    path: Path,
    *,
    candidate: MappingSpec,
    review: MappingReview,
    comparison: StructureComparison,
) -> ReviewDecisionArtifact:
    """Write one exclusive record for an explicitly approved mapping review."""

    approved = apply_mapping_review(candidate, review, comparison)
    checklist = review.checklist
    if checklist is None or checklist.shape_acceptance == "REJECTED":
        raise ValueError("approved review is missing an accepted evidence checklist")
    artifact = ReviewDecisionArtifact(
        dataset_alias=candidate.dataset_alias,
        source_revision=candidate.source_revision,
        candidate_sha256=sha256_bytes(canonical_json_bytes(candidate)),
        review_sha256=sha256_bytes(canonical_json_bytes(review)),
        checklist_sha256=sha256_bytes(canonical_json_bytes(checklist)),
        comparison_sha256=sha256_bytes(canonical_json_bytes(comparison)),
        approved_mapping_sha256=sha256_bytes(canonical_json_bytes(approved)),
        reviewer=review.reviewer,
        review_evidence=review.evidence,
        coordinate_frame=review.coordinate_frame,
        shape_acceptance=checklist.shape_acceptance,
        target_group_by_slot=dict(review.target_group_by_slot),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(artifact.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return artifact
