"""Inspect review evidence without promoting or reading source rows."""

from __future__ import annotations

from typing import Literal

from retargetlab.contracts import (
    MappingReview,
    MappingSpec,
    ReviewPackageInspection,
    StructureComparison,
)


def inspect_review_package(
    candidate: MappingSpec,
    review: MappingReview,
    comparison: StructureComparison,
) -> ReviewPackageInspection:
    """Summarize review readiness without applying semantic decisions."""

    reasons: list[str] = []
    candidate_status = candidate.metadata.get("candidate_status", "MISSING")
    if candidate_status != "REVIEW_REQUIRED":
        reasons.append("candidate is not a review-only mapping")
    if candidate.dataset_alias != review.dataset_alias:
        reasons.append("review dataset alias does not match candidate")
    if candidate.source_revision != review.source_revision:
        reasons.append("review source revision does not match candidate")
    if not comparison.alias_match:
        reasons.append("structure comparison alias check failed")
    if not comparison.revision_match:
        reasons.append("structure comparison revision check failed")
    if not comparison.compatible:
        reasons.append("structure comparison is incompatible")
    shape_decision_required = bool(comparison.shape_unverified) and not (
        review.accept_unverified_shape
    )
    if review.approved and shape_decision_required:
        reasons.append("approved review does not accept unverified source shapes")

    if reasons:
        status: Literal["PENDING_REVIEW", "REVIEW_APPROVED", "BLOCKED"] = "BLOCKED"
        next_action: Literal["REVIEW_SEMANTICS", "APPLY_APPROVED_REVIEW", "REPAIR_EVIDENCE"] = (
            "REPAIR_EVIDENCE"
        )
        ready_for_semantic_review = False
        can_apply_review = False
    elif review.approved:
        status = "REVIEW_APPROVED"
        next_action = "APPLY_APPROVED_REVIEW"
        ready_for_semantic_review = False
        can_apply_review = True
    else:
        status = "PENDING_REVIEW"
        next_action = "REVIEW_SEMANTICS"
        ready_for_semantic_review = True
        can_apply_review = False

    return ReviewPackageInspection(
        status=status,
        next_action=next_action,
        dataset_alias=candidate.dataset_alias,
        source_revision=candidate.source_revision,
        candidate_status=candidate_status,
        review_approved=review.approved,
        structure_compatible=comparison.compatible,
        structure_fully_verified=comparison.fully_verified,
        shape_unverified=comparison.shape_unverified,
        shape_decision_required=shape_decision_required,
        ready_for_semantic_review=ready_for_semantic_review,
        can_apply_review=can_apply_review,
        review_evidence_count=len(review.evidence),
        blocking_reasons=tuple(reasons),
    )
