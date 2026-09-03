"""Compare declared metadata with value-free physical structure."""

from __future__ import annotations

from retargetlab.contracts import (
    DatasetInfoManifest,
    StructureComparison,
    StructureManifest,
)


def _canonical_dtype(dtype: str) -> str:
    normalized = dtype.strip().lower()
    return {
        "float": "float32",
        "float32": "float32",
        "double": "float64",
        "float64": "float64",
        "int": "int64",
        "uint": "uint64",
    }.get(normalized, normalized)


def compare_info_to_structure(
    info: DatasetInfoManifest,
    structure: StructureManifest,
) -> StructureComparison:
    """Classify metadata/Parquet agreement without reading any row values."""

    declared_fields = {
        name: feature for name, feature in info.features.items() if feature.storage == "parquet"
    }
    missing: list[str] = []
    dtype_mismatches: list[str] = []
    shape_mismatches: list[str] = []
    shape_unverified: list[str] = []
    shape_normalized: list[str] = []
    for name, feature in sorted(declared_fields.items()):
        field = structure.fields.get(name)
        if field is None:
            missing.append(name)
            continue
        if _canonical_dtype(feature.dtype) != _canonical_dtype(field.dtype):
            dtype_mismatches.append(f"{name}: declared {feature.dtype}, got {field.dtype}")
        if feature.shape == (1,) and field.shape == ():
            shape_normalized.append(name)
        elif feature.shape is None or field.shape is None:
            shape_unverified.append(name)
        elif feature.shape != field.shape:
            shape_mismatches.append(f"{name}: declared {feature.shape}, got {field.shape}")

    alias_match = info.dataset_alias == structure.dataset_alias
    revision_match = info.source_revision == structure.source_revision
    row_count_match = info.total_frames == structure.row_count
    compatible = (
        alias_match
        and revision_match
        and row_count_match
        and not missing
        and not dtype_mismatches
        and not shape_mismatches
    )
    return StructureComparison(
        compatible=compatible,
        fully_verified=compatible and not shape_unverified and not shape_normalized,
        alias_match=alias_match,
        revision_match=revision_match,
        row_count_match=row_count_match,
        declared_total_frames=info.total_frames,
        observed_row_count=structure.row_count,
        missing_features=tuple(missing),
        dtype_mismatches=tuple(dtype_mismatches),
        shape_mismatches=tuple(shape_mismatches),
        shape_unverified=tuple(shape_unverified),
        shape_normalized=tuple(shape_normalized),
        extra_fields=tuple(sorted(set(structure.fields) - set(declared_fields))),
    )
