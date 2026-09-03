"""Persist read-only review-package preflight records."""

from __future__ import annotations

import json
from pathlib import Path

from retargetlab.contracts import (
    MappingReview,
    MappingSpec,
    ReviewPackagePreflightArtifact,
    StructureComparison,
)
from retargetlab.io.review_package import inspect_review_package
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes


def write_review_package_preflight(
    path: Path,
    *,
    candidate: MappingSpec,
    review: MappingReview,
    comparison: StructureComparison,
) -> ReviewPackagePreflightArtifact:
    """Write one exclusive preflight record without source rows."""

    inspection = inspect_review_package(candidate, review, comparison)
    artifact = ReviewPackagePreflightArtifact(
        dataset_alias=candidate.dataset_alias,
        source_revision=candidate.source_revision,
        candidate_sha256=sha256_bytes(canonical_json_bytes(candidate)),
        review_sha256=sha256_bytes(canonical_json_bytes(review)),
        comparison_sha256=sha256_bytes(canonical_json_bytes(comparison)),
        inspection=inspection,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(artifact.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return artifact
