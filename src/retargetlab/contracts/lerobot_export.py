"""Metadata-only contracts for a future LeRobot v3 export."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .export_profile import TargetVectorLayout
from .mapping import FeatureDeclaration

Hash = str
RetargetStatus = Literal["PASS", "WARN", "FAIL"]

_REQUIRED_FRAME_FEATURES = ("timestamp", "frame_index", "episode_index", "index", "task_index")
_REQUIRED_TARGET_FEATURES = ("observation.state", "action", "valid.retarget")


class LeRobotTaskMetadata(BaseModel):
    """One task row for ``meta/tasks.parquet``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_index: int = Field(ge=0)
    task: str = Field(min_length=1)


class LeRobotEpisodeMetadata(BaseModel):
    """One episode row and its contiguous range in the shared data table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    episode_index: int = Field(ge=0)
    length: int = Field(gt=0)
    dataset_from_index: int = Field(ge=0)
    dataset_to_index: int = Field(gt=0)
    task_indices: tuple[int, ...] = Field(min_length=1)
    data_chunk_index: int = Field(ge=0)
    data_file_index: int = Field(ge=0)
    retarget_status: RetargetStatus = "PASS"

    @model_validator(mode="after")
    def validate_range(self) -> LeRobotEpisodeMetadata:
        if self.dataset_to_index - self.dataset_from_index != self.length:
            raise ValueError("episode data range does not match its length")
        if len(set(self.task_indices)) != len(self.task_indices):
            raise ValueError("episode task indices must be unique")
        if any(index < 0 for index in self.task_indices):
            raise ValueError("episode task indices must be non-negative")
        return self


class LeRobotEpisodeRetargetMask(BaseModel):
    """Per-episode frame validity and the resulting audit status."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    episode_index: int = Field(ge=0)
    frame_count: int = Field(gt=0)
    valid_frames: tuple[bool, ...] = Field(min_length=1)
    retarget_status: RetargetStatus
    valid_frame_count: int = Field(ge=0)
    first_valid_frame_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_mask(self) -> LeRobotEpisodeRetargetMask:
        if self.frame_count != len(self.valid_frames):
            raise ValueError("retarget mask frame_count does not match valid_frames")
        valid_indices = [index for index, valid in enumerate(self.valid_frames) if valid]
        if self.valid_frame_count != len(valid_indices):
            raise ValueError("retarget mask valid_frame_count does not match valid_frames")
        expected_status: RetargetStatus
        if not valid_indices:
            expected_status = "FAIL"
        elif len(valid_indices) == self.frame_count:
            expected_status = "PASS"
        else:
            expected_status = "WARN"
        if self.retarget_status != expected_status:
            raise ValueError("retarget mask status does not match valid_frames")
        expected_first = valid_indices[0] if valid_indices else None
        if self.first_valid_frame_index != expected_first:
            raise ValueError("retarget mask first valid frame does not match valid_frames")
        return self


class LeRobotRetargetMask(BaseModel):
    """Value-bearing frame mask used to keep failed rows auditable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["lerobot_retarget_mask"] = "lerobot_retarget_mask"
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    status: Literal["READY"] = "READY"
    mask_policy: Literal["carry_forward_previous_valid_then_first_valid"] = (
        "carry_forward_previous_valid_then_first_valid"
    )
    all_invalid_policy: Literal["retain_candidate_values_and_mark_fail"] = (
        "retain_candidate_values_and_mark_fail"
    )
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    plan_path: str = Field(min_length=1)
    plan_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    episodes: tuple[LeRobotEpisodeRetargetMask, ...] = Field(min_length=1)
    training_episode_allowlist: tuple[int, ...] = ()
    normalization_exclude: tuple[str, ...] = ("valid.retarget",)
    total_episodes: int = Field(gt=0)
    total_frames: int = Field(gt=0)
    total_valid_frames: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_mask(self) -> LeRobotRetargetMask:
        if self.total_episodes != len(self.episodes):
            raise ValueError("retarget mask episode count does not match episodes")
        episode_indices = tuple(episode.episode_index for episode in self.episodes)
        if episode_indices != tuple(sorted(episode_indices)):
            raise ValueError("retarget mask episodes must be ordered by episode_index")
        if len(set(episode_indices)) != len(episode_indices):
            raise ValueError("retarget mask episode indices must be unique")
        if self.total_frames != sum(episode.frame_count for episode in self.episodes):
            raise ValueError("retarget mask frame count does not match episodes")
        if self.total_valid_frames != sum(
            episode.valid_frame_count for episode in self.episodes
        ):
            raise ValueError("retarget mask valid frame count does not match episodes")
        if len(set(self.training_episode_allowlist)) != len(self.training_episode_allowlist):
            raise ValueError("retarget mask training episode allowlist must be unique")
        if any(index < 0 for index in self.training_episode_allowlist):
            raise ValueError("retarget mask training episode allowlist must be non-negative")
        pass_indices = tuple(
            episode.episode_index
            for episode in self.episodes
            if episode.retarget_status == "PASS"
        )
        if any(index not in pass_indices for index in self.training_episode_allowlist):
            raise ValueError("retarget mask training allowlist must contain PASS episodes only")
        if len(set(self.normalization_exclude)) != len(self.normalization_exclude):
            raise ValueError("retarget mask normalization exclusions must be unique")
        if any(not item.strip() for item in self.normalization_exclude):
            raise ValueError("retarget mask normalization exclusions must be non-empty")
        if "valid.retarget" not in self.normalization_exclude:
            raise ValueError("retarget mask normalization exclusions must include valid.retarget")
        return self


class LeRobotRetargetMaskVerification(BaseModel):
    """Value-free result of rechecking a retarget frame mask."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["lerobot_retarget_mask_verification"] = (
        "lerobot_retarget_mask_verification"
    )
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    status: Literal["VERIFIED"] = "VERIFIED"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    plan_path: str = Field(min_length=1)
    plan_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    mask_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    total_episodes: int = Field(gt=0)
    total_frames: int = Field(gt=0)
    total_valid_frames: int = Field(ge=0)
    training_episode_allowlist: tuple[int, ...] = ()


class LeRobotEpisodeReplayBinding(BaseModel):
    """Value-free binding from one planned episode to one target replay bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    episode_index: int = Field(ge=0)
    dataset_from_index: int = Field(ge=0)
    dataset_to_index: int = Field(gt=0)
    target_replay_bundle_path: str = Field(min_length=1)
    target_replay_bundle_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    replay_id: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    export_profile_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    layout: TargetVectorLayout
    frame_count: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> LeRobotEpisodeReplayBinding:
        if self.dataset_to_index - self.dataset_from_index != self.frame_count:
            raise ValueError("episode replay binding range does not match frame_count")
        return self


class LeRobotReplayBindingManifest(BaseModel):
    """Value-free mapping needed before multi-episode data shards can be written."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["lerobot_replay_binding_manifest"] = (
        "lerobot_replay_binding_manifest"
    )
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    status: Literal["READY"] = "READY"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    plan_path: str = Field(min_length=1)
    plan_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    target_layout: TargetVectorLayout
    total_frames: int = Field(gt=0)
    bindings: tuple[LeRobotEpisodeReplayBinding, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bindings(self) -> LeRobotReplayBindingManifest:
        if self.total_frames != sum(binding.frame_count for binding in self.bindings):
            raise ValueError("replay binding frame counts do not match total_frames")
        episode_indices = tuple(binding.episode_index for binding in self.bindings)
        if episode_indices != tuple(sorted(episode_indices)):
            raise ValueError("replay bindings must be ordered by episode_index")
        if len(set(episode_indices)) != len(episode_indices):
            raise ValueError("replay binding episode indices must be unique")
        expected_start = 0
        for binding in self.bindings:
            if binding.dataset_from_index != expected_start:
                raise ValueError("replay binding ranges must be contiguous from zero")
            if binding.robot_id != self.robot_id:
                raise ValueError("replay binding robot ids must match")
            if binding.layout != self.target_layout:
                raise ValueError("replay binding layouts must match")
            expected_start = binding.dataset_to_index
        if expected_start != self.total_frames:
            raise ValueError("replay binding ranges do not cover total_frames")
        return self


class LeRobotReplayBindingVerification(BaseModel):
    """Value-free result of rechecking a multi-episode replay binding manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["lerobot_replay_binding_verification"] = (
        "lerobot_replay_binding_verification"
    )
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    status: Literal["VERIFIED"] = "VERIFIED"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    plan_path: str = Field(min_length=1)
    plan_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    binding_manifest_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    binding_count: int = Field(gt=0)
    total_frames: int = Field(gt=0)


class LeRobotEpisodeTargetTableBinding(BaseModel):
    """Value-free binding from one episode to its verified target-table report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    episode_index: int = Field(ge=0)
    dataset_from_index: int = Field(ge=0)
    dataset_to_index: int = Field(gt=0)
    target_table_report_path: str = Field(min_length=1)
    target_table_report_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    target_replay_bundle_path: str = Field(min_length=1)
    target_replay_bundle_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    replay_id: str = Field(min_length=1)
    frame_count: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> LeRobotEpisodeTargetTableBinding:
        if self.dataset_to_index - self.dataset_from_index != self.frame_count:
            raise ValueError("target-table binding range does not match frame_count")
        return self


class LeRobotTargetTableBindingManifest(BaseModel):
    """Value-free mapping for multi-episode target-table materialization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["lerobot_target_table_binding_manifest"] = (
        "lerobot_target_table_binding_manifest"
    )
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    status: Literal["READY"] = "READY"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    plan_path: str = Field(min_length=1)
    plan_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    replay_binding_manifest_path: str = Field(min_length=1)
    replay_binding_manifest_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    target_layout: TargetVectorLayout
    total_frames: int = Field(gt=0)
    bindings: tuple[LeRobotEpisodeTargetTableBinding, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bindings(self) -> LeRobotTargetTableBindingManifest:
        if self.total_frames != sum(binding.frame_count for binding in self.bindings):
            raise ValueError("target-table binding frame counts do not match total_frames")
        episode_indices = tuple(binding.episode_index for binding in self.bindings)
        if episode_indices != tuple(sorted(episode_indices)):
            raise ValueError("target-table bindings must be ordered by episode_index")
        if len(set(episode_indices)) != len(episode_indices):
            raise ValueError("target-table binding episode indices must be unique")
        expected_start = 0
        for binding in self.bindings:
            if binding.dataset_from_index != expected_start:
                raise ValueError("target-table binding ranges must be contiguous from zero")
            expected_start = binding.dataset_to_index
        if expected_start != self.total_frames:
            raise ValueError("target-table binding ranges do not cover total_frames")
        return self


class LeRobotTargetTableBindingVerification(BaseModel):
    """Value-free result of rechecking target-table bindings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["lerobot_target_table_binding_verification"] = (
        "lerobot_target_table_binding_verification"
    )
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    status: Literal["VERIFIED"] = "VERIFIED"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    plan_path: str = Field(min_length=1)
    plan_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    target_table_binding_manifest_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    binding_count: int = Field(gt=0)
    total_frames: int = Field(gt=0)


class LeRobotMultiEpisodeDatasetWrite(BaseModel):
    """Manifest for grouped synthetic data shards with stats/videos still absent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["lerobot_multi_episode_dataset_write"] = (
        "lerobot_multi_episode_dataset_write"
    )
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    status: Literal["PARTIAL"] = "PARTIAL"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    plan_path: str = Field(min_length=1)
    plan_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    output_root: str = Field(min_length=1)
    target_table_binding_manifest_path: str = Field(min_length=1)
    target_table_binding_manifest_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    retarget_mask_path: str | None = Field(default=None, min_length=1)
    retarget_mask_sha256: Hash | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    written_files: tuple[str, ...] = Field(min_length=1)
    omitted_components: tuple[str, ...] = Field(min_length=1)
    total_episodes: int = Field(gt=0)
    total_frames: int = Field(gt=0)
    total_tasks: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_manifest(self) -> LeRobotMultiEpisodeDatasetWrite:
        if len(set(self.written_files)) != len(self.written_files):
            raise ValueError("multi-episode dataset written files must be unique")
        if any(not path.strip() or path.startswith("/") for path in self.written_files):
            raise ValueError("multi-episode dataset written files must be relative paths")
        if len(set(self.omitted_components)) != len(self.omitted_components):
            raise ValueError("multi-episode dataset omitted components must be unique")
        if any(not component.strip() for component in self.omitted_components):
            raise ValueError("multi-episode dataset omitted components must be non-empty")
        if not {"video_shards", "meta/stats.json"}.issubset(self.omitted_components):
            raise ValueError("multi-episode dataset must record video and stats omissions")
        if "data_shards" in self.omitted_components:
            raise ValueError("multi-episode dataset must not omit its written data shards")
        if (self.retarget_mask_path is None) != (self.retarget_mask_sha256 is None):
            raise ValueError("retarget mask path and hash must be supplied together")
        return self


class LeRobotMultiEpisodeDatasetVerification(BaseModel):
    """Verification result for grouped synthetic data shards."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["lerobot_multi_episode_dataset_verification"] = (
        "lerobot_multi_episode_dataset_verification"
    )
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    status: Literal["VERIFIED"] = "VERIFIED"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    plan_path: str = Field(min_length=1)
    plan_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    output_root: str = Field(min_length=1)
    target_table_binding_manifest_path: str = Field(min_length=1)
    target_table_binding_manifest_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    retarget_mask_path: str | None = Field(default=None, min_length=1)
    retarget_mask_sha256: Hash | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    written_files: tuple[str, ...] = Field(min_length=1)
    omitted_components: tuple[str, ...] = Field(min_length=1)
    total_episodes: int = Field(gt=0)
    total_frames: int = Field(gt=0)
    total_tasks: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_mask_binding(self) -> LeRobotMultiEpisodeDatasetVerification:
        if (self.retarget_mask_path is None) != (self.retarget_mask_sha256 is None):
            raise ValueError("retarget mask path and hash must be supplied together")
        return self


class LeRobotStatisticsWrite(BaseModel):
    """Manifest for exact numeric stats with video output still absent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["lerobot_statistics_write"] = "lerobot_statistics_write"
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    status: Literal["PARTIAL"] = "PARTIAL"
    statistics_algorithm: Literal["numpy_exact_v0.1"] = "numpy_exact_v0.1"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    plan_path: str = Field(min_length=1)
    plan_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    output_root: str = Field(min_length=1)
    target_table_binding_manifest_path: str = Field(min_length=1)
    target_table_binding_manifest_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    retarget_mask_path: str | None = Field(default=None, min_length=1)
    retarget_mask_sha256: Hash | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    stats_path: str = Field(min_length=1)
    stats_relative_path: str = Field(min_length=1)
    stats_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    stats_features: tuple[str, ...] = Field(min_length=1)
    written_files: tuple[str, ...] = Field(min_length=1)
    omitted_components: tuple[str, ...] = Field(min_length=1)
    total_episodes: int = Field(gt=0)
    total_frames: int = Field(gt=0)
    total_tasks: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_manifest(self) -> LeRobotStatisticsWrite:
        if len(set(self.stats_features)) != len(self.stats_features):
            raise ValueError("statistics features must be unique")
        if any(not feature.strip() for feature in self.stats_features):
            raise ValueError("statistics features must be non-empty")
        if len(set(self.written_files)) != len(self.written_files):
            raise ValueError("statistics written files must be unique")
        if any(not path.strip() or path.startswith("/") for path in self.written_files):
            raise ValueError("statistics written files must be relative paths")
        if len(set(self.omitted_components)) != len(self.omitted_components):
            raise ValueError("statistics omitted components must be unique")
        if any(not component.strip() for component in self.omitted_components):
            raise ValueError("statistics omitted components must be non-empty")
        if "video_shards" not in self.omitted_components:
            raise ValueError("statistics manifest must record video omission")
        if "meta/stats.json" in self.omitted_components:
            raise ValueError("statistics manifest must not omit its written stats file")
        if (self.retarget_mask_path is None) != (self.retarget_mask_sha256 is None):
            raise ValueError("retarget mask path and hash must be supplied together")
        return self


class LeRobotStatisticsVerification(BaseModel):
    """Verification result for exact numeric stats on a partial dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["lerobot_statistics_verification"] = (
        "lerobot_statistics_verification"
    )
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    status: Literal["VERIFIED"] = "VERIFIED"
    statistics_algorithm: Literal["numpy_exact_v0.1"] = "numpy_exact_v0.1"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    plan_path: str = Field(min_length=1)
    plan_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    output_root: str = Field(min_length=1)
    target_table_binding_manifest_path: str = Field(min_length=1)
    target_table_binding_manifest_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    retarget_mask_path: str | None = Field(default=None, min_length=1)
    retarget_mask_sha256: Hash | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    stats_path: str = Field(min_length=1)
    stats_relative_path: str = Field(min_length=1)
    stats_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    stats_features: tuple[str, ...] = Field(min_length=1)
    written_files: tuple[str, ...] = Field(min_length=1)
    omitted_components: tuple[str, ...] = Field(min_length=1)
    total_episodes: int = Field(gt=0)
    total_frames: int = Field(gt=0)
    total_tasks: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_mask_binding(self) -> LeRobotStatisticsVerification:
        if (self.retarget_mask_path is None) != (self.retarget_mask_sha256 is None):
            raise ValueError("retarget mask path and hash must be supplied together")
        return self


class LeRobotLoaderPreflight(BaseModel):
    """Compatibility preflight without claiming upstream training readiness."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["lerobot_loader_preflight"] = "lerobot_loader_preflight"
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    loader_contract: Literal["lerobot_v3_numeric_video_free_v0.1"] = (
        "lerobot_v3_numeric_video_free_v0.1"
    )
    upstream_training_compatibility: Literal["NOT_CLAIMED"] = "NOT_CLAIMED"
    status: Literal["READY", "BLOCKED"]
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    plan_path: str = Field(min_length=1)
    plan_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    output_root: str = Field(min_length=1)
    target_table_binding_manifest_path: str = Field(min_length=1)
    target_table_binding_manifest_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    retarget_mask_path: str | None = Field(default=None, min_length=1)
    retarget_mask_sha256: Hash | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    episode_indices: tuple[int, ...] = ()
    stats_features: tuple[str, ...] = Field(min_length=1)
    checked_files: tuple[str, ...] = Field(min_length=1)
    passed_checks: tuple[str, ...] = Field(min_length=1)
    blocking_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    total_episodes: int = Field(gt=0)
    total_frames: int = Field(gt=0)
    total_tasks: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_preflight(self) -> LeRobotLoaderPreflight:
        if len(set(self.episode_indices)) != len(self.episode_indices):
            raise ValueError("loader preflight episode indices must be unique")
        if any(index < 0 for index in self.episode_indices):
            raise ValueError("loader preflight episode indices must be non-negative")
        if len(set(self.stats_features)) != len(self.stats_features):
            raise ValueError("loader preflight stats features must be unique")
        if any(not feature.strip() for feature in self.stats_features):
            raise ValueError("loader preflight stats features must be non-empty")
        if len(set(self.checked_files)) != len(self.checked_files):
            raise ValueError("loader preflight checked files must be unique")
        if any(not path.strip() or path.startswith("/") for path in self.checked_files):
            raise ValueError("loader preflight checked files must be relative paths")
        if len(set(self.passed_checks)) != len(self.passed_checks):
            raise ValueError("loader preflight checks must be unique")
        if any(not check.strip() for check in self.passed_checks):
            raise ValueError("loader preflight checks must be non-empty")
        if len(set(self.blocking_reasons)) != len(self.blocking_reasons):
            raise ValueError("loader preflight blocking reasons must be unique")
        if len(set(self.warnings)) != len(self.warnings):
            raise ValueError("loader preflight warnings must be unique")
        if (self.retarget_mask_path is None) != (self.retarget_mask_sha256 is None):
            raise ValueError("retarget mask path and hash must be supplied together")
        if (self.status == "BLOCKED") != bool(self.blocking_reasons):
            raise ValueError("loader preflight status must match blocking reasons")
        if self.status == "READY" and not self.episode_indices:
            raise ValueError("ready loader preflight must select at least one episode")
        return self


class LeRobotTrainingDatasetConfig(BaseModel):
    """Direct dataset-loader configuration, not a training-run result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["lerobot_training_dataset_config"] = (
        "lerobot_training_dataset_config"
    )
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    status: Literal["READY", "BLOCKED"]
    loader_contract: Literal["lerobot_v3_numeric_video_free_v0.1"] = (
        "lerobot_v3_numeric_video_free_v0.1"
    )
    runtime_dependency: Literal["lerobot==0.6.1"] = "lerobot==0.6.1"
    upstream_training_compatibility: Literal["NOT_CLAIMED"] = "NOT_CLAIMED"
    dataset_alias: str = Field(min_length=1)
    repo_id: str = Field(min_length=1)
    root: str = Field(min_length=1)
    episodes: tuple[int, ...] = ()
    plan_path: str = Field(min_length=1)
    plan_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    preflight_path: str = Field(min_length=1)
    preflight_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    retarget_mask_path: str | None = Field(default=None, min_length=1)
    retarget_mask_sha256: Hash | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    blocking_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_config(self) -> LeRobotTrainingDatasetConfig:
        if len(set(self.episodes)) != len(self.episodes):
            raise ValueError("training config episode selection must be unique")
        if any(index < 0 for index in self.episodes):
            raise ValueError("training config episode selection must be non-negative")
        if len(set(self.blocking_reasons)) != len(self.blocking_reasons):
            raise ValueError("training config blocking reasons must be unique")
        if any(not reason.strip() for reason in self.blocking_reasons):
            raise ValueError("training config blocking reasons must be non-empty")
        if len(set(self.warnings)) != len(self.warnings):
            raise ValueError("training config warnings must be unique")
        if any(not warning.strip() for warning in self.warnings):
            raise ValueError("training config warnings must be non-empty")
        if (self.retarget_mask_path is None) != (self.retarget_mask_sha256 is None):
            raise ValueError("retarget mask path and hash must be supplied together")
        if (self.status == "BLOCKED") != bool(self.blocking_reasons):
            raise ValueError("training config status must match blocking reasons")
        if self.status == "READY" and not self.episodes:
            raise ValueError("ready training config must select at least one episode")
        if self.status == "READY" and self.episodes != tuple(range(len(self.episodes))):
            raise ValueError("ready training config episodes must be zero-based and contiguous")
        return self


class LeRobotMetadataPlan(BaseModel):
    """Value-free plan for a complete, video-free LeRobot v3 metadata set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["lerobot_metadata_plan"] = "lerobot_metadata_plan"
    status: Literal["READY"] = "READY"
    codebase_version: Literal["v3.0"] = "v3.0"
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    export_input_gate_path: str = Field(min_length=1)
    export_input_gate_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    export_profile_path: str = Field(min_length=1)
    export_profile_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    robot_id: str = Field(min_length=1)
    target_layout: TargetVectorLayout
    fps: float = Field(gt=0.0)
    total_episodes: int = Field(gt=0)
    total_frames: int = Field(gt=0)
    total_tasks: int = Field(gt=0)
    features: dict[str, FeatureDeclaration] = Field(min_length=1)
    tasks: tuple[LeRobotTaskMetadata, ...] = Field(min_length=1)
    episodes: tuple[LeRobotEpisodeMetadata, ...] = Field(min_length=1)
    training_episode_allowlist: tuple[int, ...] = Field(min_length=1)
    stats_features: tuple[str, ...] = ("observation.state", "action")
    episode_index_policy: Literal["preserve_source"] = "preserve_source"
    data_path_template: str = "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet"
    episodes_path_template: str = (
        "meta/episodes/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet"
    )
    tasks_path: str = "meta/tasks.parquet"
    info_path: str = "meta/info.json"
    stats_path: str = "meta/stats.json"
    video_keys: tuple[str, ...] = ()
    video_path_templates: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_plan(self) -> LeRobotMetadataPlan:
        if not math.isfinite(self.fps):
            raise ValueError("LeRobot metadata fps must be finite")
        if self.total_episodes != len(self.episodes):
            raise ValueError("total episode count does not match episode metadata")
        if self.total_frames != sum(episode.length for episode in self.episodes):
            raise ValueError("total frame count does not match episode metadata")
        if self.total_tasks != len(self.tasks):
            raise ValueError("total task count does not match task metadata")

        episode_indices = tuple(episode.episode_index for episode in self.episodes)
        if episode_indices != tuple(sorted(episode_indices)):
            raise ValueError("episode metadata must be ordered by episode_index")
        if len(set(episode_indices)) != len(episode_indices):
            raise ValueError("episode metadata indices must be unique")
        if episode_indices != self.training_episode_allowlist:
            raise ValueError("episode metadata must match the training episode allowlist")
        if len(set(self.training_episode_allowlist)) != len(self.training_episode_allowlist):
            raise ValueError("training episode allowlist must be unique")
        if any(index < 0 for index in self.training_episode_allowlist):
            raise ValueError("training episode allowlist indices must be non-negative")

        expected_data_start = 0
        for episode in self.episodes:
            if episode.dataset_from_index != expected_data_start:
                raise ValueError("episode data ranges must be contiguous from zero")
            expected_data_start = episode.dataset_to_index
        if expected_data_start != self.total_frames:
            raise ValueError("episode data ranges do not cover total_frames")

        task_indices = tuple(task.task_index for task in self.tasks)
        if task_indices != tuple(range(self.total_tasks)):
            raise ValueError("task indices must be sequential from zero")
        task_index_set = set(task_indices)
        for episode in self.episodes:
            if not set(episode.task_indices).issubset(task_index_set):
                raise ValueError("episode references an unknown task index")

        missing_features = [
            name
            for name in (*_REQUIRED_FRAME_FEATURES, *_REQUIRED_TARGET_FEATURES)
            if name not in self.features
        ]
        if missing_features:
            raise ValueError(f"metadata plan is missing required features: {missing_features}")
        for name in _REQUIRED_FRAME_FEATURES:
            feature = self.features[name]
            if feature.shape != () or feature.storage != "parquet":
                raise ValueError(f"metadata feature must be a parquet scalar: {name}")
        for name in ("observation.state", "action"):
            feature = self.features[name]
            if (
                feature.dtype != self.target_layout.dtype
                or feature.shape != self.target_layout.shape
                or feature.names != self.target_layout.names
                or feature.storage != "parquet"
            ):
                raise ValueError(f"metadata target feature does not match target layout: {name}")
        valid_feature = self.features["valid.retarget"]
        if valid_feature.dtype != "bool" or valid_feature.shape != ():
            raise ValueError("valid.retarget must be a boolean scalar feature")
        if valid_feature.storage != "parquet":
            raise ValueError("valid.retarget must be stored in parquet")

        if len(set(self.stats_features)) != len(self.stats_features):
            raise ValueError("stats features must be unique")
        if not set(self.stats_features).issubset(self.features):
            raise ValueError("stats features must be declared features")
        if not {"observation.state", "action"}.issubset(self.stats_features):
            raise ValueError("stats features must include state and action")

        if len(set(self.video_keys)) != len(self.video_keys):
            raise ValueError("video keys must be unique")
        if set(self.video_path_templates) != set(self.video_keys):
            raise ValueError("video path templates must match video keys")
        if any(not path.strip() for path in self.video_path_templates.values()):
            raise ValueError("video path templates must not be blank")
        return self


class LeRobotMetadataPlanVerification(BaseModel):
    """Value-free result of verifying a LeRobot metadata plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    status: Literal["VERIFIED"] = "VERIFIED"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    plan_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    export_input_gate_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    export_profile_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    total_episodes: int = Field(gt=0)
    total_frames: int = Field(gt=0)
    total_tasks: int = Field(gt=0)


class LeRobotMetadataSkeletonWrite(BaseModel):
    """Manifest for a deliberately incomplete, metadata-only dataset skeleton."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["lerobot_metadata_skeleton_write"] = (
        "lerobot_metadata_skeleton_write"
    )
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    status: Literal["PARTIAL"] = "PARTIAL"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    plan_path: str = Field(min_length=1)
    plan_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    output_root: str = Field(min_length=1)
    written_files: tuple[str, ...] = Field(min_length=1)
    omitted_components: tuple[str, ...] = Field(min_length=1)
    total_episodes: int = Field(gt=0)
    total_frames: int = Field(gt=0)
    total_tasks: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_manifest(self) -> LeRobotMetadataSkeletonWrite:
        if len(set(self.written_files)) != len(self.written_files):
            raise ValueError("skeleton written files must be unique")
        if any(not path.strip() or path.startswith("/") for path in self.written_files):
            raise ValueError("skeleton written files must be non-empty relative paths")
        if len(set(self.omitted_components)) != len(self.omitted_components):
            raise ValueError("skeleton omitted components must be unique")
        if any(not component.strip() for component in self.omitted_components):
            raise ValueError("skeleton omitted components must be non-empty")
        required_omissions = {"data_shards", "video_shards", "meta/stats.json"}
        if not required_omissions.issubset(self.omitted_components):
            raise ValueError("skeleton manifest must record data, video, and stats omissions")
        return self


class LeRobotMetadataSkeletonVerification(BaseModel):
    """Verification result for a partial metadata skeleton, not a training dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["lerobot_metadata_skeleton_verification"] = (
        "lerobot_metadata_skeleton_verification"
    )
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    status: Literal["VERIFIED"] = "VERIFIED"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    plan_path: str = Field(min_length=1)
    plan_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    output_root: str = Field(min_length=1)
    written_files: tuple[str, ...] = Field(min_length=1)
    omitted_components: tuple[str, ...] = Field(min_length=1)
    total_episodes: int = Field(gt=0)
    total_frames: int = Field(gt=0)
    total_tasks: int = Field(gt=0)


class LeRobotPartialDatasetWrite(BaseModel):
    """Manifest for a partial dataset with synthetic data but no stats/videos."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["lerobot_partial_dataset_write"] = (
        "lerobot_partial_dataset_write"
    )
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    status: Literal["PARTIAL"] = "PARTIAL"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    plan_path: str = Field(min_length=1)
    plan_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    output_root: str = Field(min_length=1)
    target_table_report_path: str = Field(min_length=1)
    target_table_report_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    written_files: tuple[str, ...] = Field(min_length=1)
    omitted_components: tuple[str, ...] = Field(min_length=1)
    total_episodes: int = Field(gt=0)
    total_frames: int = Field(gt=0)
    total_tasks: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_manifest(self) -> LeRobotPartialDatasetWrite:
        if len(set(self.written_files)) != len(self.written_files):
            raise ValueError("partial dataset written files must be unique")
        if any(not path.strip() or path.startswith("/") for path in self.written_files):
            raise ValueError("partial dataset written files must be non-empty relative paths")
        if len(set(self.omitted_components)) != len(self.omitted_components):
            raise ValueError("partial dataset omitted components must be unique")
        if any(not component.strip() for component in self.omitted_components):
            raise ValueError("partial dataset omitted components must be non-empty")
        required_omissions = {"video_shards", "meta/stats.json"}
        if not required_omissions.issubset(self.omitted_components):
            raise ValueError("partial dataset manifest must record video and stats omissions")
        if "data_shards" in self.omitted_components:
            raise ValueError("partial dataset manifest must not omit its written data shards")
        return self


class LeRobotPartialDatasetVerification(BaseModel):
    """Verification result for a partial synthetic dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["lerobot_partial_dataset_verification"] = (
        "lerobot_partial_dataset_verification"
    )
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    status: Literal["VERIFIED"] = "VERIFIED"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    plan_path: str = Field(min_length=1)
    plan_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    output_root: str = Field(min_length=1)
    target_table_report_path: str = Field(min_length=1)
    target_table_report_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    written_files: tuple[str, ...] = Field(min_length=1)
    omitted_components: tuple[str, ...] = Field(min_length=1)
    total_episodes: int = Field(gt=0)
    total_frames: int = Field(gt=0)
    total_tasks: int = Field(gt=0)
