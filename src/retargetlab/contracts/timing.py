"""Contracts for source-independent command timing checks."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TimingShiftResult(BaseModel):
    """Aggregate error for one action-to-state shift."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    shift: int = Field(ge=0)
    pair_count: int = Field(gt=0)
    rmse: float = Field(ge=0)
    per_joint_rmse: tuple[float, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_finite_metrics(self) -> TimingShiftResult:
        if not math.isfinite(self.rmse) or any(
            not math.isfinite(value) for value in self.per_joint_rmse
        ):
            raise ValueError("timing metrics must be finite")
        return self


class CommandTimingReport(BaseModel):
    """Value-free command timing ranking over an explicit episode subset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    status: Literal["SUPPORTED", "CONFLICTED"]
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    data_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    episode_indices: tuple[int, ...] = Field(min_length=1)
    episode_count: int = Field(gt=0)
    frame_count: int = Field(gt=0)
    joint_indices: tuple[int, ...] = Field(min_length=1)
    joint_count: int = Field(gt=0)
    action_scales: tuple[float, ...] = Field(min_length=1)
    action_offsets: tuple[float, ...] = Field(min_length=1)
    max_shift: int = Field(ge=0)
    expected_shift_min: int = Field(ge=0)
    expected_shift_max: int = Field(ge=0)
    best_shift: int = Field(ge=0)
    best_rmse: float = Field(ge=0)
    shifts: tuple[TimingShiftResult, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_report_lineage(self) -> CommandTimingReport:
        if len(set(self.episode_indices)) != len(self.episode_indices):
            raise ValueError("timing episode indices must be unique")
        if any(index < 0 for index in self.episode_indices):
            raise ValueError("timing episode indices must be non-negative")
        if len(set(self.joint_indices)) != len(self.joint_indices):
            raise ValueError("timing joint indices must be unique")
        if any(index < 0 for index in self.joint_indices):
            raise ValueError("timing joint indices must be non-negative")
        if self.joint_count != len(self.joint_indices):
            raise ValueError("timing joint count does not match joint indices")
        if len(self.action_scales) != self.joint_count:
            raise ValueError("timing action scales do not match joint count")
        if len(self.action_offsets) != self.joint_count:
            raise ValueError("timing action offsets do not match joint count")
        if any(not math.isfinite(value) or value == 0.0 for value in self.action_scales):
            raise ValueError("timing action scales must be finite and non-zero")
        if any(not math.isfinite(value) for value in self.action_offsets):
            raise ValueError("timing action offsets must be finite")
        if self.episode_count != len(self.episode_indices):
            raise ValueError("timing episode count does not match episode indices")
        if self.expected_shift_min > self.expected_shift_max:
            raise ValueError("expected timing shift range is reversed")
        if self.expected_shift_max > self.max_shift:
            raise ValueError("expected timing shift exceeds max_shift")
        shifts = tuple(item.shift for item in self.shifts)
        if shifts != tuple(range(self.max_shift + 1)):
            raise ValueError("timing shifts must cover every value from 0 to max_shift")
        if self.best_shift > self.max_shift:
            raise ValueError("best timing shift exceeds max_shift")
        best = next(item for item in self.shifts if item.shift == self.best_shift)
        if best.rmse != self.best_rmse:
            raise ValueError("best timing RMSE does not match shift results")
        if any(len(item.per_joint_rmse) != self.joint_count for item in self.shifts):
            raise ValueError("timing per-joint metrics do not match joint count")
        expected_status = (
            "SUPPORTED"
            if self.expected_shift_min <= self.best_shift <= self.expected_shift_max
            else "CONFLICTED"
        )
        if self.status != expected_status:
            raise ValueError("timing status does not match best shift and expected range")
        if not math.isfinite(self.best_rmse):
            raise ValueError("best timing RMSE must be finite")
        return self
