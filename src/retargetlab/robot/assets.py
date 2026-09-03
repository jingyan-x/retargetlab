"""Portable robot-asset path and hash validation."""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_asset_file(asset_dir: Path, relative_or_absolute: str) -> Path:
    """Resolve a profile path without allowing it to escape its asset root."""

    candidate = Path(relative_or_absolute)
    if candidate.is_absolute():
        return candidate
    return (asset_dir / candidate).resolve()


def load_manifest(asset_dir: Path) -> dict[str, Any]:
    """Load an asset manifest as an object and reject non-object JSON."""

    manifest_path = asset_dir / "asset_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read asset manifest: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("asset manifest must be a JSON object")
    return manifest


def _mesh_path(asset_dir: Path, filename: str) -> Path:
    if filename.startswith("package://"):
        package_relative = filename.removeprefix("package://").split("/", 1)
        if len(package_relative) != 2:
            raise ValueError(f"invalid package mesh URI: {filename}")
        filename = package_relative[1]
    if Path(filename).is_absolute() or PurePosixPath(filename).is_absolute():
        raise ValueError(f"absolute mesh path is not portable: {filename}")
    relative = PurePosixPath(filename)
    if ".." in relative.parts:
        raise ValueError(f"mesh path escapes asset directory: {filename}")
    return (asset_dir / Path(*relative.parts)).resolve()


def validate_urdf_meshes(asset_dir: Path, urdf_path: Path) -> list[str]:
    """Validate every URDF mesh reference and return normalized filenames."""

    try:
        root = ET.parse(urdf_path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f"cannot parse URDF: {urdf_path}") from exc
    references: list[str] = []
    asset_root = asset_dir.resolve()
    for mesh in root.iter():
        if mesh.tag.rsplit("}", 1)[-1] != "mesh":
            continue
        filename = mesh.get("filename")
        if not filename:
            raise ValueError("URDF mesh element has no filename")
        resolved = _mesh_path(asset_root, filename)
        try:
            resolved.relative_to(asset_root)
        except ValueError as exc:
            raise ValueError(f"mesh path escapes asset directory: {filename}") from exc
        if not resolved.is_file():
            raise FileNotFoundError(f"URDF mesh is missing: {resolved}")
        references.append(filename)
    return references


def verify_urdf_manifest(asset_dir: Path, manifest: dict[str, Any]) -> Path:
    """Check the manifest's generated URDF path and recorded SHA-256."""

    raw_path = manifest.get("generated_urdf_path")
    expected_hash = manifest.get("generated_urdf_sha256")
    if not isinstance(raw_path, str) or not isinstance(expected_hash, str):
        raise ValueError("manifest is missing generated URDF path or hash")
    urdf_path = resolve_asset_file(asset_dir, raw_path)
    if not urdf_path.is_file():
        raise FileNotFoundError(f"manifest URDF is missing: {urdf_path}")
    actual_hash = sha256_file(urdf_path)
    if actual_hash.lower() != expected_hash.lower():
        raise ValueError(
            f"URDF hash mismatch: expected {expected_hash.lower()}, got {actual_hash.lower()}"
        )
    validate_urdf_meshes(asset_dir, urdf_path)
    return urdf_path
