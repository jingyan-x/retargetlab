"""Provenance contract for a canonical-to-target replay."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class TargetReplayManifest(BaseModel):
    """Value-free binding of all inputs needed for one target replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    replay_id: str = Field(min_length=1)
    status: Literal["READY"] = "READY"
    robot_id: str = Field(min_length=1)
    coupling: str = Field(min_length=1)
    backend_name: str = Field(min_length=1)
    backend_version: str = Field(min_length=1)
    arm_group: str = Field(min_length=1)
    frame_count: int = Field(gt=0)
    target_group_names: tuple[str, ...] = Field(min_length=1)
    canonical_trajectory_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    robot_profile_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    recipe_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    arm_solve_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    target_grippers_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    artifacts: tuple[ReplayArtifact, ...] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_artifacts(self) -> TargetReplayManifest:
        roles = tuple(item.role for item in self.artifacts)
        expected_roles = {
            "canonical_trajectory",
            "robot_profile",
            "recipe",
            "arm_solve",
            "target_grippers",
        }
        if set(roles) != expected_roles or len(roles) != len(set(roles)):
            raise ValueError("replay manifest must contain one artifact for each required role")
        hashes = {item.role: item.sha256 for item in self.artifacts}
        expected_hashes = {
            "canonical_trajectory": self.canonical_trajectory_sha256,
            "robot_profile": self.robot_profile_sha256,
            "recipe": self.recipe_sha256,
            "arm_solve": self.arm_solve_sha256,
            "target_grippers": self.target_grippers_sha256,
        }
        if hashes != expected_hashes:
            raise ValueError("replay artifact hashes do not match manifest fields")
        if len(set(self.target_group_names)) != len(self.target_group_names):
            raise ValueError("replay target group names must be unique")
        return self
