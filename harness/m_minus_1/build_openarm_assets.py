"""Build a portable OpenArm bimanual URDF for the disposable M-1 harness.

The upstream xacro is the kinematic authority.  The build only patches the
package lookup needed outside a ROS installation, expands the xacro, converts
mesh references to paths relative to the generated asset directory, and
records hashes for provenance.  It deliberately does not import ``src/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import xacro

BUILD_SCHEMA = "m_minus_1.openarm_assets.v1"
PACKAGE_URI_PREFIX = "package://openarm_description/"
DEFAULT_ENTRY = Path("urdf/robot/v10.urdf.xacro")
DEFAULT_SRDF = Path("urdf/robot/self_collision/openarm.srdf")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_revision(source: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def stage_source(source: Path, stage: Path) -> None:
    for directory in ("config", "meshes", "urdf"):
        source_directory = source / directory
        if not source_directory.is_dir():
            raise FileNotFoundError(f"missing upstream directory: {directory}")
        shutil.copytree(source_directory, stage / directory)

    for path in (stage / "urdf").rglob("*.xacro"):
        text = path.read_text(encoding="utf-8")
        patched = text.replace("$(find openarm_description)", str(stage))
        path.write_text(patched, encoding="utf-8")


def normalize_mesh_references(root: ET.Element) -> list[str]:
    references: set[str] = set()
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "mesh":
            continue
        filename = element.get("filename")
        if not filename:
            raise ValueError("mesh element has no filename")
        filename = filename.removeprefix(PACKAGE_URI_PREFIX)
        if Path(filename).is_absolute():
            raise ValueError(f"absolute mesh path survived expansion: {filename}")
        filename = filename.replace("\\", "/").lstrip("./")
        if not filename.startswith("meshes/"):
            raise ValueError(f"mesh is outside the bundled meshes tree: {filename}")
        element.set("filename", filename)
        references.add(filename)
    return sorted(references)


def copy_meshes(source: Path, output: Path, references: list[str]) -> None:
    for relative_name in references:
        source_file = source / relative_name
        if not source_file.is_file():
            raise FileNotFoundError(f"referenced mesh is missing: {relative_name}")
        target_file = output / relative_name
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)


def copy_srdf(srdf: Path | None, output: Path) -> tuple[str | None, str | None]:
    if srdf is None:
        return None, None

    srdf = srdf.resolve()
    if not srdf.is_file():
        raise FileNotFoundError(f"SRDF input is missing: {srdf}")
    try:
        root = ET.parse(srdf).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f"SRDF input is not valid XML: {srdf}") from exc
    if root.tag.rsplit("}", 1)[-1] != "robot":
        raise ValueError("SRDF input must have a robot root element")

    relative_path = Path("srdf") / srdf.name
    target = output / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(srdf, target)
    return relative_path.as_posix(), sha256_file(srdf)


def build(
    source: Path,
    output: Path,
    entry: Path,
    srdf: Path | None,
) -> dict[str, Any]:
    source = source.resolve()
    output = output.resolve()
    entry = entry.as_posix()
    if not source.is_dir():
        raise FileNotFoundError(f"source is not a directory: {source}")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    script_path = Path(__file__).resolve()
    with tempfile.TemporaryDirectory(prefix="openarm-xacro-", dir=output.parent) as temp:
        stage = Path(temp) / "openarm_description"
        stage.mkdir()
        stage_source(source, stage)
        entry_path = stage / entry
        if not entry_path.is_file():
            raise FileNotFoundError(f"xacro entry is missing: {entry}")

        document = xacro.process_file(
            str(entry_path),
            mappings={"bimanual": "true", "hand": "true", "ros2_control": "false"},
        )
        root = ET.fromstring(document.toxml())
        references = normalize_mesh_references(root)
        copy_meshes(source, output, references)
        urdf_path = output / "urdf" / "openarm_bimanual_v10.urdf"
        urdf_path.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(root).write(urdf_path, encoding="utf-8", xml_declaration=True)

    srdf_relative_path, srdf_hash = copy_srdf(srdf, output)

    manifest = {
        "schema_version": BUILD_SCHEMA,
        "source_repository": "enactic/openarm_description",
        "source_revision": git_revision(source),
        "xacro_entry": entry,
        "build_script_sha256": sha256_file(script_path),
        "generated_urdf_sha256": sha256_file(urdf_path),
        "srdf_path": srdf_relative_path,
        "srdf_sha256": srdf_hash,
        "mesh_count": len(references),
        "mesh_paths": references,
        "portability_rules": [
            "resolve upstream find substitution in a temporary staging tree",
            "retain only meshes referenced by the expanded URDF",
            "rewrite package://openarm_description/ references to relative paths",
            "reject absolute paths and paths outside meshes/",
        ],
    }
    manifest_path = output / "asset_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--entry", type=Path, default=DEFAULT_ENTRY)
    parser.add_argument(
        "--srdf",
        type=Path,
        help="optional SRDF policy to bundle and record in the asset manifest",
    )
    args = parser.parse_args()
    manifest = build(args.source, args.output, args.entry, args.srdf)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
