"""Contracts for the synthetic/public table-writer prototype."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .export_profile import TargetVectorLayout

Hash = str


class SyntheticTargetTableExport(BaseModel):
    """Value-free summary of one synthetic/public target table write."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["synthetic_target_table"] = "synthetic_target_table"
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    status: Literal["WRITTEN"] = "WRITTEN"
    source_table_path: str = Field(min_length=1)
    output_table_path: str = Field(min_length=1)
    target_replay_bundle_path: str = Field(min_length=1)
    target_replay_bundle_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    preflight_path: str | None = Field(default=None, min_length=1)
    preflight_sha256: Hash | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    replay_id: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    frame_count: int = Field(gt=0)
    layout: TargetVectorLayout
    source_columns: tuple[str, ...] = Field(min_length=1)
    output_columns: tuple[str, ...] = Field(min_length=1)
    preserved_columns: tuple[str, ...] = Field(min_length=1)
    selected_episode_indices: tuple[int, ...] = Field(min_length=1)
    replaced_columns: tuple[str, ...] = ("observation.state", "action")
    valid_retarget_count: int = Field(ge=0)
    output_table_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")

    @model_validator(mode="after")
    def validate_columns(self) -> SyntheticTargetTableExport:
        if len(set(self.source_columns)) != len(self.source_columns):
            raise ValueError("source table columns must be unique")
        if len(set(self.output_columns)) != len(self.output_columns):
            raise ValueError("output table columns must be unique")
        if self.replaced_columns != ("observation.state", "action"):
            raise ValueError("synthetic table must replace state and action columns")
        required = set(self.replaced_columns)
        if not required.issubset(self.source_columns):
            raise ValueError("source table must contain state and action columns")
        if (
            not required.issubset(self.output_columns)
            or "valid.retarget" not in self.output_columns
        ):
            raise ValueError("output table must contain state, action, and valid.retarget columns")
        expected_preserved = tuple(
            column for column in self.source_columns if column not in self.replaced_columns
        )
        if self.preserved_columns != expected_preserved:
            raise ValueError("preserved columns do not match the source table")
        if self.valid_retarget_count != self.frame_count:
            raise ValueError("valid.retarget must be true for every written frame")
        if len(set(self.selected_episode_indices)) != len(self.selected_episode_indices):
            raise ValueError("selected episode indices must be unique")
        if any(index < 0 for index in self.selected_episode_indices):
            raise ValueError("selected episode indices must be non-negative")
        if (self.preflight_path is None) != (self.preflight_sha256 is None):
            raise ValueError("preflight path and hash must be supplied together")
        return self


class SyntheticTableWritePreflight(BaseModel):
    """Value-free binding for the synthetic table writer's approved inputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["synthetic_table_write_preflight"] = (
        "synthetic_table_write_preflight"
    )
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    status: Literal["READY"] = "READY"
    export_input_gate_path: str = Field(min_length=1)
    export_input_gate_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    source_table_path: str = Field(min_length=1)
    source_table_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    target_replay_bundle_path: str = Field(min_length=1)
    target_replay_bundle_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    output_table_path: str = Field(min_length=1)
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    replay_id: str = Field(min_length=1)
    gated_source_frame_count: int = Field(gt=0)
    target_replay_frame_count: int = Field(gt=0)
    training_episode_allowlist: tuple[int, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_binding(self) -> SyntheticTableWritePreflight:
        if len(set(self.training_episode_allowlist)) != len(self.training_episode_allowlist):
            raise ValueError("training episode allowlist must be unique")
        if any(index < 0 for index in self.training_episode_allowlist):
            raise ValueError("training episode allowlist indices must be non-negative")
        if self.source_table_path == self.output_table_path:
            raise ValueError("synthetic table source and output paths must be different")
        return self


class SyntheticTableWritePreflightVerification(BaseModel):
    """Value-free result of rechecking a synthetic table write preflight."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    status: Literal["VERIFIED"] = "VERIFIED"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    replay_id: str = Field(min_length=1)
    preflight_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    export_input_gate_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    source_table_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    target_replay_bundle_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    target_replay_frame_count: int = Field(gt=0)
