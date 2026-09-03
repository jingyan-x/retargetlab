"""Read-only diagnostic report contracts."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from retargetlab.contracts.solve import IKStatus


class FrameDiagnostics(BaseModel):
    """Quality facts for one solved frame; it contains no joint values."""

    model_config = ConfigDict(extra="forbid")

    frame_index: int = Field(ge=0)
    solver_status: IKStatus
    position_error_m: float = Field(ge=0.0)
    orientation_error_rad: float = Field(ge=0.0)
    collision_free: bool | None
    joint_limit_violation: bool = False
    delta_violation: bool = False
    nominal: bool = False
    relaxed: bool = False

    @model_validator(mode="after")
    def validate_flags(self) -> FrameDiagnostics:
        if not math.isfinite(self.position_error_m) or not math.isfinite(
            self.orientation_error_rad
        ):
            raise ValueError("frame diagnostic errors must be finite")
        if self.nominal and not self.relaxed:
            raise ValueError("nominal frames must also satisfy the relaxed predicate")
        if (self.nominal or self.relaxed) and (
            self.collision_free is not True or self.joint_limit_violation or self.delta_violation
        ):
            raise ValueError("a colliding, invalid, or jumping frame cannot be reachable")
        return self


class EpisodeReport(BaseModel):
    """Aggregated episode result with explicit quality status."""

    model_config = ConfigDict(extra="forbid")

    episode_index: int = Field(ge=0)
    frame_count: int = Field(gt=0)
    nominal_rate: float = Field(ge=0.0, le=1.0)
    relaxed_rate: float = Field(ge=0.0, le=1.0)
    collision_fraction: float = Field(ge=0.0, le=1.0)
    joint_limit_violation_fraction: float = Field(ge=0.0, le=1.0)
    delta_violation_fraction: float = Field(ge=0.0, le=1.0)
    status: Literal["PASS", "WARN", "FAIL"]
    frames: tuple[FrameDiagnostics, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_frame_count(self) -> EpisodeReport:
        if self.frame_count != len(self.frames):
            raise ValueError("frame_count must match the number of frame diagnostics")
        return self


class DatasetReport(BaseModel):
    """Aggregated report for a set of episodes."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    episode_count: int = Field(gt=0)
    episodes: tuple[EpisodeReport, ...] = Field(min_length=1)
    status: Literal["PASS", "WARN", "FAIL"]

    @model_validator(mode="after")
    def validate_episode_count(self) -> DatasetReport:
        if self.episode_count != len(self.episodes):
            raise ValueError("episode_count must match the number of episode reports")
        return self
