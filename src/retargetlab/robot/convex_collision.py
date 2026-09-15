"""Build a separate, auditable convex collision proxy without changing visuals."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path

from retargetlab.robot.assets import sha256_file
from retargetlab.robot.mujoco_model import MujocoKinematics

PRESET = dict(
    threshold=0.002,
    real_metric=True,
    max_convex_hull=32,
    preprocess_resolution=100,
    resolution=2000,
    mcts_nodes=20,
    mcts_iterations=150,
    mcts_max_depth=3,
    merge=True,
    decimate=False,
    seed=20260913,
)


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def _decompose(job):
    os.environ["OMP_NUM_THREADS"] = "2"
    import coacd
    import trimesh

    source, output = Path(job["source"]), Path(job["output"])
    mesh = trimesh.load_mesh(source, process=True)
    kwargs = {
        **PRESET,
        "preprocess_mode": "off" if mesh.is_watertight and mesh.is_winding_consistent else "auto",
    }
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "source_sha256": sha256_file(source),
        "preset": kwargs,
        "source_vertices": len(mesh.vertices),
        "source_faces": len(mesh.faces),
        "source_watertight": bool(mesh.is_watertight),
        "source_winding_consistent": bool(mesh.is_winding_consistent),
        "preprocessing_may_change_surface": kwargs["preprocess_mode"] == "auto",
    }
    _write(output / "input.json", report)
    coacd.set_log_level("warn")
    started = time.monotonic()
    parts = coacd.run_coacd(coacd.Mesh(mesh.vertices, mesh.faces), **kwargs)
    if not parts:
        raise ValueError("CoACD returned no convex components")
    files = {}
    for i, (vertices, faces) in enumerate(parts):
        path = output / f"part-{i:03d}.obj"
        trimesh.Trimesh(vertices, faces, process=False).export(
            path,
            file_type="obj",
            digits=17,
            include_normals=False,
            include_color=False,
            include_texture=False,
        )
        files[path.name] = sha256_file(path)
    report.update(
        status="COMPLETED_APPROXIMATION",
        files=files,
        parts=len(parts),
        part_cap_reached=len(parts) >= PRESET["max_convex_hull"],
        elapsed_s=time.monotonic() - started,
        tolerance_is_not_a_certified_surface_error_bound=True,
    )
    _write(output / "report.json", report)
    return str(output)


def derive_models(config_path: Path, cache: Path, *, workers=2):
    """An explicit selected-geometry preset; no collision-pair policy changes."""
    import mujoco

    configs = json.loads(config_path.read_text())
    jobs, plans = {}, []
    for config in configs:
        source, output = Path(config["model"]), Path(config["output"])
        if output.exists() or output.resolve().is_relative_to(source.resolve()):
            raise ValueError("convex model output must be a new directory outside its source")
        engine = MujocoKinematics(source)
        tree = ET.parse(source / engine.metadata["model_path"])
        assets = {m.get("name"): m for m in tree.findall(".//asset/mesh")}
        geoms = {g.get("name"): g for g in tree.findall(".//geom") if g.get("name")}
        selections = {}
        for name in config["geometry_names"]:
            if not name.startswith("collision__") or name not in geoms:
                raise ValueError("select existing collision geoms by exact name")
            asset = assets[geoms[name].get("mesh")]
            if set(asset.attrib) - {"name", "file", "content_type"}:
                raise ValueError("mesh transforms require explicit reconciliation")
            path = source / asset.get("file")
            key = hashlib.sha256(
                (sha256_file(path) + json.dumps(PRESET, sort_keys=True)).encode()
            ).hexdigest()[:24]
            jobs[key] = {"source": str(path), "output": str(cache / key)}
            selections[name] = key
        plans.append((source, output, engine.metadata, tree, selections))
    pending = []
    for key, job in jobs.items():
        path = Path(job["output"]) / "report.json"
        if path.exists():
            report = json.loads(path.read_text())
            if report["source_sha256"] != sha256_file(Path(job["source"])):
                raise ValueError("convex cache source mismatch")
            for name, digest in report["files"].items():
                if sha256_file(path.parent / name) != digest:
                    raise ValueError("convex cache component changed")
        else:
            pending.append(job)
    print(f"convex jobs: {len(jobs)} unique meshes, {len(pending)} pending", flush=True)
    cache.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as pool:
        for path in pool.map(_decompose, pending):
            report = json.loads((Path(path) / "report.json").read_text())
            print(Path(path).name, report["parts"], report["elapsed_s"], flush=True)
    for source, output, metadata, tree, selections in plans:
        shutil.copytree(source, output)
        shutil.copy2(source / "manifest.json", output / "upstream-manifest.json")
        xml = tree.getroot()
        assets = xml.find("asset")
        reports = {}
        for key in set(selections.values()):
            report = json.loads((cache / key / "report.json").read_text())
            reports[key] = report
            target = output / "collision-convex" / key
            target.mkdir(parents=True)
            for i, name in enumerate(report["files"]):
                shutil.copy2(cache / key / name, target / name)
                ET.SubElement(
                    assets,
                    "mesh",
                    name=f"convex_{key}_{i:03d}",
                    file=f"collision-convex/{key}/{name}",
                )
        old_mapping = {g["name"]: g for g in metadata["geometry_mapping"]}
        mapping = [g for g in metadata["geometry_mapping"] if g["name"] not in selections]
        for body in xml.findall(".//body"):
            for geom in list(body.findall("geom")):
                original = geom.get("name")
                if original not in selections:
                    continue
                key = selections[original]
                entry = old_mapping[original]
                source_name = f"{entry['link']}_{original.rsplit('__', 1)[1]}"
                for i in range(reports[key]["parts"]):
                    new = copy.deepcopy(geom)
                    new_name = f"{original}__part{i:03d}"
                    new.set("name", new_name)
                    new.set("mesh", f"convex_{key}_{i:03d}")
                    body.append(new)
                    mapping.append(
                        {
                            "name": new_name,
                            "link": entry["link"],
                            "kind": "collision",
                            "source_geometry_name": source_name,
                        }
                    )
                body.remove(geom)
        tree.write(output / metadata["model_path"], encoding="utf-8", xml_declaration=True)
        model = mujoco.MjModel.from_xml_path(str(output / metadata["model_path"]))
        metadata = {
            **metadata,
            "geometries": model.ngeom,
            "geometry_mapping": mapping,
            "collision_status": "PARTIAL_COACD_PROXY_REQUIRES_INDEPENDENT_POSTCHECK",
            "collision_proxy": {
                "upstream_manifest_sha256": sha256_file(source / "manifest.json"),
                "selected_geometries": selections,
                "decompositions": reports,
                "selection": (
                    "geometries in extra native contact pairs on the existing development audit"
                ),
                "pair_filter_policy_changed": False,
                "visual_geometry_changed": False,
                "preset_is_not_a_certified_error_bound": True,
            },
        }
        _write(output / "mujoco-model.json", metadata)
        _write(
            output / "manifest.json",
            {
                "status": "COMPLETED",
                "files": {
                    p.relative_to(output).as_posix(): sha256_file(p)
                    for p in output.rglob("*")
                    if p.is_file() and p.name != "manifest.json"
                },
            },
        )
        checked = MujocoKinematics(output)
        assert checked.model.nq == metadata["nq"] and checked.model.nv == metadata["nv"]
        print(str(output), model.ngeom, "geoms", flush=True)
    return [str(plan[1]) for plan in plans]
