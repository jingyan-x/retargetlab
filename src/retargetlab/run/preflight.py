"""Persist read-only review-package preflight records."""

from __future__ import annotations

import json
from pathlib import Path

from retargetlab.contracts import (
    MappingReview,
    MappingSpec,
    ReviewPackagePreflightArtifact,
    ReviewPackagePreflightVerification,
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


def verify_review_package_preflight(
    preflight_path: Path,
    *,
    candidate_path: Path,
    review_path: Path,
    comparison_path: Path,
) -> ReviewPackagePreflightVerification:
    """Verify a saved preflight against its review-package inputs."""

    preflight = ReviewPackagePreflightArtifact.model_validate_json(
        preflight_path.read_text(encoding="utf-8")
    )
    candidate_raw = json.loads(candidate_path.read_text(encoding="utf-8"))
    if not isinstance(candidate_raw, dict):
        raise ValueError("mapping candidate must contain a JSON object")
    candidate = MappingSpec.model_validate(candidate_raw.get("mapping", candidate_raw))
    review = MappingReview.model_validate_json(review_path.read_text(encoding="utf-8"))
    comparison_raw = json.loads(comparison_path.read_text(encoding="utf-8"))
    if not isinstance(comparison_raw, dict):
        raise ValueError("structure comparison must contain a JSON object")
    comparison = StructureComparison.model_validate(
        comparison_raw.get("comparison", comparison_raw)
    )

    candidate_sha256 = sha256_bytes(canonical_json_bytes(candidate))
    review_sha256 = sha256_bytes(canonical_json_bytes(review))
    comparison_sha256 = sha256_bytes(canonical_json_bytes(comparison))
    if preflight.candidate_sha256 != candidate_sha256:
        raise ValueError("preflight candidate hash does not match candidate")
    if preflight.review_sha256 != review_sha256:
        raise ValueError("preflight review hash does not match review")
    if preflight.comparison_sha256 != comparison_sha256:
        raise ValueError("preflight comparison hash does not match comparison")
    if preflight.dataset_alias != candidate.dataset_alias:
        raise ValueError("preflight dataset alias does not match candidate")
    if preflight.source_revision != candidate.source_revision:
        raise ValueError("preflight source revision does not match candidate")
    expected_inspection = inspect_review_package(candidate, review, comparison)
    if preflight.inspection != expected_inspection:
        raise ValueError("preflight inspection does not match review package")

    return ReviewPackagePreflightVerification(
        dataset_alias=candidate.dataset_alias,
        source_revision=candidate.source_revision,
        preflight_sha256=sha256_bytes(canonical_json_bytes(preflight)),
        candidate_sha256=candidate_sha256,
        review_sha256=review_sha256,
        comparison_sha256=comparison_sha256,
        inspection_status=expected_inspection.status,
        can_apply_review=expected_inspection.can_apply_review,
    )
