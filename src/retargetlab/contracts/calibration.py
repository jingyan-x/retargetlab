"""Bounded calibration execution contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
