"""Target-side vector layout contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

JointUnit = Literal["rad", "m"]


class TargetVectorLayout(BaseModel):
    """Ordered target joint vector names and units for one exported row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    group_names: tuple[str, ...] = Field(min_length=1)
    names: tuple[str, ...] = Field(min_length=1)
    units: tuple[JointUnit, ...] = Field(min_length=1)
    dtype: Literal["float32"] = "float32"

    @model_validator(mode="after")
    def validate_layout(self) -> TargetVectorLayout:
        if len(self.names) != len(self.units):
            raise ValueError("target vector names and units must have the same length")
        if len(set(self.group_names)) != len(self.group_names):
            raise ValueError("target vector group names must be unique")
        if any(not name.strip() for name in self.group_names + self.names):
            raise ValueError("target vector names must not be blank")
        if len(set(self.names)) != len(self.names):
            raise ValueError("target vector joint names must be unique")
        return self

    @property
    def dimension(self) -> int:
        """Return the flattened target vector dimension."""

        return len(self.names)

    @property
    def shape(self) -> tuple[int]:
        """Return the one-dimensional shape used by the dataset feature."""

        return (self.dimension,)


class ExportProfile(BaseModel):
    """Stable target-side output semantics bound to one RobotProfile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    robot_id: str = Field(min_length=1)
    robot_profile_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    target_layout: TargetVectorLayout
    control_mode: Literal["position"] = "position"
    normalization_exclude: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_exclusions(self) -> ExportProfile:
        if len(set(self.normalization_exclude)) != len(self.normalization_exclude):
            raise ValueError("normalization exclusions must be unique")
        if any(not item.strip() for item in self.normalization_exclude):
            raise ValueError("normalization exclusions must not be blank")
        return self
