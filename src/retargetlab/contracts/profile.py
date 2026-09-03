"""Reviewable dataset-profile contracts for a versioned source layout."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .mapping import MappingSpec

Hash = str


class DatasetRevision(BaseModel):
    """Hashes that identify the complete source-side dataset revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    info_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    data_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    episodes_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    tasks_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    stats_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")


class AffineMap(BaseModel):
    """Explicit scalar transform ``target = scale * source + offset``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scale: float
    offset: float

    @model_validator(mode="after")
    def validate_finite(self) -> AffineMap:
        if not math.isfinite(self.scale) or self.scale == 0.0:
            raise ValueError("affine map scale must be finite and non-zero")
        if not math.isfinite(self.offset):
            raise ValueError("affine map offset must be finite")
        return self


class ProfileChannel(BaseModel):
    """One source channel with explicit semantics and physical unit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stream: str = Field(min_length=1)
    index: int = Field(ge=0)
    semantics: Literal["joint_angle", "normalized_open"]
    unit: Literal["rad", "unitless"]


class GripperProfile(BaseModel):
    """Source-side gripper semantics for one EEF slot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slot: Literal["slot_0", "slot_1"]
    observation_state: ProfileChannel
    action: ProfileChannel
    reference_observation_state: ProfileChannel
    reference_action: ProfileChannel
    observation_to_aperture: AffineMap
    action_to_aperture: AffineMap
    aperture_semantics: Literal["aperture_fraction"] = "aperture_fraction"

    @model_validator(mode="after")
    def validate_channel_semantics(self) -> GripperProfile:
        if self.observation_state.stream != "observation.state":
            raise ValueError("observation_state must use observation.state")
        if self.action.stream != "action":
            raise ValueError("action must use action")
        if self.reference_observation_state.stream != "observation.state.position":
            raise ValueError("reference_observation_state must use observation.state.position")
        if self.reference_action.stream != "action.position":
            raise ValueError("reference_action must use action.position")
        for channel in (self.observation_state, self.reference_observation_state):
            if channel.semantics != "joint_angle" or channel.unit != "rad":
                raise ValueError("observation gripper channels must be joint angles in rad")
        for channel in (self.action, self.reference_action):
            if channel.semantics != "normalized_open" or channel.unit != "unitless":
                raise ValueError("action gripper channels must be normalized_open and unitless")
        return self


class TimingEvidence(BaseModel):
    """A value-free timing result bound to one source-data revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    group: str = Field(min_length=1)
    report_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    data_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    joint_indices: tuple[int, ...] = Field(min_length=1)
    action_scales: tuple[float, ...] = Field(min_length=1)
    action_offsets: tuple[float, ...] = Field(min_length=1)
    pairing: Literal["same_step"] = "same_step"
    shift_policy: Literal["none"] = "none"
    expected_shift_min: int = Field(ge=0)
    expected_shift_max: int = Field(ge=0)
    observed_best_shift: int = Field(ge=0)
    status: Literal["SUPPORTED", "CONFLICTED"]

    @model_validator(mode="after")
    def validate_timing_evidence(self) -> TimingEvidence:
        if len(set(self.joint_indices)) != len(self.joint_indices):
            raise ValueError("timing evidence joint indices must be unique")
        if any(index < 0 for index in self.joint_indices):
            raise ValueError("timing evidence joint indices must be non-negative")
        if len(self.action_scales) != len(self.joint_indices):
            raise ValueError("timing evidence scales do not match joint indices")
        if len(self.action_offsets) != len(self.joint_indices):
            raise ValueError("timing evidence offsets do not match joint indices")
        if any(not math.isfinite(value) or value == 0.0 for value in self.action_scales):
            raise ValueError("timing evidence scales must be finite and non-zero")
        if any(not math.isfinite(value) for value in self.action_offsets):
            raise ValueError("timing evidence offsets must be finite")
        if self.expected_shift_min > self.expected_shift_max:
            raise ValueError("timing evidence expected shift range is reversed")
        expected_status = (
            "SUPPORTED"
            if self.expected_shift_min <= self.observed_best_shift <= self.expected_shift_max
            else "CONFLICTED"
        )
        if self.status != expected_status:
            raise ValueError("timing evidence status does not match observed best shift")
        return self


class DataProfile(BaseModel):
    """Immutable, reviewable source semantics for one dataset revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    profile_id: str = Field(min_length=1)
    status: Literal["REVIEW_REQUIRED", "CERTIFIED"] = "REVIEW_REQUIRED"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    storage_adapter: Literal["lerobot_v3"] = "lerobot_v3"
    reader_version: str = Field(min_length=1)
    revision: DatasetRevision
    mapping: MappingSpec
    grippers: tuple[GripperProfile, ...] = Field(min_length=2, max_length=2)
    timing: tuple[TimingEvidence, ...] = Field(min_length=1)
    validation_scope: str = Field(min_length=1)
    evidence_scope: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = ()
    review_decision_sha256: Hash | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{64}$",
    )

    @model_validator(mode="after")
    def validate_profile_lineage(self) -> DataProfile:
        if self.mapping.dataset_alias != self.dataset_alias:
            raise ValueError("mapping dataset alias does not match profile")
        if self.mapping.source_revision != self.source_revision:
            raise ValueError("mapping source revision does not match profile")
        slots = tuple(item.slot for item in self.grippers)
        if set(slots) != {"slot_0", "slot_1"}:
            raise ValueError("profile must define exactly slot_0 and slot_1 grippers")
        groups = tuple(item.group for item in self.timing)
        if len(set(groups)) != len(groups):
            raise ValueError("profile timing groups must be unique")
        if any(item.data_sha256 != self.revision.data_sha256 for item in self.timing):
            raise ValueError("timing evidence data hash does not match profile revision")
        if self.status == "CERTIFIED":
            if self.review_decision_sha256 is None:
                raise ValueError("certified profile requires a review decision hash")
            if self.mapping.metadata.get("candidate_status") != "APPROVED":
                raise ValueError("certified profile requires an approved mapping")
            if self.mapping.coordinate_frame == "UNRESOLVED":
                raise ValueError("certified profile cannot have an unresolved frame")
        return self


class DataProfileVerification(BaseModel):
    """Value-free result of verifying one dataset profile and optional decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    status: Literal["VERIFIED"] = "VERIFIED"
    profile_id: str = Field(min_length=1)
    profile_status: Literal["REVIEW_REQUIRED", "CERTIFIED"]
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    profile_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    decision_sha256: Hash | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    decision_verified: bool = False
