"""Provenance contract for a canonical-to-target replay."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .export_profile import TargetVectorLayout

Hash = str
ReplayArtifactRole = Literal[
    "canonical_trajectory",
    "robot_profile",
    "recipe",
    "arm_solve",
    "target_grippers",
]


class ReplayArtifact(BaseModel):
    """One immutable input reference in a replay manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: ReplayArtifactRole
    path: str = Field(min_length=1)
    sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    group: str | None = None

    @model_validator(mode="after")
    def validate_group(self) -> ReplayArtifact:
        if self.role == "arm_solve" and (self.group is None or not self.group.strip()):
            raise ValueError("arm solve artifacts require a non-empty group")
        if self.role != "arm_solve" and self.group is not None:
            raise ValueError("only arm solve artifacts may declare a group")
        return self


class TargetReplayManifest(BaseModel):
    """Value-free binding of all inputs needed for one multi-group replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.2", pattern=r"^0\.2$")
    replay_id: str = Field(min_length=1)
    status: Literal["READY"] = "READY"
    robot_id: str = Field(min_length=1)
    coupling: str = Field(min_length=1)
    backend_name: str = Field(min_length=1)
    backend_version: str = Field(min_length=1)
    arm_groups: tuple[str, ...] = Field(min_length=1)
    frame_count: int = Field(gt=0)
    target_group_names: tuple[str, ...] = Field(min_length=1)
    canonical_trajectory_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    robot_profile_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    recipe_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    arm_solve_sha256s: tuple[Hash, ...] = Field(min_length=1)
    target_grippers_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    artifacts: tuple[ReplayArtifact, ...] = Field(min_length=5)

    @model_validator(mode="after")
    def validate_artifacts(self) -> TargetReplayManifest:
        if len(set(self.target_group_names)) != len(self.target_group_names):
            raise ValueError("replay target group names must be unique")
        if len(set(self.arm_groups)) != len(self.arm_groups):
            raise ValueError("replay arm groups must be unique")
        if set(self.arm_groups) != set(self.target_group_names):
            raise ValueError("arm solve groups must cover every target robot group")
        if len(self.arm_groups) != len(self.arm_solve_sha256s):
            raise ValueError("arm solve hashes must match arm group count")

        non_arm = [item for item in self.artifacts if item.role != "arm_solve"]
        arm = [item for item in self.artifacts if item.role == "arm_solve"]
        expected_non_arm_roles = {
            "canonical_trajectory",
            "robot_profile",
            "recipe",
            "target_grippers",
        }
        if {item.role for item in non_arm} != expected_non_arm_roles or len(non_arm) != 4:
            raise ValueError("replay manifest must contain one artifact for each non-arm role")
        if len(arm) != len(self.arm_groups):
            raise ValueError("replay manifest arm artifacts must cover every arm group")
        if {item.group for item in arm} != set(self.arm_groups):
            raise ValueError("replay arm artifact groups do not match arm_groups")

        expected_hashes = {
            "canonical_trajectory": self.canonical_trajectory_sha256,
            "robot_profile": self.robot_profile_sha256,
            "recipe": self.recipe_sha256,
            "target_grippers": self.target_grippers_sha256,
        }
        observed_hashes = {item.role: item.sha256 for item in non_arm}
        if observed_hashes != expected_hashes:
            raise ValueError("replay artifact hashes do not match manifest fields")
        observed_arm_hashes = {item.group: item.sha256 for item in arm}
        expected_arm_hashes = dict(zip(self.arm_groups, self.arm_solve_sha256s, strict=True))
        if observed_arm_hashes != expected_arm_hashes:
            raise ValueError("replay arm solve hashes do not match manifest fields")
        return self


class TargetReplayVerification(BaseModel):
    """Value-free result of rechecking a target replay manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.2", pattern=r"^0\.2$")
    status: Literal["VERIFIED"] = "VERIFIED"
    replay_id: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    frame_count: int = Field(gt=0)
    manifest_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    robot_profile_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    arm_groups: tuple[str, ...] = Field(min_length=1)
    artifact_roles: tuple[ReplayArtifactRole, ...] = Field(min_length=5)


class TargetReplayFrame(BaseModel):
    """One value-bearing target command row in export-layout order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp_s: float = Field(ge=0.0)
    joint_positions: tuple[float, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_finite(self) -> TargetReplayFrame:
        if not math.isfinite(self.timestamp_s):
            raise ValueError("target replay timestamp must be finite")
        if not all(math.isfinite(value) for value in self.joint_positions):
            raise ValueError("target replay joint positions must be finite")
        return self


class TargetReplayTrajectory(BaseModel):
    """Deterministic target command values bound to verified provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    status: Literal["READY"] = "READY"
    replay_id: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    replay_manifest_path: str = Field(min_length=1)
    replay_manifest_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    export_profile_path: str = Field(min_length=1)
    export_profile_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    layout: TargetVectorLayout
    frame_count: int = Field(gt=0)
    frames: list[TargetReplayFrame] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_alignment(self) -> TargetReplayTrajectory:
        if self.frame_count != len(self.frames):
            raise ValueError("target replay frame_count does not match frames")
        previous_timestamp = -math.inf
        for frame in self.frames:
            if len(frame.joint_positions) != self.layout.dimension:
                raise ValueError("target replay joint vector does not match export layout")
            if frame.timestamp_s <= previous_timestamp:
                raise ValueError("target replay timestamps must be strictly increasing")
            previous_timestamp = frame.timestamp_s
        return self
