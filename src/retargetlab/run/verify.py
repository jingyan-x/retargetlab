"""Read-only verification for bounded calibration artifact sets."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from retargetlab.contracts import (
    CalibrationRecipe,
    CalibrationRunManifest,
    CalibrationRunVerification,
    ReviewRunArtifact,
)
from retargetlab.run.calibration_report import render_calibration_summary
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes

_RECIPE_NAME = "calibration-recipe.json"
_RECIPE_HASH_NAME = "calibration-recipe.sha256"
_SUMMARY_NAME = "calibration-summary.md"
_MANIFEST_NAME = "calibration-run-manifest.json"
_FIXED_NAMES = frozenset({_RECIPE_NAME, _RECIPE_HASH_NAME, _SUMMARY_NAME, _MANIFEST_NAME})


def _read_json_model[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def _require_artifact_names(run_path: Path, names: tuple[str, ...]) -> Path:
    if len(names) != 5 or len(set(names)) != len(names):
        raise ValueError("calibration manifest must list exactly five unique artifacts")
    for name in names:
        candidate = Path(name)
        if not name or candidate.is_absolute() or candidate.name != name:
            raise ValueError(f"calibration manifest contains an unsafe artifact name: {name}")
        if not (run_path / name).is_file():
            raise FileNotFoundError(f"calibration artifact is missing: {run_path / name}")
    audit_names = tuple(name for name in names if name not in _FIXED_NAMES)
    if len(audit_names) != 1:
        raise ValueError("calibration manifest must list one audit artifact")
    return run_path / audit_names[0]


def verify_calibration_run(run_path: Path) -> CalibrationRunVerification:
    """Verify a bounded calibration artifact set without reading source data."""

    if not run_path.is_dir():
        raise FileNotFoundError(f"calibration run directory does not exist: {run_path}")
    manifest_path = run_path / _MANIFEST_NAME
    manifest = _read_json_model(manifest_path, CalibrationRunManifest)
    audit_path = _require_artifact_names(run_path, manifest.artifacts)

    recipe_path = run_path / _RECIPE_NAME
    recipe = _read_json_model(recipe_path, CalibrationRecipe)
    recipe_digest = sha256_bytes(canonical_json_bytes(recipe))
    sidecar_tokens = (run_path / _RECIPE_HASH_NAME).read_text(encoding="utf-8").split()
    if sidecar_tokens != [recipe_digest]:
        raise ValueError("calibration recipe sidecar does not match canonical recipe hash")
    if manifest.recipe_sha256 != recipe_digest:
        raise ValueError("calibration manifest recipe hash does not match recipe")

    audit = _read_json_model(audit_path, ReviewRunArtifact)
    audit_digest = sha256_bytes(canonical_json_bytes(audit))
    if manifest.audit_sha256 != audit_digest:
        raise ValueError("calibration manifest audit hash does not match audit artifact")
    if manifest.run_id != audit_path.stem:
        raise ValueError("calibration manifest run id does not match audit artifact")

    if audit.dataset_alias != recipe.dataset_alias:
        raise ValueError("audit dataset alias does not match recipe")
    if audit.source_revision != recipe.source_revision:
        raise ValueError("audit source revision does not match recipe")
    if audit.mapping_sha256 != recipe.mapping_sha256:
        raise ValueError("audit mapping hash does not match recipe")
    if audit.comparison_sha256 != recipe.comparison_sha256:
        raise ValueError("audit comparison hash does not match recipe")
    if audit.review_sha256 != recipe.review_sha256:
        raise ValueError("audit review hash does not match recipe")
    if audit.selection.data_sha256 != recipe.data_sha256:
        raise ValueError("audit data hash does not match recipe")
    if audit.selection.episodes_sha256 != recipe.episodes_sha256:
        raise ValueError("audit episode hash does not match recipe")
    if audit.selection.frames_per_episode != recipe.frames_per_episode:
        raise ValueError("audit frame count does not match recipe")
    selected_episodes = tuple(item.episode_index for item in audit.selection.episode_ranges)
    if selected_episodes != recipe.episode_indices:
        raise ValueError("audit episode selection does not match recipe")
    if audit.calibration.max_frames != recipe.max_frames:
        raise ValueError("audit max_frames does not match recipe")
    if audit.selection.selected_frame_count > recipe.max_frames:
        raise ValueError("audit selection exceeds recipe max_frames")
    summary_path = run_path / _SUMMARY_NAME
    expected_summary = render_calibration_summary(
        recipe,
        audit,
        recipe_sha256=recipe_digest,
        audit_sha256=audit_digest,
    )
    summary = summary_path.read_text(encoding="utf-8")
    summary_digest = sha256_bytes(summary.encode("utf-8"))
    if manifest.summary_sha256 != summary_digest:
        raise ValueError("calibration manifest summary hash does not match summary")
    if summary != expected_summary:
        raise ValueError("calibration summary does not match recipe and audit")

    return CalibrationRunVerification(
        run_id=manifest.run_id,
        dataset_alias=recipe.dataset_alias,
        source_revision=recipe.source_revision,
        selected_frame_count=audit.selection.selected_frame_count,
        recipe_sha256=recipe_digest,
        decision_sha256=recipe.decision_sha256,
        audit_sha256=audit_digest,
        summary_sha256=summary_digest,
        artifacts=manifest.artifacts,
    )
