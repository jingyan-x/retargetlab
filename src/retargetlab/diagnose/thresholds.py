"""Diagnostic thresholds with visible provenance."""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field

from retargetlab.contracts.threshold import Threshold


class ThresholdSet(BaseModel):
    """M0 diagnostic thresholds; values are not silently inferred."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    position_nominal_m: Threshold
    orientation_nominal_rad: Threshold
    orientation_relaxed_rad: Threshold
    max_joint_delta_ratio: float = Field(default=1.0, gt=0.0)


def _threshold(value: float, unit: str, source: str) -> Threshold:
    return Threshold(
        warn=value,
        fail=value,
        unit=unit,
        source=source,
        provenance="M0 feasibility definition; not a product accuracy guarantee",
    )


def default_m0_thresholds() -> ThresholdSet:
    """Return the pre-registered M-1/M0 feasibility thresholds."""

    source = "engineering-plan-v1 §9.4"
    return ThresholdSet(
        position_nominal_m=_threshold(0.005, "m", source),
        orientation_nominal_rad=_threshold(math.radians(2.0), "rad", source),
        orientation_relaxed_rad=_threshold(math.radians(5.0), "rad", source),
    )
