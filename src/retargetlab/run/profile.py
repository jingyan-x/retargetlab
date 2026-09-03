"""Persistence helpers for reviewable dataset profiles."""

from __future__ import annotations

import json
from pathlib import Path

from retargetlab.contracts import DataProfile, DataProfileVerification, ReviewDecisionArtifact
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes


def write_data_profile(path: Path, profile: DataProfile) -> DataProfile:
    """Write one exclusive value-free dataset profile."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(profile.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return profile


def verify_data_profile(
    path: Path,
    *,
    decision_path: Path | None = None,
) -> DataProfileVerification:
    """Verify a profile and, when supplied, its exact semantic decision binding."""

    profile = DataProfile.model_validate_json(path.read_text(encoding="utf-8"))
    profile_digest = sha256_bytes(canonical_json_bytes(profile))
    decision_digest: str | None = None
    decision_verified = False

    if decision_path is not None:
        if profile.review_decision_sha256 is None:
            raise ValueError("decision file supplied but profile has no decision hash")
        decision = ReviewDecisionArtifact.model_validate_json(
            decision_path.read_text(encoding="utf-8")
        )
        decision_digest = sha256_bytes(canonical_json_bytes(decision))
        if decision_digest != profile.review_decision_sha256:
            raise ValueError("decision file hash does not match data profile")
        if decision.dataset_alias != profile.dataset_alias:
            raise ValueError("decision dataset alias does not match data profile")
        if decision.source_revision != profile.source_revision:
            raise ValueError("decision source revision does not match data profile")
        mapping_digest = sha256_bytes(canonical_json_bytes(profile.mapping))
        if decision.approved_mapping_sha256 != mapping_digest:
            raise ValueError("decision approved mapping hash does not match data profile")
        if decision.coordinate_frame != profile.mapping.coordinate_frame:
            raise ValueError("decision coordinate frame does not match data profile")
        decision_verified = True
    elif profile.status == "CERTIFIED":
        raise ValueError("certified profile verification requires a decision file")

    return DataProfileVerification(
        profile_id=profile.profile_id,
        profile_status=profile.status,
        dataset_alias=profile.dataset_alias,
        source_revision=profile.source_revision,
        profile_sha256=profile_digest,
        decision_sha256=decision_digest or profile.review_decision_sha256,
        decision_verified=decision_verified,
    )
