"""Canonical trajectory v0.1 contracts."""

from __future__ import annotations

import math
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Pose(BaseModel):
    """A rigid pose with an explicit frame and quaternion order."""

    model_config = ConfigDict(extra="forbid")

    QUATERNION_ORDER: ClassVar[str] = "wxyz"

    position_m: tuple[float, float, float]
    quaternion_wxyz: tuple[float, float, float, float]
    frame: str = Field(default="dataset_native", min_length=1)

    @field_validator("position_m", "quaternion_wxyz")
    @classmethod
    def validate_finite(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if not all(math.isfinite(component) for component in value):
            raise ValueError("pose values must be finite")
        return value

    @field_validator("quaternion_wxyz")
    @classmethod
    def validate_quaternion_norm(
        cls, value: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        norm = math.sqrt(sum(component * component for component in value))
        if norm < 1e-12 or abs(norm - 1.0) > 1e-3:
            raise ValueError("quaternion_wxyz must be normalized within 1e-3")
        return value


class CanonicalFrame(BaseModel):
    """One timestamp and one pose per named stream."""

    model_config = ConfigDict(extra="forbid")

    timestamp_s: float = Field(ge=0.0)
    poses: dict[str, Pose] = Field(min_length=1)
    grippers: dict[str, float] = Field(default_factory=dict)

    @field_validator("timestamp_s")
    @classmethod
    def validate_timestamp(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("timestamp_s must be finite")
        return value

    @field_validator("poses")
    @classmethod
    def validate_stream_names(cls, value: dict[str, Pose]) -> dict[str, Pose]:
        if any(not name.strip() for name in value):
            raise ValueError("stream names must not be blank")
        return value

    @field_validator("grippers")
    @classmethod
    def validate_grippers(cls, value: dict[str, float]) -> dict[str, float]:
        for name, aperture in value.items():
            if not name.strip():
                raise ValueError("gripper stream names must not be blank")
            if not math.isfinite(aperture) or not 0.0 <= aperture <= 1.0:
                raise ValueError("gripper apertures must be finite values in [0, 1]")
        return value


class CanonicalTrajectory(BaseModel):
    """CanonicalTrajectory v0.1: synchronized, frame-explicit pose streams."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    coordinate_frame: str = Field(default="dataset_native", min_length=1)
    frames: list[CanonicalFrame] = Field(min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_alignment(self) -> CanonicalTrajectory:
        first_streams = set(self.frames[0].poses)
        first_grippers = set(self.frames[0].grippers)
        previous_timestamp = -math.inf
        for frame in self.frames:
            if set(frame.poses) != first_streams:
                raise ValueError("all frames must contain the same stream names")
            if set(frame.grippers) != first_grippers:
                raise ValueError("all frames must contain the same gripper streams")
            if not set(frame.grippers).issubset(first_streams):
                raise ValueError("gripper streams must correspond to pose streams")
            if frame.timestamp_s <= previous_timestamp:
                raise ValueError("timestamps must be strictly increasing")
            previous_timestamp = frame.timestamp_s
            if any(pose.frame != self.coordinate_frame for pose in frame.poses.values()):
                raise ValueError("all poses must use the trajectory coordinate_frame")
        return self

    @property
    def stream_names(self) -> tuple[str, ...]:
        """Stable stream names in the first-frame insertion order."""

        return tuple(self.frames[0].poses)

    @property
    def frame_count(self) -> int:
        return len(self.frames)
