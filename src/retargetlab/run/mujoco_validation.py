"""Validate saved MuJoCo FK against Pinocchio using named configurations."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np

from retargetlab.contracts import RobotProfile
from retargetlab.kinematics.transforms import (
    matrix_to_quaternion_wxyz,
    quaternion_geodesic_angle_rad,
)
from retargetlab.robot.assets import sha256_file
from retargetlab.robot.mujoco_model import MujocoKinematics, _write_json


def compare_configuration(engine, pin_model, pin_data, profile, names, q) -> dict:
    import pinocchio as pin

    engine.set_configuration(names, q)
    source_q = pin.neutral(pin_model)
    for name, value in zip(names, q, strict=True):
        source_q[pin_model.joints[pin_model.getJointId(name)].idx_q] = value
    pin.framesForwardKinematics(pin_model, pin_data, source_q)
    root = pin_data.oMf[pin_model.getFrameId(profile.root_frame)]
    errors = {}
    for group in profile.groups:
        expected = root.inverse() * pin_data.oMf[pin_model.getFrameId(group.end_effector_frame)]
        actual_p, actual_r = engine.frame_pose(group.name)
        errors[group.name] = [
            float(np.linalg.norm(expected.translation - actual_p)),
            quaternion_geodesic_angle_rad(
                matrix_to_quaternion_wxyz(expected.rotation), matrix_to_quaternion_wxyz(actual_r)
            ),
        ]
    return errors


def validate_mujoco_model(
    asset_dir: Path, processing_run: Path, output: Path, progress=None
) -> dict:
    import pinocchio as pin
    import pyarrow.parquet as pq

    from retargetlab.kinematics.pinocchio_backend import PinocchioBackend

    if output.exists():
        raise FileExistsError(output)
    engine = MujocoKinematics(asset_dir)
    profile = RobotProfile.model_validate_json((asset_dir / "source-profile.json").read_text())
    manifest = json.loads((processing_run / "manifest.json").read_text())
    for name in ("trajectories.parquet", "robot-profile.json", "report.json", "input-binding.json"):
        if sha256_file(processing_run / name) != manifest["files"][name]:
            raise ValueError(f"processing artifact changed: {name}")
    processed_profile = RobotProfile.model_validate_json(
        (processing_run / "robot-profile.json").read_text()
    )
    if profile != processed_profile:
        raise ValueError("model and processing run must reference the identical robot profile")
    pin_backend = PinocchioBackend(profile)
    pin_model, pin_data = pin_backend.model, pin_backend.data
    names = list(engine.metadata["joints"])
    controlled = [n for g in profile.groups for n in g.joint_names]
    lower = np.array([engine.metadata["joints"][n]["lower"] for n in names])
    upper = np.array([engine.metadata["joints"][n]["upper"] for n in names])
    neutral = np.clip(np.zeros(len(names)), lower, upper)

    def couple(q):
        for relation in engine.metadata["mimic"]:
            q[names.index(relation["follower"])] = (
                q[names.index(relation["driver"])] * relation["multiplier"] + relation["offset"]
            )
        return q

    followers = {r["follower"] for r in engine.metadata["mimic"]}
    cases = [("neutral", couple(neutral.copy()))]
    for index, name in enumerate(names):
        if name in followers:
            continue
        for label, value in (("lower", lower[index] + 1e-7), ("upper", upper[index] - 1e-7)):
            q = neutral.copy()
            q[index] = value
            cases.append((f"{name}:{label}", couple(q)))
    rng = np.random.default_rng(20260912)
    cases.extend((f"random:{i}", couple(rng.uniform(lower, upper))) for i in range(128))
    output.mkdir(parents=True)
    _write_json(
        output / "plan.json",
        {
            "position_tolerance_m": 1e-5,
            "orientation_tolerance_rad": 1e-4,
            "seed": 20260912,
            "synthetic_cases": len(cases),
            "processing_manifest_sha256": sha256_file(processing_run / "manifest.json"),
            "model_manifest_sha256": sha256_file(asset_dir / "manifest.json"),
            "new_source_dataset_access": False,
            "negative_controls": ["joint permutation", "TCP offset"]
            + (["fixed waist transform"] if profile.robot_id == "moqi_mq03_fixed_body" else []),
        },
    )
    measured = []
    for label, q in cases:
        measured.append(
            {
                "kind": "synthetic",
                "case": label,
                "errors": compare_configuration(engine, pin_model, pin_data, profile, names, q),
            }
        )
    process_report = json.loads((processing_run / "report.json").read_text())
    stored_names = process_report["joint_names"]
    frames = pq.read_table(
        processing_run / "trajectories.parquet",
        columns=["episode_index", "frame_index", "stream", "joint_positions"],
    ).to_pylist()
    for i, row in enumerate(frames):
        measured.append(
            {
                "kind": "saved_trajectory",
                "episode_index": row["episode_index"],
                "frame_index": row["frame_index"],
                "stream": row["stream"],
                "errors": compare_configuration(
                    engine, pin_model, pin_data, profile, stored_names, row["joint_positions"]
                ),
            }
        )
        if progress and (i + 1) % 5000 == 0:
            progress(i + 1, len(frames))
    summaries = {}
    for kind in ("synthetic", "saved_trajectory"):
        group = [r for r in measured if r["kind"] == kind]
        array = np.asarray([v for r in group for v in r["errors"].values()])
        summaries[kind] = {
            "configurations": len(group),
            "tcp_checks": len(array),
            "max_position_error_m": float(array[:, 0].max()),
            "max_orientation_error_rad": float(array[:, 1].max()),
            "failures": int(((array[:, 0] > 1e-5) | (array[:, 1] > 1e-4)).sum()),
        }
    # Fault injections modify only this in-memory instance; saved assets remain unchanged.
    probe = couple(neutral.copy())
    probe[names.index(controlled[0])] = 0.3
    probe[names.index(controlled[1])] = -0.2
    original_errors = compare_configuration(engine, pin_model, pin_data, profile, names, probe)
    assert all(p <= 1e-5 and a <= 1e-4 for p, a in original_errors.values())
    wrong_names = names.copy()
    first, second = names.index(controlled[0]), names.index(controlled[1])
    wrong_names[first], wrong_names[second] = wrong_names[second], wrong_names[first]
    engine.set_configuration(wrong_names, probe)
    first_group = profile.groups[0]
    expected = (
        pin_data.oMf[pin_model.getFrameId(profile.root_frame)].inverse()
        * pin_data.oMf[pin_model.getFrameId(first_group.end_effector_frame)]
    )
    p, r = engine.frame_pose(first_group.name)
    negative = {
        "joint_permutation": {
            "position_error_m": float(np.linalg.norm(p - expected.translation)),
            "orientation_error_rad": quaternion_geodesic_angle_rad(
                matrix_to_quaternion_wxyz(r), matrix_to_quaternion_wxyz(expected.rotation)
            ),
        }
    }
    site = engine.model.site(engine.metadata["tcp_sites"][first_group.name]["site"]).id
    sameframe = int(engine.model.site_sameframe[site])
    engine.model.site_sameframe[site] = 0  # Recompute the injected nonzero site transform.
    engine.model.site_pos[site, 2] += 0.01
    errors = compare_configuration(engine, pin_model, pin_data, profile, names, probe)
    engine.model.site_pos[site, 2] -= 0.01
    engine.model.site_sameframe[site] = sameframe
    negative["tcp_offset"] = {
        "position_error_m": errors[first_group.name][0],
        "orientation_error_rad": errors[first_group.name][1],
    }
    if profile.robot_id == "moqi_mq03_fixed_body":
        import xml.etree.ElementTree as ET

        source_tree = ET.parse(asset_dir / "source.urdf")
        child = source_tree.find(".//joint[@name='Waist1_Joint']/child").get("link")
        body = engine.model.body(child).id
        engine.model.body_pos[body, 2] += 0.02
        errors = compare_configuration(engine, pin_model, pin_data, profile, names, probe)
        engine.model.body_pos[body, 2] -= 0.02
        negative["fixed_waist_transform"] = {
            "position_error_m": errors[first_group.name][0],
            "orientation_error_rad": errors[first_group.name][1],
        }
    for value in negative.values():
        value["detected"] = (
            value["position_error_m"] > 1e-5 or value["orientation_error_rad"] > 1e-4
        )
    _write_json(output / "measurements.json", measured)
    report = {
        "status": "PASSED"
        if all(v["failures"] == 0 for v in summaries.values())
        and all(v["detected"] for v in negative.values())
        else "FAILED",
        "robot_id": profile.robot_id,
        "summaries": summaries,
        "negative_controls": negative,
        "inertia_repairs": engine.metadata["inertia_repairs"],
        "model_root": profile.root_frame,
        "gripper_mimic_relations": len(engine.metadata["mimic"]),
        "mink_ik_status": "NOT_IMPLEMENTED",
        "collision_equivalence": "NOT_VALIDATED",
        "dynamic_tracking": "NOT_RUN",
        "versions": {**engine.metadata["versions"], "pinocchio": pin.__version__},
    }
    _write_json(output / "report.json", report)
    code_dir = output / "code"
    code_dir.mkdir()
    shutil.copy2(Path(__file__), code_dir / Path(__file__).name)
    shutil.copy2(Path(__file__).parents[1] / "robot/mujoco_model.py", code_dir / "mujoco_model.py")
    return report
