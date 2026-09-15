"""Export same-embodiment training rows after source-relative quality checks."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

import numpy as np

from retargetlab.run.training_quality import assess_contacts


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def _stats(values: np.ndarray) -> dict:
    values = np.asarray(values, dtype=np.float64)
    if not len(values):
        raise ValueError("no eligible values for training normalization")
    return {
        "min": values.min(axis=0).tolist(),
        "max": values.max(axis=0).tolist(),
        "mean": values.mean(axis=0).tolist(),
        "std": values.std(axis=0).tolist(),
        "count": [len(values)],
    }


def _merge_stats(values: list[dict]) -> dict:
    weights = np.asarray([v["count"][0] for v in values], dtype=float)
    mean = np.average(np.asarray([v["mean"] for v in values]), axis=0, weights=weights)
    variances = np.asarray(
        [np.asarray(v["std"]) ** 2 + (np.asarray(v["mean"]) - mean) ** 2 for v in values]
    )
    return {
        "min": np.min([v["min"] for v in values], axis=0).tolist(),
        "max": np.max([v["max"] for v in values], axis=0).tolist(),
        "mean": mean.tolist(),
        "std": np.sqrt(np.average(variances, axis=0, weights=weights)).tolist(),
        "count": [int(weights.sum())],
    }


def export_training_dataset(
    processing_run: Path,
    policy_path: Path,
    output: Path,
    progress=None,
    media_audit: Path | None = None,
) -> dict:
    """Use saved EEF-only IK results; read source joints only in this later step."""
    import pinocchio as pin
    import pyarrow as pa
    import pyarrow.parquet as pq

    from retargetlab.contracts import RobotProfile
    from retargetlab.kinematics.transforms import (
        matrix_to_quaternion_wxyz,
        quaternion_geodesic_angle_rad,
    )
    from retargetlab.robot.collision import PinocchioCollisionModel
    from retargetlab.run.video_metadata import probe_video

    processing_run, output = processing_run.resolve(), output.resolve()
    config = json.loads((processing_run / "processing-config.json").read_text())
    binding = json.loads((processing_run / "input-binding.json").read_text())
    run_manifest = json.loads((processing_run / "manifest.json").read_text())
    if run_manifest["status"] != "COMPLETED":
        raise ValueError("processing run is not complete")
    for name in [
        "trajectories.parquet",
        "robot-profile.json",
        "processing-config.json",
        "input-binding.json",
    ]:
        if _sha(processing_run / name) != run_manifest["files"][name]:
            raise ValueError(f"processing artifact changed: {name}")
    if binding["source_joint_columns_read"]:
        raise ValueError("training export requires independent EEF-only IK")
    is_mq03 = config["source_format"] == "mq03_eef"
    policy = json.loads(policy_path.read_text(encoding="utf-8-sig"))
    profile = RobotProfile.model_validate_json((processing_run / "robot-profile.json").read_text())
    if profile.robot_id != policy["robot_id"]:
        raise ValueError("training policy/profile mismatch")
    sidecar = Path(config["dataset"])
    if is_mq03:
        from retargetlab.run.process import load_config, select_rows

        if _sha(Path(config["split"])) != binding["split_sha256"]:
            raise ValueError("MQ03 split changed before source access")
        eef_rows, _, fresh_binding = select_rows(
            load_config(processing_run / "processing-config.json")
        )
        for key in ("selected_rows_sha256", "metadata_sha256", "split_sha256", "episode_indices"):
            if fresh_binding[key] != binding[key]:
                raise ValueError(f"MQ03 processing input changed: {key}")
        source = sidecar
        source_manifest_hash = None
    else:
        source_manifest = json.loads((sidecar / "manifest.json").read_text())
        source = Path(source_manifest["source_dataset"])
        source_manifest_hash = _sha(sidecar / "manifest.json")
        for name, digest in source_manifest["fingerprints"]["data"].items():
            if _sha(source / name) != digest:
                raise ValueError("original Joint source fingerprint changed")
        if _sha(source / "meta/info.json") != source_manifest["fingerprints"]["info"]:
            raise ValueError("original metadata changed")
    if output.exists() or any(
        output.is_relative_to(p.resolve()) for p in [source, sidecar, processing_run]
    ):
        raise ValueError("output must be a new directory outside source and processing inputs")
    episodes = binding["episode_indices"]
    filters = [("episode_index", "in", episodes)]
    source_table = pq.read_table(source / "data", filters=filters)
    source_rows = sorted(
        source_table.to_pylist(), key=lambda r: (r["episode_index"], r["frame_index"])
    )
    if not is_mq03:
        eef_rows = pq.read_table(
            sidecar / "data/eef.parquet",
            columns=["episode_index", "frame_index", "timestamp", "observation.eef", "action.eef"],
            filters=filters,
        ).to_pylist()
    eef_by = {(r["episode_index"], r["frame_index"]): r for r in eef_rows}
    diagnostics = pq.read_table(processing_run / "trajectories.parquet").to_pylist()
    by = {(r["episode_index"], r["frame_index"], r["stream"]): r for r in diagnostics}
    if len(by) != len(diagnostics) or len(by) != len(source_rows) * 2:
        raise ValueError("processing/source row identity mismatch")
    info = json.loads((source / "meta/info.json").read_text())
    vector_names = [
        n for arm in range(2) for n in [*[f"qpos_{arm}_{j}" for j in range(7)], f"gripper_{arm}"]
    ]
    if is_mq03:
        vector_names = [
            n
            for side in ("L", "R")
            for n in [*[f"{side}arm{j}_Joint" for j in range(1, 8)], f"{side}gripper_Joint"]
        ]
    for stream in ["observation.state", "action"]:
        reference = stream + ".position" if is_mq03 else stream
        if info["features"][reference]["names"] != vector_names:
            raise ValueError("unexpected source Joint layout")
    source_episodes = pq.read_table(source / "meta/episodes", filters=filters).to_pylist()
    cameras = [key for key, feature in info["features"].items() if feature["dtype"] == "video"]
    media = json.loads(media_audit.read_text()) if media_audit else None
    video_headers, camera_shapes = {}, {}
    for meta in source_episodes:
        for camera in cameras:
            relative = info["video_path"].format(
                video_key=camera,
                chunk_index=meta[f"videos/{camera}/chunk_index"],
                file_index=meta[f"videos/{camera}/file_index"],
            )
            if not (source / relative).is_file():
                raise FileNotFoundError(f"selected source video missing: {relative}")
            header = probe_video(
                source / relative, meta[f"videos/{camera}/from_timestamp"], info["fps"]
            )
            if camera in camera_shapes and camera_shapes[camera] != header["shape_hwc"]:
                raise ValueError(f"selected episodes have different image sizes: {camera}")
            camera_shapes[camera] = header["shape_hwc"]
            video_headers[relative] = {**header, "sha256": _sha(source / relative)}
            if any(
                f"stats/{camera}/{stat}" not in meta
                for stat in ("min", "max", "mean", "std", "count")
            ):
                if media is None:
                    raise ValueError(
                        "missing episode image statistics; provide a video media audit"
                    )
                entry = media["videos"][relative]
                if entry["sha256"] != _sha(source / relative):
                    raise ValueError("media audit video fingerprint changed")
                if entry["decoded_frames"] != meta["length"]:
                    raise ValueError("media audit frame count differs from episode length")
                for stat, value in entry["stats"].items():
                    meta[f"stats/{camera}/{stat}"] = value
    video_corrections = []
    for camera, shape in camera_shapes.items():
        feature = info["features"][camera]
        if feature["shape"] != shape:
            video_corrections.append(
                {"camera": camera, "source_declared_shape": feature["shape"], "actual_shape": shape}
            )
        feature["shape"] = shape
        feature["names"] = ["height", "width", "channels"]
        details = feature.setdefault("info", feature.pop("video_info", {}))
        details.update(
            {"video.height": shape[0], "video.width": shape[1], "video.channels": shape[2]}
        )
    tasks = pq.read_table(source / "meta/tasks.parquet").to_pylist()
    task_text = {r["task_index"]: r["task"] for r in tasks}
    task_ids = sorted({r["task_index"] for r in source_rows})
    if not set(task_ids) <= task_text.keys():
        raise ValueError("source frame task index has no task description")
    task_map = {old: new for new, old in enumerate(task_ids)}
    dropped = [
        key
        for key in info["features"]
        if is_mq03
        and (key.endswith((".position", ".velocity", ".effort")) or key == "control_mode")
    ]
    collision = PinocchioCollisionModel(profile)
    model, data = collision.model, collision.model.createData()
    active = np.asarray(
        [model.joints[model.getJointId(n)].idx_q for g in profile.groups for n in g.joint_names]
    )
    raw_indices = list(range(7)) + list(range(8, 15))
    fingers = np.asarray(
        [
            model.joints[model.getJointId(n)].idx_q
            for g in profile.groups
            for n in g.gripper_joint_names
        ],
        dtype=int,
    )
    native = None
    if "native_clearance" in policy:
        from retargetlab.run.training_native_clearance import NativeExportClearance

        report_path = processing_run / "report.json"
        if _sha(report_path) != run_manifest["files"]["report.json"]:
            raise ValueError("processing report changed")
        names = list(model.names)[1:]
        if json.loads(report_path.read_text())["joint_names"] != names:
            raise ValueError("export joint order differs from processing report")
        native = NativeExportClearance(policy["native_clearance"], config, binding, profile, names)
    output.mkdir(parents=True)
    auxiliary = output / "retarget"
    auxiliary.mkdir()
    _json(
        auxiliary / "video-metadata-audit.json",
        {
            "videos": video_headers,
            "corrections": video_corrections,
            "source_metadata_modified": False,
        },
    )
    _json(
        auxiliary / "plan.json",
        {
            "policy": policy,
            "native_clearance": native.summary() if native else None,
            "processing_manifest_sha256": _sha(processing_run / "manifest.json"),
            "source_manifest_sha256": source_manifest_hash,
            "episode_indices": episodes,
            "source_joints_read_after_independent_ik": True,
            "pose_reference": "source EEF; immutable target",
            "numeric_check": "Final float32 arm values; joint-limit epsilon is explicit in policy",
        },
    )
    if is_mq03:
        pq.write_table(source_table, auxiliary / "source-reference.parquet")
    if media_audit:
        shutil.copy2(media_audit, auxiliary / "media-audit.json")
    output_rows, quality_rows = [], []
    previous = {}
    episode_map = {ep: i for i, ep in enumerate(sorted(episodes))}
    for global_index, source_row in enumerate(source_rows):
        ep, frame = source_row["episode_index"], source_row["frame_index"]
        eef = eef_by[(ep, frame)]
        if source_row["timestamp"] != eef["timestamp"]:
            raise ValueError("source Joint and EEF timestamps do not match")
        target_row = {key: value for key, value in source_row.items() if key not in dropped}
        valid_streams = []
        for stream, eef_field in [
            ("observation.state", "observation.eef"),
            ("action", "action.eef"),
        ]:
            diagnostic = by[(ep, frame, stream)]
            if diagnostic["timestamp"] != source_row["timestamp"]:
                raise ValueError("processing timestamp changed")
            original = np.asarray(
                source_row[stream + ".position" if is_mq03 else stream], dtype=float
            )
            target = np.asarray(eef[stream if is_mq03 else eef_field], dtype=float)
            q = np.asarray(diagnostic["joint_positions"], dtype=float)
            # The exported vector contains motor raw gripper channels, not geometry coordinates.
            vector = np.empty(16, dtype=np.float32)
            vector[raw_indices] = q[active]
            vector[[7, 15]] = diagnostic["source_gripper_raw"]
            if not np.array_equal(vector[[7, 15]], np.asarray(original[[7, 15]], dtype=np.float32)):
                raise ValueError("raw gripper channels changed")
            q = q.copy()
            q[active] = vector[raw_indices].astype(float)
            q[fingers] = 0.022
            source_q = pin.neutral(model)
            source_q[active] = original[raw_indices]
            source_q[fingers] = 0.022
            errors, source_errors = [], []
            for current, is_source in [(source_q, True), (q, False)]:
                pin.framesForwardKinematics(model, data, current)
                for group, offset in zip(profile.groups, (0, 8), strict=True):
                    placement = data.oMf[model.getFrameId(group.end_effector_frame)]
                    position = (
                        target[offset + 5 : offset + 8] if is_mq03 else target[offset : offset + 3]
                    )
                    quaternion = (
                        target[offset + 1 : offset + 5]
                        if is_mq03
                        else target[offset + 3 : offset + 7]
                    )
                    p = float(np.linalg.norm(placement.translation - position))
                    a = quaternion_geodesic_angle_rad(
                        matrix_to_quaternion_wxyz(placement.rotation),
                        quaternion,
                    )
                    source_p_tol = policy.get("source_fk_position_tolerance_m", 1e-9)
                    source_a_tol = policy.get("source_fk_orientation_tolerance_rad", 1e-6)
                    if is_source and (p > source_p_tol or a > source_a_tol):
                        raise ValueError("original Joint does not reproduce its EEF target")
                    if is_source:
                        source_errors.append([p, a])
                    else:
                        errors.append([p, a])
            source_contacts = collision.report(source_q)
            target_contacts = collision.report(q)
            pose = all(
                p <= policy["position_tolerance_m"]
                and a <= np.deg2rad(policy["orientation_tolerance_deg"])
                for p, a in errors
            )
            eps = policy["joint_limit_numeric_epsilon_rad"]
            limits = bool(
                (q[active] >= model.lowerPositionLimit[active] - eps).all()
                and (q[active] <= model.upperPositionLimit[active] + eps).all()
            )
            last = previous.get((ep, stream))
            ratio = None
            if last is not None:
                if frame != last[0] + 1:
                    raise ValueError("export episodes must have contiguous frames")
                dt = source_row["timestamp"] - last[1]
                ratio = float(
                    np.max(np.abs(q[active] - last[2]) / dt / model.velocityLimit[active])
                )
            previous[(ep, stream)] = (frame, source_row["timestamp"], q[active])
            speed = ratio is None or ratio <= policy["maximum_speed_ratio"]
            assessment = assess_contacts(
                target_contacts.active_pairs,
                source_contacts.active_pairs,
                terminal_links=policy["terminal_links"],
                kinematics_valid=pose and limits and speed,
            )
            if native is not None:
                assessment.update(native.assess(q))
                if not assessment["native_clearance_ok"]:
                    assessment["training_eligible"] = False
                    assessment["quality"] = "EXCLUDED"
            assessment.update(
                {
                    "source_episode_index": ep,
                    "episode_index": episode_map[ep],
                    "frame_index": frame,
                    "index": global_index,
                    "stream": stream,
                    "pose_pass": pose,
                    "limits_pass": limits,
                    "speed_pass": speed,
                    "max_speed_ratio": ratio,
                    "fk_errors": errors,
                    "source_fk_errors": source_errors,
                    "source_to_target_max_joint_delta_rad": float(
                        np.max(np.abs(q[active] - source_q[active]))
                    ),
                }
            )
            quality_rows.append(assessment)
            valid_streams.append(assessment["training_eligible"])
            target_row[stream] = vector.tolist()
        target_row["episode_index"] = episode_map[ep]
        target_row["index"] = global_index
        target_row["task_index"] = task_map[source_row["task_index"]]
        target_row["valid.retarget"] = float(all(valid_streams))
        output_rows.append(target_row)
        if progress and (global_index + 1) % 1000 == 0:
            progress(global_index + 1, len(source_rows))
    table = pa.Table.from_pylist(output_rows)
    for stream in ["observation.state", "action", "valid.retarget"]:
        dtype = pa.float32() if stream == "valid.retarget" else pa.list_(pa.float32(), 16)
        values = pa.array([r[stream] for r in output_rows], type=dtype)
        table = table.set_column(table.schema.get_field_index(stream), stream, values)
    data_path = output / "data/chunk-000/file-000.parquet"
    data_path.parent.mkdir(parents=True)
    pq.write_table(table, data_path)
    if pq.read_table(data_path).to_pylist() != table.to_pylist():
        raise RuntimeError("training data round-trip changed values")
    pq.write_table(pa.Table.from_pylist(quality_rows), auxiliary / "quality.parquet")
    original_meta = {r["episode_index"]: r for r in source_episodes}
    features = {
        key: copy.deepcopy(value) for key, value in info["features"].items() if key not in dropped
    }
    for stream in ("observation.state", "action"):
        features[stream]["names"] = vector_names
    for camera in cameras:
        feature = features[camera]
        if "video_info" in feature and "info" not in feature:
            feature["info"] = feature.pop("video_info")
    features["valid.retarget"] = {"dtype": "float32", "shape": [1], "names": ["training_eligible"]}
    info["features"] = features
    numeric = [key for key, feature in features.items() if feature["dtype"] != "video"]
    cameras = [key for key, feature in features.items() if feature["dtype"] == "video"]
    new_episodes, video_paths = [], set()
    offset = 0
    for old_ep, new_ep in episode_map.items():
        selected = [r for r in output_rows if r["episode_index"] == new_ep]
        meta = {
            key: copy.deepcopy(value)
            for key, value in original_meta[old_ep].items()
            if not any(key.startswith(f"stats/{name}/") for name in dropped)
        }
        meta["tasks"] = sorted(
            {task_text[r["task_index"]] for r in source_rows if r["episode_index"] == old_ep}
        )
        meta.update(
            {
                "episode_index": new_ep,
                "dataset_from_index": offset,
                "dataset_to_index": offset + len(selected),
                "length": len(selected),
                "data/chunk_index": 0,
                "data/file_index": 0,
                "meta/episodes/chunk_index": 0,
                "meta/episodes/file_index": 0,
            }
        )
        offset += len(selected)
        mask = np.asarray([bool(r["valid.retarget"]) for r in selected])
        for key in numeric:
            values = np.asarray([r[key] for r in selected])
            if values.ndim == 1:
                values = values[:, None]
            measured = values[mask] if key in ["observation.state", "action"] else values
            stats = _stats(measured) if len(measured) else None
            if stats is None:
                stats = {
                    "min": [0.0] * 16,
                    "max": [0.0] * 16,
                    "mean": [0.0] * 16,
                    "std": [1.0] * 16,
                    "count": [0],
                }
            for stat, value in stats.items():
                meta[f"stats/{key}/{stat}"] = value
        for camera in cameras:
            relative = info["video_path"].format(
                video_key=camera,
                chunk_index=meta[f"videos/{camera}/chunk_index"],
                file_index=meta[f"videos/{camera}/file_index"],
            )
            video_paths.add(relative)
        new_episodes.append(meta)
    metadata_path = output / "meta/episodes/chunk-000/file-000.parquet"
    metadata_path.parent.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(new_episodes), metadata_path)
    task_table = pa.table(
        {"task_index": list(range(len(task_ids))), "task": [task_text[k] for k in task_ids]}
    )
    pandas_metadata = {
        "index_columns": ["task"],
        "column_indexes": [],
        "columns": [
            {
                "name": "task_index",
                "field_name": "task_index",
                "pandas_type": "int64",
                "numpy_type": "int64",
                "metadata": None,
            },
            {
                "name": "task",
                "field_name": "task",
                "pandas_type": "unicode",
                "numpy_type": "object",
                "metadata": None,
            },
        ],
        "pandas_version": "2.2.3",
    }
    task_table = task_table.replace_schema_metadata(
        {b"pandas": json.dumps(pandas_metadata).encode()}
    )
    pq.write_table(task_table, output / "meta/tasks.parquet")
    stats = {}
    for key in features:
        if key in ["observation.state", "action"]:
            values = np.asarray([r[key] for r in output_rows if r["valid.retarget"]])
            stats[key] = _stats(values)
        elif key in cameras:
            entries = [
                {name: r[f"stats/{key}/{name}"] for name in ["min", "max", "mean", "std", "count"]}
                for r in new_episodes
            ]
            stats[key] = _merge_stats(entries)
        else:
            values = np.asarray([r[key] for r in output_rows])
            stats[key] = _stats(values[:, None] if values.ndim == 1 else values)
    info.update(
        {
            "total_episodes": len(new_episodes),
            "total_frames": len(output_rows),
            "total_videos": len(video_paths),
            "total_tasks": len(task_ids),
            "splits": {"train": f"0:{len(new_episodes)}"},
        }
    )
    _json(output / "meta/info.json", info)
    _json(output / "meta/stats.json", stats)
    for relative in sorted(video_paths):
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, destination)
        if _sha(destination) != video_headers[relative]["sha256"]:
            raise RuntimeError("video source changed while copying the export")
    summaries = {}
    for stream in ["observation.state", "action"]:
        group = [r for r in quality_rows if r["stream"] == stream]
        summaries[stream] = {
            "frames": len(group),
            "quality_counts": dict(Counter(r["quality"] for r in group)),
            "new_collision_frames": sum(bool(r["new_collision_pairs"]) for r in group),
            "pose_failures": sum(not r["pose_pass"] for r in group),
            "limit_failures": sum(not r["limits_pass"] for r in group),
            "speed_failures": sum(not r["speed_pass"] for r in group),
            **(
                {
                    "native_clearance_failures": sum(not r["native_clearance_ok"] for r in group),
                    "minimum_native_distance_m": min(r["native_min_distance_m"] for r in group),
                }
                if native
                else {}
            ),
        }
    report = {
        "status": "COMPLETED",
        "format": "LeRobot v3 local dataset with explicit training mask",
        "policy_id": policy["policy_id"],
        "native_clearance": native.summary() if native else None,
        "backend": config.get("backend", "pink"),
        "video_metadata_corrections": video_corrections,
        "frames": len(output_rows),
        "episodes": len(new_episodes),
        "videos_copied": len(video_paths),
        "source_episode_mapping": episode_map,
        "source_task_mapping": task_map,
        "auxiliary_source_columns_removed": dropped,
        "eligible_paired_rows": sum(bool(r["valid.retarget"]) for r in output_rows),
        "streams": summaries,
        "source_joint_read_stage": "AFTER_INDEPENDENT_IK",
        "gripper_raw_preserved": True,
        "training_loader_acceptance": "PENDING",
        "training_effect": "NOT_MEASURED",
        "baseline_evidence": policy["baseline_evidence"],
    }
    _json(auxiliary / "report.json", report)
    _json(auxiliary / "policy.json", policy)
    _json(
        auxiliary / "reader-config.json",
        {
            "repo_id": f"local/{profile.robot_id}-retarget-training",
            "video_backend": "pyav",
            "quality_feature": "valid.retarget",
            "default_action_horizon": 16,
            "normalization_note": "Joint stats masked; image stats inherited.",
        },
    )
    code_dir = auxiliary / "code"
    code_dir.mkdir()
    for name in [
        "training_export.py",
        "training_quality.py",
        "training_native_clearance.py",
        "video_metadata.py",
    ]:
        shutil.copy2(Path(__file__).parent / name, code_dir / name)
    _json(
        auxiliary / "manifest.json",
        {
            "status": "COMPLETED",
            "files": {
                p.relative_to(output).as_posix(): _sha(p)
                for p in output.rglob("*")
                if p.is_file() and p != auxiliary / "manifest.json"
            },
        },
    )
    return report
