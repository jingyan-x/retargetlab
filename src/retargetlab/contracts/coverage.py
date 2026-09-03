"""Value-free coverage contracts for a bounded LeRobot dataset revision."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .profile import DatasetRevision


class EpisodeCoverage(BaseModel):
    """One episode's source-row interval from the episode metadata table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    episode_index: int = Field(ge=0)
    start_row: int = Field(ge=0)
    end_row_exclusive: int = Field(gt=0)
    length: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_interval(self) -> EpisodeCoverage:
        if self.end_row_exclusive - self.start_row != self.length:
            raise ValueError("episode coverage length does not match its row interval")
        return self


class DatasetCoverage(BaseModel):
    """Read-only structure and episode coverage summary for one dataset revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["dataset_coverage"] = "dataset_coverage"
    status: Literal["COMPLETE", "INCONSISTENT"]
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    storage_adapter: Literal["lerobot_v3"] = "lerobot_v3"
    reader_version: str = Field(min_length=1)
    revision: DatasetRevision
    declared_total_episodes: int = Field(gt=0)
    declared_total_frames: int = Field(gt=0)
    declared_total_tasks: int = Field(gt=0)
    declared_total_chunks: int = Field(gt=0)
    observed_episode_count: int = Field(ge=0)
    observed_frame_count: int = Field(ge=0)
    data_row_count: int = Field(gt=0)
    observed_task_count: int = Field(ge=0)
    episode_ranges: tuple[EpisodeCoverage, ...] = ()
    data_fields: tuple[str, ...] = Field(min_length=1)
    episode_fields: tuple[str, ...] = Field(min_length=1)
    task_fields: tuple[str, ...] = Field(min_length=1)
    declared_features: tuple[str, ...] = Field(min_length=1)
    stats_features: tuple[str, ...] = ()
    structure_compatible: bool
    structure_fully_verified: bool
    shape_unverified: tuple[str, ...] = ()
    shape_normalized: tuple[str, ...] = ()
    coverage_complete: bool
    validation_scope: str = Field(min_length=1)
    blocking_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_coverage_counts(self) -> DatasetCoverage:
        indices = tuple(item.episode_index for item in self.episode_ranges)
        if len(set(indices)) != len(indices):
            raise ValueError("episode coverage indices must be unique")
        if self.observed_episode_count != len(self.episode_ranges):
            raise ValueError("observed episode count must match episode ranges")
        if self.observed_frame_count != sum(item.length for item in self.episode_ranges):
            raise ValueError("observed frame count must match episode ranges")
        if self.coverage_complete != (self.status == "COMPLETE"):
            raise ValueError("coverage status and coverage_complete disagree")
        if self.status == "COMPLETE" and self.blocking_reasons:
            raise ValueError("complete coverage cannot contain blocking reasons")
        if self.status == "INCONSISTENT" and not self.blocking_reasons:
            raise ValueError("inconsistent coverage must record blocking reasons")
        return self
