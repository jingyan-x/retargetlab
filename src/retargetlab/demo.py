"""Generate a public-model, synthetic-data example for the existing pipeline."""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

OPENARM_REVISION = "6148297241fb0402eafe2c6eed455ae4e90d4552"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def _video(path, camera, episode, count, fps):
    import av

    path.parent.mkdir(parents=True, exist_ok=True)
    samples = []
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width, stream.height, stream.pix_fmt = 96, 64, "yuv420p"
        stream.options = {"crf": "18", "preset": "fast"}
        yy, xx = np.indices((64, 96))
        for i in range(count):
            rgb = np.empty((64, 96, 3), dtype=np.uint8)
            rgb[:, :, 0] = (xx * 2 + i * 3) % 256
            rgb[:, :, 1] = (yy * 3 + episode * 60) % 256
            rgb[:, :, 2] = (camera * 80 + i) % 256
            for packet in stream.encode(av.VideoFrame.from_ndarray(rgb, format="rgb24")):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    # Statistics describe decoded pixels, not the pre-encoding RGB arrays.
    with av.open(str(path)) as container:
        for frame in container.decode(video=0):
            samples.append(frame.to_ndarray(format="rgb24").reshape(-1, 3) / 255)
    if len(samples) != count:
        raise RuntimeError("synthetic video frame count changed")
    values = np.concatenate(samples)
    return {
        **{
            key: getattr(values, key)(axis=0).reshape(3, 1, 1).tolist()
            for key in ("min", "max", "mean", "std")
        },
        "count": [count],
    }


def create_demo(source: Path, output: Path) -> dict:
    """Use official OpenArm geometry and generate EEF targets from synthetic q.

    The generated joint columns are a later export reference only. The normal
    process command reads EEF/time/index columns and starts IK independently.
    """
    import pinocchio as pin
    import pyarrow as pa
    import pyarrow.parquet as pq

    from retargetlab.kinematics.transforms import matrix_to_quaternion_wxyz
    from retargetlab.robot.assets import sha256_file
    from retargetlab.robot.openarm import load_openarm_bimanual_profile
    from retargetlab.robot.openarm_assets import DEFAULT_ENTRY, build, git_revision

    source, output = source.resolve(), output.resolve()
    if git_revision(source) != OPENARM_REVISION:
        raise ValueError(f"checkout enactic/openarm_description at {OPENARM_REVISION}")
    if output.exists() or output.is_relative_to(source):
        raise ValueError("demo output must be a new directory outside the upstream source")
    license_path = source / "LICENSE.txt"
    if not license_path.is_file():
        raise ValueError("official OpenArm LICENSE.txt is required")
    output.mkdir(parents=True)
    assets, joint_source, sidecar = [output / name for name in ("robot", "source", "eef")]
    manifest = build(source, assets, DEFAULT_ENTRY, None)
    # Explicit structural demo policy, not a private or inferred contact table:
    # adjacent controlled arm links and their fixed hand attachment only.
    urdf = ET.parse(assets / "urdf/openarm_bimanual_v10.urdf").getroot()
    adjacent = ET.Element("robot", name="openarm_demo")
    names = {f"openarm_{s}_joint{j}" for s in ("left", "right") for j in range(1, 8)}
    names.update(f"{s}_openarm_hand_joint" for s in ("left", "right"))
    for joint in urdf.findall("joint"):
        if joint.get("name") in names:
            ET.SubElement(
                adjacent,
                "disable_collisions",
                reason="Adjacent",
                link1=joint.find("parent").get("link"),
                link2=joint.find("child").get("link"),
            )
    srdf = assets / "srdf/demo-adjacent.srdf"
    srdf.parent.mkdir()
    ET.ElementTree(adjacent).write(srdf, encoding="utf-8", xml_declaration=True)
    manifest.update(srdf_path="srdf/demo-adjacent.srdf", srdf_sha256=sha256_file(srdf))
    manifest["collision_policy_origin"] = (
        "Generated from URDF adjacency; 14 arm joints + 2 hand attachments"
    )
    write_json(assets / "asset_manifest.json", manifest)
    shutil.copy2(license_path, assets / "LICENSE.txt")
    (assets / "NOTICE.txt").write_text(
        "OpenArm description: Copyright 2025 Enactic, Inc.; Apache-2.0.\n"
        f"Source: https://github.com/enactic/openarm_description/tree/{OPENARM_REVISION}\n"
        "Changes: expanded xacro; relative meshes; generated adjacency SRDF.\n"
        "Synthetic demonstration trajectories are not recorded robot data.\n"
    )
    profile = load_openarm_bimanual_profile(assets)
    write_json(output / "robot-profile.json", profile.model_dump(mode="json"))
    model = pin.buildModelFromUrdf(str(assets / profile.urdf_path))
    data = model.createData()
    base = np.clip(pin.neutral(model), model.lowerPositionLimit, model.upperPositionLimit)
    active = [
        model.joints[model.getJointId(n)].idx_q for g in profile.groups for n in g.joint_names
    ]
    fingers = [
        model.joints[model.getJointId(n)].idx_q
        for g in profile.groups
        for n in g.gripper_joint_names
    ]
    base[fingers] = 0.022
    fps, count, n_episodes = 30, 96, 2
    raw_rows, eef_rows, metadata = [], [], []
    cameras = [f"observation.images.{n}" for n in ("front", "left_wrist", "right_wrist")]
    for episode in range(n_episodes):
        for frame in range(count):
            eef_row = dict(episode_index=episode, frame_index=frame, timestamp=frame / fps)
            raw_row = {**eef_row, "index": len(raw_rows), "task_index": 0}
            for stream, shift in (("observation.state", 0), ("action", 0.12)):
                q = base.copy()
                phase = frame / fps + shift
                q[active] += 0.06 * np.sin(phase * 1.2) * np.cos(np.arange(14) * 0.6)
                # An abrupt, valid source target creates a visible tracking failure
                # under unchanged frame-to-frame output speed limits.
                if episode == 1 and 48 <= frame < 64:
                    q[active[0]] += 0.8
                q = np.clip(q, model.lowerPositionLimit, model.upperPositionLimit)
                raw_grippers = [-0.4 + 0.03 * np.sin(phase), -0.3 + 0.03 * np.cos(phase)]
                pin.framesForwardKinematics(model, data, q)
                vector, eef = [], []
                for arm, group in enumerate(profile.groups):
                    placement = data.oMf[model.getFrameId(group.end_effector_frame)]
                    vector.extend([*q[active[arm * 7 : (arm + 1) * 7]], raw_grippers[arm]])
                    eef.extend(
                        [
                            *placement.translation,
                            *matrix_to_quaternion_wxyz(placement.rotation),
                            raw_grippers[arm],
                        ]
                    )
                raw_row[stream] = vector
                eef_row["observation.eef" if stream == "observation.state" else "action.eef"] = eef
            raw_rows.append(raw_row)
            eef_rows.append(eef_row)
        meta = {"episode_index": episode, "length": count, "tasks": ["Synthetic pipeline demo"]}
        for camera_index, camera in enumerate(cameras):
            relative = f"videos/{camera}/chunk-000/file-{episode:03d}.mp4"
            stats = _video(joint_source / relative, camera_index, episode, count, fps)
            for key, value in stats.items():
                meta[f"stats/{camera}/{key}"] = value
            for key, value in {
                "chunk_index": 0,
                "file_index": episode,
                "from_timestamp": 0.0,
                "to_timestamp": count / fps,
            }.items():
                meta[f"videos/{camera}/{key}"] = value
        metadata.append(meta)
    for path, rows in (
        (joint_source / "data/chunk-000/file-000.parquet", raw_rows),
        (sidecar / "data/eef.parquet", eef_rows),
        (joint_source / "meta/episodes/chunk-000/file-000.parquet", metadata),
        (
            joint_source / "meta/tasks.parquet",
            [{"task_index": 0, "task": "Synthetic pipeline demo"}],
        ),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows), path)
    names = [
        n for arm in range(2) for n in [*[f"qpos_{arm}_{j}" for j in range(7)], f"gripper_{arm}"]
    ]
    features = {
        key: {"dtype": "float32", "shape": [16], "names": names}
        for key in ("observation.state", "action")
    }
    features.update(
        {
            key: {"dtype": "int64", "shape": [1], "names": None}
            for key in ("index", "episode_index", "frame_index", "task_index")
        }
    )
    features["timestamp"] = {"dtype": "float32", "shape": [1], "names": None}
    for camera in cameras:
        features[camera] = {
            "dtype": "video",
            "shape": [64, 96, 3],
            "names": ["height", "width", "channels"],
            "info": {
                "video.fps": fps,
                "video.codec": "h264",
                "video.pix_fmt": "yuv420p",
                "video.is_depth_map": False,
                "has_audio": False,
                "video.height": 64,
                "video.width": 96,
                "video.channels": 3,
            },
        }
    write_json(
        joint_source / "meta/info.json",
        {
            "codebase_version": "v3.0",
            "robot_type": "openarm_bimanual",
            "fps": fps,
            "total_episodes": n_episodes,
            "total_frames": n_episodes * count,
            "total_tasks": 1,
            "total_videos": n_episodes * len(cameras),
            "chunks_size": 1000,
            "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
            "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
            "features": features,
            "splits": {"train": "0:2"},
        },
    )
    (sidecar / "assets").mkdir()
    shutil.copy2(assets / profile.urdf_path, sidecar / "assets/source_openarm.urdf")
    write_json(
        sidecar / "manifest.json",
        {
            "format": "openarm_eef_sidecar.v1",
            "source_dataset": str(joint_source),
            "pose_columns": [
                f"{side}.{part}"
                for side in ("left", "right")
                for part in ("x_m", "y_m", "z_m", "qw", "qx", "qy", "qz", "gripper_raw")
            ],
            "root_frame": "world (URDF model root; no external lab-world calibration applied)",
            "quaternion_order": "wxyz",
            "pose_direction": "T_world_tcp maps TCP-local coordinates into URDF world",
            "tcp_frames": ["openarm_left_hand_tcp", "openarm_right_hand_tcp"],
            "link7_to_tcp_translation_m": [0, 0, 0.1801],
            "fingerprints": {
                "urdf": profile.urdf_sha256,
                "data": {
                    "data/chunk-000/file-000.parquet": sha256_file(
                        joint_source / "data/chunk-000/file-000.parquet"
                    )
                },
                "info": sha256_file(joint_source / "meta/info.json"),
            },
            "data_origin": "SYNTHETIC_FK_AND_RGB_PATTERNS; not private or recorded data",
        },
    )
    common = {
        "dataset_alias": "public_openarm_synthetic_demo",
        "source_format": "openarm_eef_sidecar",
        "dataset": "eef",
        "robot_asset": "robot",
        "episode_indices": [0, 1],
        "solve_options": {
            "enable_self_collision_barrier": False,
            "qp_eps_abs": 1e-8,
            "qp_eps_rel": 1e-8,
            "random_seed": 7,
        },
    }
    write_json(output / "process-pink.json", {**common, "backend": "pink"})
    write_json(
        output / "process-mink.json", {**common, "backend": "mink", "mujoco_model": "mujoco"}
    )
    write_json(
        output / "quality-policy.json",
        {
            "policy_id": "synthetic_demo_strict_v1",
            "robot_id": profile.robot_id,
            "terminal_links": {"left": [], "right": []},
            "position_tolerance_m": 0.005,
            "orientation_tolerance_deg": 2.0,
            "joint_limit_numeric_epsilon_rad": 1e-6,
            "maximum_speed_ratio": 1.000001,
            "baseline_evidence": {
                "kind": "SYNTHETIC",
                "claim": "Public model and synthetic data; no physical execution.",
            },
            "rule": "Any active target collision or kinematic failure excludes the paired row.",
            "gripper": "Raw demonstration channels are not physical aperture commands.",
        },
    )
    write_json(
        output / "replay.json",
        [
            {
                "id": "openarm-demo",
                "label": "合成演示 · 非实采数据",
                "processing_run": "processed",
                "model": "mujoco",
                "quality_dataset": "dataset",
            }
        ],
    )
    result = {
        "status": "COMPLETED",
        "directory": str(output),
        "episodes": n_episodes,
        "frames": n_episodes * count,
        "synthetic": True,
        "source_revision": OPENARM_REVISION,
        "next": "Run process with process-pink.json and a new processed directory.",
    }
    write_json(output / "demo.json", result)
    return result
