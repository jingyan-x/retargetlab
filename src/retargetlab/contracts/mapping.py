"""Explicit source-field mapping and structure-manifest contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ColumnRef(BaseModel):
    """One source field reference with optional vector-index checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(min_length=1)
    expected_shape: tuple[int, ...] | None = None
    indices: tuple[int, ...] = ()
    unit: str | None = None
    frame: str | None = None
    quaternion_order: Literal["wxyz", "xyzw"] | None = None

    @model_validator(mode="after")
    def validate_shape_and_indices(self) -> ColumnRef:
        if self.expected_shape is not None and any(size < 0 for size in self.expected_shape):
            raise ValueError("expected_shape dimensions must be non-negative")
        if any(index < 0 for index in self.indices):
            raise ValueError("column indices must be non-negative")
        if len(set(self.indices)) != len(self.indices):
            raise ValueError("column indices must be unique")
        return self


class StreamMapping(BaseModel):
    """All explicit field references for one source stream."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    role: Literal["robot_state", "command"]
    fields: dict[str, ColumnRef] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_field_names(self) -> StreamMapping:
        if any(not name.strip() for name in self.fields):
            raise ValueError("mapping field names must not be blank")
        return self


class MappingSpec(BaseModel):
    """Versioned mapping from a source structure into canonical fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    coordinate_frame: str = Field(min_length=1)
    timestamp: ColumnRef
    streams: tuple[StreamMapping, ...] = Field(min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_streams(self) -> MappingSpec:
        names = [stream.name for stream in self.streams]
        if len(set(names)) != len(names):
            raise ValueError("mapping stream names must be unique")
        return self


class StructureField(BaseModel):
    """Shape metadata for one source field; values are intentionally absent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dtype: str = Field(min_length=1)
    shape: tuple[int, ...] | None

    @model_validator(mode="after")
    def validate_shape(self) -> StructureField:
        if self.shape is not None and any(size < 0 for size in self.shape):
            raise ValueError("structure field dimensions must be non-negative")
        return self


class StructureManifest(BaseModel):
    """Read-only source structure summary produced by a future prober."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    row_count: int = Field(gt=0)
    fields: dict[str, StructureField] = Field(min_length=1)


class FeatureDeclaration(BaseModel):
    """Value-free feature declaration from a dataset metadata manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dtype: str = Field(min_length=1)
    shape: tuple[int, ...] | None
    names: tuple[str, ...] = ()
    storage: Literal["parquet", "external"] = "parquet"

    @model_validator(mode="after")
    def validate_shape(self) -> FeatureDeclaration:
        if self.shape is not None and any(size < 0 for size in self.shape):
            raise ValueError("feature declaration dimensions must be non-negative")
        return self


class DatasetInfoManifest(BaseModel):
    """Selected metadata from a LeRobot-style ``info.json`` manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    dataset_name: str = Field(min_length=1)
    total_episodes: int = Field(gt=0)
    total_frames: int = Field(gt=0)
    total_tasks: int = Field(gt=0)
    total_chunks: int = Field(gt=0)
    fps: float = Field(gt=0)
    features: dict[str, FeatureDeclaration] = Field(min_length=1)


class StructureComparison(BaseModel):
    """Explicit comparison between declared features and physical columns."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    compatible: bool
    fully_verified: bool
    alias_match: bool
    revision_match: bool
    row_count_match: bool
    declared_total_frames: int = Field(gt=0)
    observed_row_count: int = Field(gt=0)
    missing_features: tuple[str, ...] = ()
    dtype_mismatches: tuple[str, ...] = ()
    shape_mismatches: tuple[str, ...] = ()
    shape_unverified: tuple[str, ...] = ()
    shape_normalized: tuple[str, ...] = ()
    extra_fields: tuple[str, ...] = ()


class ReviewEvidenceChecklist(BaseModel):
    """Explicit evidence checklist attached to an approved semantic review."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    structure_evidence_reviewed: bool = False
    coordinate_frame_confirmed: bool = False
    position_unit_confirmed: bool = False
    timestamp_unit_confirmed: bool = False
    orientation_order_confirmed: bool = False
    slot_labels_confirmed: bool = False
    target_groups_confirmed: bool = False
    shape_acceptance: Literal["NOT_REQUIRED", "ACCEPTED", "REJECTED"] = "NOT_REQUIRED"

    def semantics_complete(self) -> bool:
        """Return whether all non-shape semantic evidence is explicitly confirmed."""

        return all(
            (
                self.structure_evidence_reviewed,
                self.coordinate_frame_confirmed,
                self.position_unit_confirmed,
                self.timestamp_unit_confirmed,
                self.orientation_order_confirmed,
                self.slot_labels_confirmed,
                self.target_groups_confirmed,
            )
        )


class MappingReview(BaseModel):
    """Explicit human review required before a candidate becomes executable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    coordinate_frame: str = Field(min_length=1)
    position_unit: Literal["m"]
    timestamp_unit: Literal["s"]
    orientation_quaternion_order: Literal["wxyz"]
    slot_labels: dict[str, str] = Field(min_length=2, max_length=2)
    target_group_by_slot: dict[str, str] = Field(min_length=2, max_length=2)
    evidence: tuple[str, ...] = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    accept_unverified_shape: bool = False
    approved: bool = False
    checklist: ReviewEvidenceChecklist | None = None

    @model_validator(mode="after")
    def validate_slots(self) -> MappingReview:
        expected = {"slot_0", "slot_1"}
        if set(self.slot_labels) != expected:
            raise ValueError("slot_labels must define exactly slot_0 and slot_1")
        if set(self.target_group_by_slot) != expected:
            raise ValueError("target_group_by_slot must define exactly slot_0 and slot_1")
        values = (*self.slot_labels.values(), *self.target_group_by_slot.values())
        if any(not value.strip() for value in values):
            raise ValueError("slot labels and target groups must not be blank")
        if len(set(self.slot_labels.values())) != 2:
            raise ValueError("slot labels must be unique")
        if self.approved:
            if self.checklist is None:
                raise ValueError("approved review requires an evidence checklist")
            if not self.checklist.semantics_complete():
                raise ValueError("approved review has incomplete evidence checklist")
            if self.checklist.shape_acceptance == "REJECTED":
                raise ValueError("approved review rejects source shapes")
            if self.accept_unverified_shape and self.checklist.shape_acceptance != "ACCEPTED":
                raise ValueError("shape acceptance must be ACCEPTED when enabled")
        return self


class ReviewPackageInspection(BaseModel):
    """Read-only status of a candidate, review, and structure evidence package."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    status: Literal["PENDING_REVIEW", "REVIEW_APPROVED", "BLOCKED"]
    next_action: Literal["REVIEW_SEMANTICS", "APPLY_APPROVED_REVIEW", "REPAIR_EVIDENCE"]
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    candidate_status: str = Field(min_length=1)
    review_approved: bool
    structure_compatible: bool
    structure_fully_verified: bool
    shape_unverified: tuple[str, ...] = ()
    checklist_present: bool
    checklist_semantics_complete: bool
    shape_acceptance: Literal["NOT_REQUIRED", "ACCEPTED", "REJECTED"]
    shape_decision_required: bool
    ready_for_semantic_review: bool
    can_apply_review: bool
    review_evidence_count: int = Field(ge=0)
    blocking_reasons: tuple[str, ...] = ()


class ReviewPackagePreflightArtifact(BaseModel):
    """Value-free, exclusive record of one review-package preflight."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["review_package_preflight"] = "review_package_preflight"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    candidate_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    review_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    comparison_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    inspection: ReviewPackageInspection

    @model_validator(mode="after")
    def validate_lineage(self) -> ReviewPackagePreflightArtifact:
        if self.inspection.dataset_alias != self.dataset_alias:
            raise ValueError("inspection dataset alias does not match preflight")
        if self.inspection.source_revision != self.source_revision:
            raise ValueError("inspection source revision does not match preflight")
        return self


class ReviewPackagePreflightVerification(BaseModel):
    """Value-free result of verifying a saved review-package preflight."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    status: Literal["VERIFIED"] = "VERIFIED"
    dataset_alias: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    preflight_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    candidate_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    review_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    comparison_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    inspection_status: Literal["PENDING_REVIEW", "REVIEW_APPROVED", "BLOCKED"]
    can_apply_review: bool


class MappingValidation(BaseModel):
    """Machine-readable result of mapping a spec onto a structure manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    alias_match: bool
    revision_match: bool
    missing_sources: tuple[str, ...] = ()
    shape_mismatches: tuple[str, ...] = ()
    index_errors: tuple[str, ...] = ()
