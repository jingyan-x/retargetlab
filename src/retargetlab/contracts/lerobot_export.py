"""Metadata-only contracts for a future LeRobot v3 export."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .export_profile import TargetVectorLayout
from .mapping import FeatureDeclaration

Hash = str

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

    @model_validator(mode="after")
    def validate_range(self) -> LeRobotEpisodeMetadata:
        if self.dataset_to_index - self.dataset_from_index != self.length:
            raise ValueError("episode data range does not match its length")
        if len(set(self.task_indices)) != len(self.task_indices):
            raise ValueError("episode task indices must be unique")
        if any(index < 0 for index in self.task_indices):
            raise ValueError("episode task indices must be non-negative")
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
