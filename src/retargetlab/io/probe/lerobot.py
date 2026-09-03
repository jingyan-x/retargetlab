"""Read-only probing for LeRobot-style dataset metadata manifests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from retargetlab.contracts import DatasetInfoManifest, FeatureDeclaration
from retargetlab.robot.assets import sha256_file


def _shape(value: Any, *, label: str) -> tuple[int, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(
        not isinstance(item, int) or isinstance(item, bool) or item < 0 for item in value
    ):
        raise ValueError(f"{label} must be a list of non-negative integers")
    return tuple(value)


def _names(value: Any, *, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of strings")
    return tuple(value)


def _required_text(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"metadata field must be a non-empty string: {key}")
    return value


def _required_int(raw: dict[str, Any], key: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"metadata field must be a positive integer: {key}")
    return value


def _required_float(raw: dict[str, Any], key: str) -> float:
    value = raw.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"metadata field must be a positive number: {key}")
    return float(value)


def probe_lerobot_info(
    path: Path,
    *,
    dataset_alias: str,
    source_revision: str,
) -> DatasetInfoManifest:
    """Return declared dataset metadata without opening data or video rows."""

    if not path.is_file():
        raise FileNotFoundError(f"metadata manifest does not exist: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("metadata manifest must contain a JSON object")
    raw_features = raw.get("features")
    if not isinstance(raw_features, dict) or not raw_features:
        raise ValueError("metadata manifest must contain a non-empty features object")

    features: dict[str, FeatureDeclaration] = {}
    for name, payload in raw_features.items():
        if not isinstance(name, str) or not name:
            raise ValueError("feature names must be non-empty strings")
        if not isinstance(payload, dict):
            raise ValueError(f"feature declaration must be an object: {name}")
        dtype = payload.get("dtype")
        if not isinstance(dtype, str) or not dtype:
            raise ValueError(f"feature dtype must be a non-empty string: {name}")
        features[name] = FeatureDeclaration(
            dtype=dtype,
            shape=_shape(payload.get("shape"), label=f"feature shape: {name}"),
            names=_names(payload.get("names"), label=f"feature names: {name}"),
            storage="external" if dtype.lower() == "video" else "parquet",
        )

    return DatasetInfoManifest(
        dataset_alias=dataset_alias,
        source_revision=source_revision,
        source_sha256=sha256_file(path),
        dataset_name=_required_text(raw, "dataset_name"),
        total_episodes=_required_int(raw, "total_episodes"),
        total_frames=_required_int(raw, "total_frames"),
        total_tasks=_required_int(raw, "total_tasks"),
        total_chunks=_required_int(raw, "total_chunks"),
        fps=_required_float(raw, "fps"),
        features=features,
    )
