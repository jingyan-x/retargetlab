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


class MappingValidation(BaseModel):
    """Machine-readable result of mapping a spec onto a structure manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    alias_match: bool
    revision_match: bool
    missing_sources: tuple[str, ...] = ()
    shape_mismatches: tuple[str, ...] = ()
    index_errors: tuple[str, ...] = ()
