"""Target-side gripper replay contracts."""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TargetGripperFrame(BaseModel):
    """One timestamp of target gripper joint positions, without arm state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp_s: float = Field(ge=0.0)
    joint_positions: dict[str, float] = Field(min_length=1)

    @field_validator("timestamp_s")
    @classmethod
    def validate_timestamp(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("target gripper timestamp must be finite")
        return value

    @field_validator("joint_positions")
    @classmethod
    def validate_positions(cls, value: dict[str, float]) -> dict[str, float]:
        for name, position in value.items():
            if not name.strip():
                raise ValueError("target gripper joint names must not be blank")
            if not math.isfinite(position):
                raise ValueError("target gripper joint positions must be finite")
        return value


class TargetGripperTrajectory(BaseModel):
    """A value-bearing gripper-only replay artifact bound to one target profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    robot_id: str = Field(min_length=1)
    profile_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    group_names: tuple[str, ...] = Field(min_length=1)
    frames: list[TargetGripperFrame] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_alignment(self) -> TargetGripperTrajectory:
        if len(set(self.group_names)) != len(self.group_names):
            raise ValueError("target gripper group names must be unique")
        if any(not name.strip() for name in self.group_names):
            raise ValueError("target gripper group names must not be blank")
        expected_joints = set(self.frames[0].joint_positions)
        previous_timestamp = -math.inf
        for frame in self.frames:
            if set(frame.joint_positions) != expected_joints:
                raise ValueError("all target gripper frames must share joint names")
            if frame.timestamp_s <= previous_timestamp:
                raise ValueError("target gripper timestamps must be strictly increasing")
            previous_timestamp = frame.timestamp_s
        return self
