"""Render source-independent bounded calibration summaries."""

from __future__ import annotations

from retargetlab.contracts import CalibrationRecipe, ReviewRunArtifact


def render_calibration_summary(
    recipe: CalibrationRecipe,
    audit: ReviewRunArtifact,
    *,
    recipe_sha256: str,
    audit_sha256: str,
) -> str:
    """Render a deterministic Markdown summary containing no source rows."""

    episode_indices = ", ".join(str(index) for index in recipe.episode_indices)
    columns = ", ".join(f"`{column}`" for column in recipe.columns)
    streams = ", ".join(f"`{name}`" for name in audit.calibration.stream_names)
    lines = [
        "# RetargetLab calibration summary",
        "",
        f"- status: `{audit.calibration.status}`",
        f"- dataset_alias: `{recipe.dataset_alias}`",
        f"- source_revision: `{recipe.source_revision}`",
        f"- recipe_id: `{recipe.recipe_id}`",
        "",
        "## Provenance",
        "",
        f"- recipe_sha256: `{recipe_sha256}`",
        f"- audit_sha256: `{audit_sha256}`",
        f"- mapping_sha256: `{recipe.mapping_sha256}`",
        f"- comparison_sha256: `{recipe.comparison_sha256}`",
        f"- review_sha256: `{recipe.review_sha256}`",
        "",
        "## Selection",
        "",
        f"- episode_indices: `{episode_indices}`",
        f"- frames_per_episode: `{recipe.frames_per_episode}`",
        f"- selected_frame_count: `{audit.selection.selected_frame_count}`",
        f"- max_frames: `{recipe.max_frames}`",
        f"- columns: {columns}",
        "",
        "## Calibration",
        "",
        f"- coordinate_frame: `{audit.coordinate_frame}`",
        f"- streams: {streams}",
        f"- structure_status: `{audit.calibration.structure_status}`",
        f"- reviewer: `{audit.reviewer}`",
        "",
        "This summary contains provenance and quality metadata only; source rows "
        "and trajectory arrays are not embedded.",
        "",
    ]
    return "\n".join(lines)
