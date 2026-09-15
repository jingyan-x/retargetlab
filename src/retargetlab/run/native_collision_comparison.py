"""Compare collision experiments with the unchanged source-relative quality policy."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import numpy as np

from retargetlab.contracts import RobotProfile
from retargetlab.replay.bundle import digest, quality_index, read, verify_files, write
from retargetlab.robot.collision import PinocchioCollisionModel
from retargetlab.robot.mujoco_model import MujocoKinematics
from retargetlab.robot.native_collision import NativeCollisionGeometry
from retargetlab.run.training_dataset import valid_window_indices
from retargetlab.run.training_quality import assess_contacts


def review_collision_run(processing: Path, baseline: Path, source_quality: Path, output: Path):
    """Write a small diagnostic quality review, never a LeRobot training export.

    The primary mask preserves the prior training criterion for an apples-to-
    apples comparison. A second count intersects it with the requested native
    clearance. Source contact pairs come from the frozen prior postcheck and
    are never sent to IK.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    if output.exists():
        raise ValueError("quality review requires a new directory")
    verify_files(processing)
    verify_files(baseline)
    original = quality_index(source_quality, baseline)
    source_binding, target_binding = (
        read(baseline / "input-binding.json"),
        read(processing / "input-binding.json"),
    )
    for key in ("selected_rows_sha256", "metadata_sha256", "split_sha256", "episode_indices"):
        if source_binding[key] != target_binding[key]:
            raise ValueError(f"comparison source identity differs: {key}")
    old_report, new_report = read(baseline / "report.json"), read(processing / "report.json")
    if old_report["joint_names"] != new_report["joint_names"]:
        raise ValueError("comparison joint order differs")
    if read(baseline / "robot-profile.json") != read(processing / "robot-profile.json"):
        raise ValueError("comparison robot profile differs")
    profile = RobotProfile.model_validate_json((processing / "robot-profile.json").read_text())
    collision = PinocchioCollisionModel(profile)
    config = read(processing / "processing-config.json")
    engine = MujocoKinematics(Path(config["mujoco_model"]))
    native_geometry = NativeCollisionGeometry(engine, profile)
    margin = config["solve_options"]["self_collision_min_distance_m"]
    cutoff = max(0.02, margin * 10)
    quality_plan = read(source_quality / "retarget/plan.json")
    policy = quality_plan["policy"]
    mapping = {
        int(k): v
        for k, v in read(source_quality / "retarget/report.json")["source_episode_mapping"].items()
    }
    rows = pq.read_table(processing / "trajectories.parquet").to_pylist()
    old_rows = pq.read_table(baseline / "trajectories.parquet").to_pylist()

    def keyed(r):
        return r["episode_index"], r["frame_index"], r["stream"]

    old = {keyed(r): r for r in old_rows}
    if {keyed(r) for r in rows} != set(old) or set(old) != set(original):
        raise ValueError("comparison frame coverage differs")
    output.mkdir(parents=True)
    (output / "retarget").mkdir()
    (output / "data").mkdir()
    qualities = []
    paired = {}
    native = {}
    old_paired = {}
    stream_counts = {}
    max_delta = 0.0
    for row in rows:
        key = keyed(row)
        before = old[key]
        if row["timestamp"] != before["timestamp"]:
            raise ValueError("comparison timestamp differs")
        target_pairs = collision.report(row["joint_positions"]).active_pairs
        if (not target_pairs) != row["collision_free"]:
            raise ValueError("fresh Coal check disagrees with process")
        engine.set_configuration(new_report["joint_names"], row["joint_positions"])
        native_distance = native_geometry.minimum(engine.data, cutoff)
        native_ok = native_distance >= margin - 1e-8
        if row.get("backend_clearance_ok") is not None:
            if native_ok != row["backend_clearance_ok"]:
                raise ValueError("fresh native clearance check disagrees with process")
            if abs(native_distance - row["backend_min_distance_m"]) > 1e-10:
                raise ValueError("fresh native distance disagrees with process")
        assessment = assess_contacts(
            target_pairs,
            original[key]["source_pairs"],
            terminal_links=policy["terminal_links"],
            kinematics_valid=row["kinematics_valid"],
        )
        assessment.update(
            source_episode_index=key[0],
            episode_index=mapping[key[0]],
            frame_index=key[1],
            stream=key[2],
            native_clearance_ok=native_ok,
            native_min_distance_m=native_distance,
        )
        qualities.append(assessment)
        paired.setdefault(key[:2], []).append(assessment["training_eligible"])
        native.setdefault(key[:2], []).append(native_ok)
        old_paired.setdefault(key[:2], []).append(original[key]["training_eligible"])
        counts = stream_counts.setdefault(key[2], Counter())
        counts["frames"] += 1
        counts["pose_pass"] += row["pose_ok"]
        counts["limits_pass"] += row["limits_ok"]
        counts["speed_failures"] += (
            row["max_velocity_ratio"] is not None and row["max_velocity_ratio"] > 1 + 1e-6
        )
        counts["coal_contact_frames"] += not row["collision_free"]
        counts["same_policy_eligible"] += assessment["training_eligible"]
        counts["native_clearance_pass"] += native_ok
        counts["solver_converged"] += row["solver_status"] == "CONVERGED"
        counts["newly_eligible"] += (
            assessment["training_eligible"] and not original[key]["training_eligible"]
        )
        counts["lost_eligible"] += (
            original[key]["training_eligible"] and not assessment["training_eligible"]
        )
        max_delta = max(
            max_delta,
            float(np.max(np.abs(np.asarray(row["joint_positions"]) - before["joint_positions"]))),
        )
    keys = sorted(paired)
    if any(len(v) != 2 for v in paired.values()):
        raise ValueError("paired mask requires both streams")
    masks = [all(paired[k]) for k in keys]
    old_masks = [all(old_paired[k]) for k in keys]
    strict = [m and all(native[k]) for k, m in zip(keys, masks, strict=True)]
    episodes = [k[0] for k in keys]
    frames = [k[1] for k in keys]

    def windows(flags):
        return len(valid_window_indices(episodes, frames, flags, 16))

    mask_rows = [
        {
            "episode_index": mapping[k[0]],
            "frame_index": k[1],
            "valid.retarget": float(m),
            "valid.native_clearance": float(s),
        }
        for k, m, s in zip(keys, masks, strict, strict=True)
    ]
    pq.write_table(pa.Table.from_pylist(mask_rows), output / "data/mask.parquet")
    pq.write_table(pa.Table.from_pylist(qualities), output / "retarget/quality.parquet")
    plan = {
        "artifact_kind": "DIAGNOSTIC_QUALITY_REVIEW_NOT_A_TRAINING_DATASET",
        "policy": policy,
        "processing_manifest_sha256": digest(processing / "manifest.json"),
        "source_quality_manifest_sha256": digest(source_quality / "retarget/manifest.json"),
        "scope": "same original training criterion; native clearance counted separately",
    }
    write(output / "retarget/plan.json", plan)
    result = {
        "status": "COMPLETED_DIAGNOSTIC_REVIEW",
        "training_ready": False,
        "source_episode_mapping": mapping,
        "streams": stream_counts,
        "same_policy_paired_eligible": sum(masks),
        "baseline_paired_eligible": sum(old_masks),
        "same_policy_horizon16_windows": windows(masks),
        "baseline_horizon16_windows": windows(old_masks),
        "paired_and_native_clearance_eligible": sum(strict),
        "paired_and_native_clearance_horizon16_windows": windows(strict),
        "maximum_joint_delta_from_baseline": max_delta,
        "native_collision_avoidance": new_report["native_collision_avoidance"],
        "native_postcheck": {
            "both_enabled_and_disabled_runs_checked": True,
            "geometry": native_geometry.summary(),
            "minimum_distance_m": margin,
            "detection_distance_m": cutoff,
        },
        "processing_manifest_sha256": digest(processing / "manifest.json"),
        "baseline_processing_manifest_sha256": digest(baseline / "manifest.json"),
        "mask_scope": (
            "valid.retarget preserves the original quality criterion; "
            "valid.native_clearance additionally requires native clearance. "
            "Both on and off are freshly checked. No videos, no loader or training-readiness claim."
        ),
    }
    write(output / "retarget/report.json", result)
    write(
        output / "retarget/manifest.json",
        {
            "status": "COMPLETED",
            "files": {
                p.relative_to(output).as_posix(): digest(p)
                for p in output.rglob("*")
                if p.is_file()
            },
        },
    )
    # The same verified quality interface is consumed by the saved-q viewer.
    quality_index(output, processing)
    return result
