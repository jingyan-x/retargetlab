"""Persist bounded calibration audit artifacts without source rows."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from retargetlab.contracts import (
    CalibrationRecipe,
    CalibrationReport,
    CalibrationRunManifest,
    CalibrationSelection,
    MappingSpec,
    ReviewRunArtifact,
    StructureComparison,
)
from retargetlab.run.calibration_report import render_calibration_summary
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes


def _build_review_artifact(
    *,
    mapping: MappingSpec,
    comparison: StructureComparison,
    review_sha256: str,
    selection: CalibrationSelection,
    calibration: CalibrationReport,
) -> ReviewRunArtifact:
    """Build one value-free audit record for a bounded calibration."""

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
        review_sha256=review_sha256,
        reviewer=reviewer,
        review_evidence=tuple(item for item in evidence_text.split(";") if item),
        coordinate_frame=mapping.coordinate_frame,
        selection=selection,
        calibration=calibration,
    )
    return artifact


def write_review_run_artifact(
    path: Path,
    *,
    mapping: MappingSpec,
    comparison: StructureComparison,
    review_sha256: str,
    selection: CalibrationSelection,
    calibration: CalibrationReport,
) -> ReviewRunArtifact:
    """Write one exclusive audit JSON containing no trajectory arrays."""

    artifact = _build_review_artifact(
        mapping=mapping,
        comparison=comparison,
        review_sha256=review_sha256,
        selection=selection,
        calibration=calibration,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(artifact.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return artifact


def write_calibration_run(
    output_path: Path,
    *,
    recipe: CalibrationRecipe,
    mapping: MappingSpec,
    comparison: StructureComparison,
    review_sha256: str,
    selection: CalibrationSelection,
    calibration: CalibrationReport,
    decision_sha256: str | None = None,
    profile_sha256: str | None = None,
) -> CalibrationRunManifest:
    """Write recipe, audit, and completion manifest without source rows."""

    if recipe.dataset_alias != mapping.dataset_alias:
        raise ValueError("calibration recipe dataset alias does not match mapping")
    if recipe.source_revision != mapping.source_revision:
        raise ValueError("calibration recipe source revision does not match mapping")
    if recipe.data_sha256 != selection.data_sha256:
        raise ValueError("calibration recipe data hash does not match selection")
    if recipe.episodes_sha256 != selection.episodes_sha256:
        raise ValueError("calibration recipe episode hash does not match selection")
    mapping_sha256 = sha256_bytes(canonical_json_bytes(mapping))
    if recipe.mapping_sha256 != mapping_sha256:
        raise ValueError("calibration recipe mapping hash does not match mapping")
    comparison_sha256 = sha256_bytes(canonical_json_bytes(comparison))
    if recipe.comparison_sha256 != comparison_sha256:
        raise ValueError("calibration recipe comparison hash does not match comparison")
    if recipe.review_sha256 != review_sha256:
        raise ValueError("calibration recipe review hash does not match review")
    if recipe.decision_sha256 != decision_sha256:
        raise ValueError("calibration recipe decision hash does not match decision")
    if recipe.profile_sha256 != profile_sha256:
        raise ValueError("calibration recipe profile hash does not match profile")
    if recipe.frames_per_episode != selection.frames_per_episode:
        raise ValueError("calibration recipe frame count does not match selection")
    selected_episodes = tuple(item.episode_index for item in selection.episode_ranges)
    if recipe.episode_indices != selected_episodes:
        raise ValueError("calibration recipe episodes do not match selection")
    if recipe.max_frames < selection.selected_frame_count:
        raise ValueError("calibration recipe max_frames is below selection count")
    if calibration.max_frames != recipe.max_frames:
        raise ValueError("calibration report max_frames does not match recipe")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    recipe_path = output_path.with_name("calibration-recipe.json")
    recipe_hash_path = output_path.with_name("calibration-recipe.sha256")
    summary_path = output_path.with_name("calibration-summary.md")
    manifest_path = output_path.with_name("calibration-run-manifest.json")
    reserved_names = {
        recipe_path.name,
        recipe_hash_path.name,
        summary_path.name,
        manifest_path.name,
    }
    if output_path.name in reserved_names:
        raise ValueError("calibration audit output name is reserved")
    for path in (output_path, recipe_path, recipe_hash_path, summary_path, manifest_path):
        if path.exists():
            raise FileExistsError(f"calibration artifact already exists: {path}")

    artifact = _build_review_artifact(
        mapping=mapping,
        comparison=comparison,
        review_sha256=review_sha256,
        selection=selection,
        calibration=calibration,
    )
    with output_path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(artifact.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    recipe_digest = sha256_bytes(canonical_json_bytes(recipe))
    with recipe_path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(recipe.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    with recipe_hash_path.open("x", encoding="utf-8", newline="") as handle:
        handle.write(f"{recipe_digest}\n")
    audit_digest = sha256_bytes(canonical_json_bytes(artifact))
    summary = render_calibration_summary(
        recipe,
        artifact,
        recipe_sha256=recipe_digest,
        audit_sha256=audit_digest,
    )
    with summary_path.open("x", encoding="utf-8", newline="") as handle:
        handle.write(summary)
    summary_digest = sha256_bytes(summary.encode("utf-8"))
    manifest = CalibrationRunManifest(
        run_id=output_path.stem,
        recipe_sha256=recipe_digest,
        audit_sha256=audit_digest,
        summary_sha256=summary_digest,
        artifacts=(
            output_path.name,
            recipe_path.name,
            recipe_hash_path.name,
            summary_path.name,
            manifest_path.name,
        ),
        completed_at_utc=datetime.now(UTC).isoformat(),
    )
    with manifest_path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(manifest.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return manifest
