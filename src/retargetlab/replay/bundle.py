"""Fingerprint-bound saved-configuration replay; this module never invokes IK."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np

from retargetlab.contracts import RobotProfile
from retargetlab.kinematics.transforms import quaternion_geodesic_angle_rad
from retargetlab.robot.mujoco_model import MujocoKinematics
from retargetlab.run.process import canonical_frame, load_config, select_rows


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")


def verify_files(root, names=None, manifest_path="manifest.json"):
    manifest = read(root / manifest_path)
    for name in names or manifest["files"]:
        if digest(root / name) != manifest["files"][name]:
            raise ValueError(f"artifact fingerprint changed: {root / name}")


def visual_bounds(engine):
    visible = engine.model.geom_group == 1
    rot = engine.data.geom_xmat[visible].reshape(-1, 3, 3)
    box = engine.model.geom_aabb[visible]
    center = engine.data.geom_xpos[visible] + np.einsum("nij,nj->ni", rot, box[:, :3])
    half = np.einsum("nij,nj->ni", np.abs(rot), box[:, 3:])
    return (center - half).min(axis=0), (center + half).max(axis=0)


def quality_index(dataset, processing):
    import pyarrow.parquet as pq

    if dataset is None:
        return None
    plan = read(dataset / "retarget/plan.json")
    if plan["processing_manifest_sha256"] != digest(processing / "manifest.json"):
        raise ValueError("quality dataset belongs to another processing run")
    names = ["retarget/plan.json", "retarget/quality.parquet", "retarget/report.json"]
    names += [str(p.relative_to(dataset)) for p in sorted((dataset / "data").rglob("*.parquet"))]
    verify_files(dataset, names, "retarget/manifest.json")
    rows = pq.read_table(dataset / "retarget/quality.parquet").to_pylist()
    quality = {}
    pair = {}
    for row in rows:
        key = (row["source_episode_index"], row["frame_index"], row["stream"])
        if key in quality:
            raise ValueError("duplicate quality key")
        quality[key] = row
        pair.setdefault(key[:2], []).append(bool(row["training_eligible"]))
    if any(len(flags) != 2 for flags in pair.values()):
        raise ValueError("quality must cover both streams")
    mapping = {
        int(k): v
        for k, v in read(dataset / "retarget/report.json")["source_episode_mapping"].items()
    }
    inverse = {v: k for k, v in mapping.items()}
    masks = pq.read_table(
        dataset / "data", columns=["episode_index", "frame_index", "valid.retarget"]
    ).to_pylist()
    for row in masks:
        key = (inverse[row["episode_index"]], row["frame_index"])
        value = row["valid.retarget"]
        if isinstance(value, list):
            value = value[0]
        if float(value) != float(all(pair.pop(key))):
            raise ValueError("joint eligibility mask disagrees with saved quality")
    if pair:
        raise ValueError("missing training mask rows")
    return quality


def build(config_path: Path, output: Path):
    import mujoco
    import pyarrow.parquet as pq

    entries = read(config_path)
    ids = [entry["id"] for entry in entries]
    if (
        not ids
        or len(set(ids)) != len(ids)
        or any(not re.fullmatch(r"[a-z0-9_-]+", i) for i in ids)
    ):
        raise ValueError("replay IDs must be unique lowercase identifiers")
    if output.exists():
        raise ValueError("use a new replay bundle directory")
    output.mkdir(parents=True)
    catalog = {"schema_version": "saved_q_replay.0.1", "runs": [], "files": {}, "sources": {}}
    total = 0
    for entry in entries:
        if set(entry) - {"id", "processing_run", "model", "quality_dataset", "label"}:
            raise ValueError("unknown replay config field")
        processing = (config_path.resolve().parent / entry["processing_run"]).resolve()
        model_dir = (config_path.resolve().parent / entry["model"]).resolve()
        dataset = (
            (config_path.resolve().parent / entry["quality_dataset"]).resolve()
            if entry.get("quality_dataset")
            else None
        )
        verify_files(processing)
        config = load_config(processing / "processing-config.json")
        binding = read(processing / "input-binding.json")
        # Check the split before source I/O, including implicit calibration selection.
        if config.split is not None and digest(config.split) != binding["split_sha256"]:
            raise ValueError("calibration split changed")
        rows, fields, observed = select_rows(config)
        for key in ("selected_rows_sha256", "metadata_sha256", "split_sha256", "episode_indices"):
            if observed[key] != binding[key]:
                raise ValueError(f"source binding changed: {key}")
        profile = RobotProfile.model_validate_json((processing / "robot-profile.json").read_text())
        model_profile = RobotProfile.model_validate_json(
            (model_dir / "source-profile.json").read_text()
        )
        if profile != model_profile:
            raise ValueError("replay model/profile mismatch")
        if (
            config.mujoco_model
            and digest(model_dir / "manifest.json") != binding["mujoco_model_manifest_sha256"]
        ):
            raise ValueError("Mink processing used a different model")
        engine = MujocoKinematics(model_dir)
        report = read(processing / "report.json")
        names = report["joint_names"]
        groups = [g.name for g in profile.groups]
        targets = {}
        for row in rows:
            for stream, field in fields.items():
                canonical, _ = canonical_frame(config, profile, row, field)
                targets[row["episode_index"], row["frame_index"], stream] = canonical
        quality = quality_index(dataset, processing)
        records = pq.read_table(processing / "trajectories.parquet").to_pylist()
        episodes = {}
        max_p_delta = max_a_delta = 0.0
        seen = set()
        for row in sorted(
            records, key=lambda r: (r["episode_index"], r["stream"], r["frame_index"])
        ):
            key = (row["episode_index"], row["frame_index"], row["stream"])
            if key in seen or key not in targets:
                raise ValueError("duplicate or unexpected processing frame")
            seen.add(key)
            canonical = targets[key]
            if canonical.timestamp_s != row["timestamp"]:
                raise ValueError("source and saved trajectory timestamps differ")
            engine.set_configuration(names, row["joint_positions"])
            target_values, actual_values = [], []
            for i, group in enumerate(groups):
                pose = canonical.poses[group]
                p, rot = engine.frame_pose(group)
                quat = np.empty(4)
                mujoco.mju_mat2Quat(quat, rot.reshape(9))
                pe = float(np.linalg.norm(p - pose.position_m))
                ae = quaternion_geodesic_angle_rad(quat, pose.quaternion_wxyz)
                dp, da = (
                    abs(pe - row["position_error_m"][i]),
                    abs(ae - row["orientation_error_rad"][i]),
                )
                max_p_delta, max_a_delta = max(max_p_delta, dp), max(max_a_delta, da)
                if dp > 1e-5 or da > 1e-4:
                    raise ValueError(f"MuJoCo/saved diagnostic FK mismatch: {key}")
                target_values.append([*pose.position_m, *pose.quaternion_wxyz])
                actual_values.append([*p.tolist(), *quat.tolist()])
            episode = episodes.setdefault(key[0], {"episode_index": key[0], "streams": {}})
            seq = episode["streams"].setdefault(
                key[2], {"frames": [], "lower": [1e9] * 3, "upper": [-1e9] * 3}
            )
            lower, upper = visual_bounds(engine)
            root = engine.model.body(engine.metadata["root_frame"]).id
            root_rot = engine.data.xmat[root].reshape(3, 3)
            for target in target_values:
                world = engine.data.xpos[root] + root_rot @ target[:3]
                lower, upper = np.minimum(lower, world - 0.08), np.maximum(upper, world + 0.08)
            seq["lower"] = np.minimum(seq["lower"], lower).tolist()
            seq["upper"] = np.maximum(seq["upper"], upper).tolist()
            qr = quality[key] if quality is not None else None
            paired = (
                None
                if quality is None
                else all(quality[(key[0], key[1], s)]["training_eligible"] for s in fields)
            )
            seq["frames"].append(
                {
                    "frame_index": key[1],
                    "timestamp_s": row["timestamp"],
                    "q": row["joint_positions"],
                    "targets": target_values,
                    "actuals": actual_values,
                    "position_error_mm": [v * 1000 for v in row["position_error_m"]],
                    "orientation_error_deg": [
                        float(np.degrees(v)) for v in row["orientation_error_rad"]
                    ],
                    "velocity_ratio": row["max_velocity_ratio"],
                    "pose_ok": row["pose_ok"],
                    "limits_ok": row["limits_ok"],
                    "kinematics_valid": row["kinematics_valid"],
                    "collision_free": row["collision_free"],
                    "solver_status": row["solver_status"],
                    "native_collision_free": row.get("backend_collision_free"),
                    "native_clearance_ok": (qr or {}).get(
                        "native_clearance_ok", row.get("backend_clearance_ok")
                    ),
                    "native_min_distance_m": (qr or {}).get(
                        "native_min_distance_m", row.get("backend_min_distance_m")
                    ),
                    "eligible": paired,
                    "eligible_with_native_clearance": (
                        bool(
                            paired
                            and all(
                                quality[(key[0], key[1], stream)]["native_clearance_ok"]
                                for stream in fields
                            )
                        )
                        if qr is not None and qr.get("native_clearance_ok") is not None
                        else None
                    ),
                    "quality": qr["quality"] if qr else None,
                }
            )
        if seen != set(targets) or (quality is not None and set(quality) != seen):
            raise ValueError("source, processing and quality frame coverage differs")
        item = {
            "id": entry["id"],
            "robot_id": profile.robot_id,
            "backend": config.backend,
            "label": entry.get("label", entry["id"]),
            "collision_avoidance_enabled": config.backend == "mink"
            and config.solve_options.enable_self_collision_barrier,
            "native_clearance_margin_mm": config.solve_options.self_collision_min_distance_m * 1000,
            "native_distance_clip_mm": max(
                0.02, config.solve_options.self_collision_min_distance_m * 10
            )
            * 1000,
            "model": str(model_dir),
            "model_sha256": digest(model_dir / "manifest.json"),
            "joint_names": names,
            "groups": groups,
            "episodes": [],
            "position_tolerance_mm": config.solve_options.position_tolerance_m * 1000,
            "orientation_tolerance_deg": float(
                np.degrees(config.solve_options.orientation_tolerance_rad)
            ),
            "fk_max_delta_m": max_p_delta,
            "fk_max_delta_rad": max_a_delta,
        }
        for ep, episode in sorted(episodes.items()):
            filename = f"{entry['id']}-{ep}.json"
            write(output / filename, episode)
            catalog["files"][filename] = digest(output / filename)
            item["episodes"].append(
                {
                    "id": ep,
                    "file": filename,
                    "frames": len(next(iter(episode["streams"].values()))["frames"]),
                }
            )
        catalog["runs"].append(item)
        catalog["sources"][entry["id"]] = {
            "processing_run": str(processing),
            "processing_manifest_sha256": digest(processing / "manifest.json"),
            "quality_dataset": str(dataset) if dataset else None,
            "quality_manifest_sha256": digest(dataset / "retarget/manifest.json")
            if dataset
            else None,
            "input_binding": observed,
        }
        total += len(records)
        print(f"{entry['id']}: verified {len(records)} stream frames", flush=True)
    catalog["stream_frames"] = total
    write(output / "catalog.json", catalog)
    return {
        "status": "VERIFIED",
        "stream_frames": total,
        "views": len(entries),
        "catalog_sha256": digest(output / "catalog.json"),
    }
