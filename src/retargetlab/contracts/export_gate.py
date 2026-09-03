"""Value-free preflight contract for dataset export inputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Hash = str


class ExportInputGate(BaseModel):
    """All non-value prerequisites proven before a dataset writer may run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.2", pattern=r"^0\.2$")
    artifact_type: Literal["export_input_gate"] = "export_input_gate"
    status: Literal["READY"] = "READY"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    data_profile_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    coverage_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    target_replay_bundle_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    export_profile_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    robot_id: str = Field(min_length=1)
    source_frame_count: int = Field(gt=0)
    target_replay_frame_count: int = Field(gt=0)
    training_episode_allowlist: tuple[int, ...] = Field(min_length=1)
    normalization_exclude: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_allowlist(self) -> ExportInputGate:
        if len(set(self.training_episode_allowlist)) != len(self.training_episode_allowlist):
            raise ValueError("training episode allowlist must be unique")
        if any(index < 0 for index in self.training_episode_allowlist):
            raise ValueError("training episode allowlist indices must be non-negative")
        if len(set(self.normalization_exclude)) != len(self.normalization_exclude):
            raise ValueError("normalization exclusions must be unique")
        if any(not item.strip() for item in self.normalization_exclude):
            raise ValueError("normalization exclusions must not be blank")
        return self
