"""Validate explicit mappings against value-free structure manifests."""

from __future__ import annotations

from collections.abc import Iterator

from retargetlab.contracts import (
    ColumnRef,
    MappingSpec,
    MappingValidation,
    StructureField,
    StructureManifest,
)


def _references(spec: MappingSpec) -> Iterator[tuple[str, ColumnRef]]:
    yield "timestamp", spec.timestamp
    for stream in spec.streams:
        for field_name, reference in stream.fields.items():
            yield f"{stream.name}.{field_name}", reference


def _check_reference(
    label: str,
    reference: ColumnRef,
    field: StructureField | None,
    missing: list[str],
    shape_mismatches: list[str],
    index_errors: list[str],
) -> None:
    if field is None:
        missing.append(f"{label}: {reference.source}")
        return
    if reference.expected_shape is not None and field.shape != reference.expected_shape:
        shape_mismatches.append(f"{label}: expected {reference.expected_shape}, got {field.shape}")
    if reference.indices:
        if field.shape is None:
            index_errors.append(f"{label}: source width is unknown")
        elif not field.shape:
            index_errors.append(f"{label}: scalar field cannot be indexed")
        elif max(reference.indices) >= field.shape[-1]:
            index_errors.append(
                f"{label}: index {max(reference.indices)} exceeds width {field.shape[-1]}"
            )


def validate_mapping(
    spec: MappingSpec,
    manifest: StructureManifest,
) -> MappingValidation:
    """Check paths, shapes, indices, alias, and source revision without values."""

    missing: list[str] = []
    shape_mismatches: list[str] = []
    index_errors: list[str] = []
    for label, reference in _references(spec):
        _check_reference(
            label,
            reference,
            manifest.fields.get(reference.source),
            missing,
            shape_mismatches,
            index_errors,
        )
    alias_match = spec.dataset_alias == manifest.dataset_alias
    revision_match = spec.source_revision == manifest.source_revision
    return MappingValidation(
        valid=alias_match
        and revision_match
        and not missing
        and not shape_mismatches
        and not index_errors,
        alias_match=alias_match,
        revision_match=revision_match,
        missing_sources=tuple(missing),
        shape_mismatches=tuple(shape_mismatches),
        index_errors=tuple(index_errors),
    )
