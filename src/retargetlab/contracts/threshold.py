"""Thresholds with explicit source and validation scope."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Threshold(BaseModel):
    """One diagnostic threshold; values without provenance are invalid."""

    model_config = ConfigDict(extra="forbid")

    warn: float
    fail: float
    unit: str = Field(min_length=1)
    source: str = Field(min_length=1)
    provenance: str = Field(min_length=1)
    status: Literal["provisional", "sample_validated", "frozen"] = "provisional"
    calibrated_on: str | None = None
    validation_scope: str | None = None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_metadata(self) -> Threshold:
        if self.warn < 0 or self.fail < 0:
            raise ValueError("thresholds must be non-negative")
        if self.status in {"sample_validated", "frozen"}:
            if not self.calibrated_on or not self.validation_scope:
                raise ValueError(
                    "sample_validated and frozen thresholds require calibrated_on "
                    "and validation_scope"
                )
        if not self.source.strip() or not self.provenance.strip():
            raise ValueError("threshold source and provenance must not be blank")
        return self
