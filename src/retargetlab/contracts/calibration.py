"""Bounded calibration execution contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .selection import CalibrationSelection


class CalibrationReport(BaseModel):
    """Value-free completion report for a bounded normalization slice."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    status: Literal["COMPLETED"] = "COMPLETED"
    frame_count: int = Field(gt=0)
    max_frames: int = Field(gt=0, le=600)
    stream_names: tuple[str, ...] = Field(min_length=1)
    mapping_status: Literal["APPROVED"] = "APPROVED"
    structure_status: Literal["FULLY_VERIFIED", "COMPATIBLE_UNVERIFIED"]


class CalibrationRecipe(BaseModel):
    """Reproducible inputs for one bounded calibration run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    recipe_id: str = Field(min_length=1)
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    data_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    episodes_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    mapping_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    comparison_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    review_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    decision_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    profile_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    episode_indices: tuple[int, ...] = Field(min_length=1)
    frames_per_episode: int = Field(gt=0, le=60)
    max_frames: int = Field(gt=0, le=60)
    columns: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_selection_budget(self) -> CalibrationRecipe:
        if any(index < 0 for index in self.episode_indices):
            raise ValueError("episode indices must be non-negative")
        if len(set(self.episode_indices)) != len(self.episode_indices):
            raise ValueError("episode indices must be unique")
        if len(self.episode_indices) * self.frames_per_episode > self.max_frames:
            raise ValueError("calibration recipe exceeds max_frames")
        return self


class CalibrationRunManifest(BaseModel):
    """Completion record for a bounded calibration artifact set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    run_id: str = Field(min_length=1)
    status: Literal["COMPLETED"] = "COMPLETED"
    recipe_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    audit_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    summary_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    artifacts: tuple[str, ...] = Field(min_length=1)
    completed_at_utc: str = Field(min_length=1)


class CalibrationRunVerification(BaseModel):
    """Value-free result of verifying one bounded calibration artifact set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    status: Literal["VERIFIED"] = "VERIFIED"
    run_id: str = Field(min_length=1)
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    selected_frame_count: int = Field(gt=0)
    recipe_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    decision_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    profile_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    decision_verified: bool = False
    audit_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    summary_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    artifacts: tuple[str, ...] = Field(min_length=1)


class ReviewRunArtifact(BaseModel):
    """Audit record for one bounded calibration without source rows."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["bounded_calibration"] = "bounded_calibration"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    mapping_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    comparison_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    review_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    reviewer: str = Field(min_length=1)
    review_evidence: tuple[str, ...] = Field(min_length=1)
    coordinate_frame: str = Field(min_length=1)
    selection: CalibrationSelection
    calibration: CalibrationReport

    @model_validator(mode="after")
    def validate_lineage(self) -> ReviewRunArtifact:
        if self.selection.dataset_alias != self.dataset_alias:
            raise ValueError("selection dataset alias does not match artifact")
        if self.selection.source_revision != self.source_revision:
            raise ValueError("selection source revision does not match artifact")
        if self.calibration.frame_count != self.selection.selected_frame_count:
            raise ValueError("calibration count does not match selection")
        return self
