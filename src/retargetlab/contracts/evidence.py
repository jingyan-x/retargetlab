"""Evidence and provenance types used by every semantic field."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvidenceLevel(StrEnum):
    """How strongly a value is supported by inspectable evidence."""

    EXPLICIT = "EXPLICIT"
    ADAPTER_CERTIFIED = "ADAPTER_CERTIFIED"
    DERIVED = "DERIVED"
    DATA_DERIVED = "DATA_DERIVED"
    INFERRED_CANDIDATE = "INFERRED_CANDIDATE"
    USER_CONFIRMED = "USER_CONFIRMED"
    MISSING = "MISSING"
    UNDEFINED = "UNDEFINED"


class Provenance(BaseModel):
    """Human-readable provenance without embedding private source values."""

    model_config = ConfigDict(extra="forbid")

    level: EvidenceLevel
    source: str = Field(min_length=1)
    note: str | None = None
    validation_scope: str | None = None

    @field_validator("source", "note", "validation_scope")
    @classmethod
    def reject_blank_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("provenance text must not be blank")
        return value


class SemanticField[ValueT](BaseModel):
    """A value together with its units, frame, and evidence level."""

    model_config = ConfigDict(extra="forbid")

    value: ValueT
    unit: str | None = None
    frame: str | None = None
    provenance: Provenance
