"""Parquet schema probing without reading row values."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from retargetlab.contracts import StructureField, StructureManifest
from retargetlab.robot.assets import sha256_file


def _field_shape(arrow_type: Any) -> tuple[tuple[int, ...] | None, str]:
    try:
        import pyarrow as pa  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("pyarrow is required for Parquet structure probing") from exc
    if pa.types.is_fixed_size_list(arrow_type):
        return (int(arrow_type.list_size),), str(arrow_type.value_type)
    if pa.types.is_list(arrow_type) or pa.types.is_large_list(arrow_type):
        return None, str(arrow_type.value_type)
    return (), str(arrow_type)


def probe_parquet(
    path: Path,
    *,
    dataset_alias: str,
    source_revision: str,
) -> StructureManifest:
    """Return schema metadata and file hash without materializing any rows."""

    if not path.is_file():
        raise FileNotFoundError(f"Parquet file does not exist: {path}")
    try:
        import pyarrow.parquet as parquet  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("pyarrow is required for Parquet structure probing") from exc

    parquet_file = parquet.ParquetFile(path)
    fields: dict[str, StructureField] = {}
    for field in parquet_file.schema_arrow:
        shape, dtype = _field_shape(field.type)
        fields[field.name] = StructureField(dtype=dtype, shape=shape)
    metadata = parquet_file.metadata
    if metadata is None or metadata.num_rows <= 0:
        raise ValueError("Parquet file must contain at least one row")
    return StructureManifest(
        dataset_alias=dataset_alias,
        source_revision=source_revision,
        source_sha256=sha256_file(path),
        row_count=int(metadata.num_rows),
        fields=fields,
    )
