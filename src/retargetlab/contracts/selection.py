"""Bounded source-row selection contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EpisodeRange(BaseModel):
    """Metadata-only global row range for one episode."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    episode_index: int = Field(ge=0)
    start_row: int = Field(ge=0)
    end_row_exclusive: int = Field(gt=0)
    length: int = Field(gt=0)

    @property
    def stop_row(self) -> int:
        return self.end_row_exclusive

    def model_post_init(self, __context: object) -> None:
        if self.end_row_exclusive <= self.start_row:
            raise ValueError("episode row range must be non-empty")
        if self.end_row_exclusive - self.start_row != self.length:
            raise ValueError("episode row range length does not match endpoints")


class CalibrationSelection(BaseModel):
    """Value-free provenance for a bounded row selection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    data_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    episodes_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    frames_per_episode: int = Field(gt=0, le=60)
    episode_ranges: tuple[EpisodeRange, ...] = Field(min_length=1)
    selected_row_indices: tuple[int, ...] = Field(min_length=1)
    selected_frame_count: int = Field(gt=0, le=60)
