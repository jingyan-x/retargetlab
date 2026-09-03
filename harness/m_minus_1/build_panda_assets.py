"""Build a portable dual-Panda target asset for the target-reselection spike.

The official ``franka_description`` xacro remains the kinematic authority.  A
temporary staging tree supplies the ROS package lookup that is unavailable in
the remote conda environment, then the expanded URDF is normalized to bundled
relative mesh paths.  The dual-Panda example's table geometry is deliberately
removed: this bundle represents a robot target, while environment geometry is
outside the M-1 target model.
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


BUILD_SCHEMA = "m_minus_1.panda_assets.v1"
PACKAGE_URI_PREFIX = "package://franka_description/"
DEFAULT_ENTRY = Path("robots/dual_panda/dual_panda_example.urdf.xacro")
DEFAULT_URDF = Path("urdf/panda_bimanual.urdf")
SEMANTIC_POLICY_SOURCE = {
    "repository": "moveit/moveit_resources",
    "revision": "c55b102711fc0aebe80c6952d2ce97c38110abba",
    "path": "dual_arm_panda_moveit_config/config/panda.srdf",
}


def local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


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
    for directory in ("meshes", "robots"):
        source_directory = source / directory
        if not source_directory.is_dir():
            raise FileNotFoundError(f"missing upstream directory: {directory}")
        shutil.copytree(source_directory, stage / directory)

    for path in (stage / "robots").rglob("*.xacro"):
        text = path.read_text(encoding="utf-8")
        patched = text.replace("$(find franka_description)", str(stage))
        path.write_text(patched, encoding="utf-8")


def remove_environment_base(root: ET.Element) -> None:
    base = next(
        (
            element
            for element in root
            if local_tag(element) == "link" and element.get("name") == "base"
        ),
        None,
    )
    if base is None:
        raise ValueError("dual Panda xacro did not produce the expected base link")
    for child in list(base):
        if local_tag(child) in {"visual", "collision"}:
            base.remove(child)


def normalize_mesh_references(root: ET.Element) -> list[str]:
    references: set[str] = set()
    for element in root.iter():
        if local_tag(element) != "mesh":
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
    if local_tag(root) != "robot":
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
    if not source.is_dir():
        raise FileNotFoundError(f"source is not a directory: {source}")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    script_path = Path(__file__).resolve()
    with tempfile.TemporaryDirectory(prefix="panda-xacro-", dir=output.parent) as temp:
        stage = Path(temp) / "franka_description"
        stage.mkdir()
        stage_source(source, stage)
        entry_path = stage / entry
        if not entry_path.is_file():
            raise FileNotFoundError(f"xacro entry is missing: {entry}")

        document = xacro.process_file(str(entry_path))
        root = ET.fromstring(document.toxml())
        remove_environment_base(root)
        references = normalize_mesh_references(root)
        copy_meshes(source, output, references)
        urdf_path = output / DEFAULT_URDF
        urdf_path.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(root).write(urdf_path, encoding="utf-8", xml_declaration=True)

    srdf_relative_path, srdf_hash = copy_srdf(srdf, output)
    manifest = {
        "schema_version": BUILD_SCHEMA,
        "asset_role": "target_reselection_spike_only",
        "source_repository": "frankarobotics/franka_ros",
        "source_revision": git_revision(source),
        "source_subdirectory": "franka_description",
        "xacro_entry": entry.as_posix(),
        "generated_urdf_path": DEFAULT_URDF.as_posix(),
        "build_script_sha256": sha256_file(script_path),
        "generated_urdf_sha256": sha256_file(urdf_path),
        "srdf_path": srdf_relative_path,
        "srdf_sha256": srdf_hash,
        "semantic_policy_source": SEMANTIC_POLICY_SOURCE,
        "mesh_count": len(references),
        "mesh_paths": references,
        "root_link": "base",
        "base_mounts": {
            "panda_1": {"xyz_m": [0.0, -0.5, 1.0], "rpy_rad": [0.0, 0.0, 0.0]},
            "panda_2": {"xyz_m": [0.0, 0.5, 1.0], "rpy_rad": [0.0, 0.0, 0.0]},
        },
        "tcp_frames": ["panda_1_hand_tcp", "panda_2_hand_tcp"],
        "flange_frames": ["panda_1_link8", "panda_2_link8"],
        "dataset_side_mapping": {
            "dataset_left": "panda_2",
            "dataset_right": "panda_1",
            "basis": "dual-example comments identify panda_1 at y=-0.5 as right and panda_2 at y=0.5 as left",
        },
        "environment_geometry": "removed_from_base_link",
        "collision_geometry_strategy": "coarse_sc_links_plus_finger_primitives",
        "portability_rules": [
            "resolve upstream find substitution in a temporary staging tree",
            "retain only meshes referenced by the expanded URDF",
            "rewrite package://franka_description/ references to relative paths",
            "reject absolute paths and paths outside meshes/",
            "do not bundle the upstream dual-example table as robot collision geometry",
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
    parser.add_argument("--srdf", type=Path)
    args = parser.parse_args()
    manifest = build(args.source, args.output, args.entry, args.srdf)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
