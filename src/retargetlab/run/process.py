"""Config-driven Pink or Mink processing for the two established EEF layouts."""

from __future__ import annotations

import csv
import hashlib
import json
import time
from importlib.metadata import version
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from retargetlab.contracts import CanonicalFrame, Pose, RobotProfile, SolveOptions
from retargetlab.kinematics.pink_backend import PinkBackend
from retargetlab.kinematics.transforms import quaternion_geodesic_angle_rad
from retargetlab.openarm_new_eef import validate_manifest
from retargetlab.robot.moqi import build_profile as build_moqi
from retargetlab.robot.openarm import load_openarm_bimanual_profile


class ProcessingConfig(BaseModel):
    """Explicit selection and known-layout binding, not a certification claim."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["0.1"] = "0.1"
    dataset_alias: str = Field(min_length=1)
    source_format: Literal["openarm_eef_sidecar", "mq03_eef"]
    dataset: Path
    robot_asset: Path | None = None
    robot_profile: Path | None = None
    split: Path | None = None
    episode_indices: list[int] | None = None
    backend: Literal["pink", "mink"] = "pink"
    mujoco_model: Path | None = None
    posture_cost: float = Field(default=0.005, ge=0, allow_inf_nan=False)
    solve_options: SolveOptions = Field(
        default_factory=lambda: SolveOptions(
            enable_self_collision_barrier=False,
            qp_eps_abs=1e-8,
            qp_eps_rel=1e-8,
            random_seed=20260911,
        )
    )

    @model_validator(mode="after")
    def validate_selection(self):
        if self.backend == "pink" and (
            self.solve_options.qp_solver != "osqp"
            or self.solve_options.self_collision_recovery_margin_m
            or self.solve_options.self_collision_refinement_steps
        ):
            raise ValueError("DAQP and native collision refinement are registered only for Mink")
        if (self.backend == "mink") != (self.mujoco_model is not None):
            raise ValueError("Mink requires a MuJoCo model directory; Pink does not use one")
        if self.robot_asset is None and self.robot_profile is None:
            raise ValueError("provide a robot asset or a registered robot profile")
        if self.source_format == "openarm_eef_sidecar" and self.robot_profile is not None:
            raise ValueError("OpenArm sidecar currently uses its registered asset directory")
        if self.source_format == "mq03_eef" and self.split is None:
            raise ValueError("mq03_eef requires its calibration/held-out split")
        if self.source_format == "openarm_eef_sidecar" and not self.episode_indices:
            raise ValueError("OpenArm requires explicit development episode_indices")
        if self.episode_indices is not None:
            if (
                not self.episode_indices
                or min(self.episode_indices) < 0
                or len(set(self.episode_indices)) != len(self.episode_indices)
            ):
                raise ValueError("episode_indices must be nonempty unique nonnegative integers")
        if not self.solve_options.enforce_configuration_limits:
            raise ValueError("process requires configuration limits")
        return self


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def load_config(path: Path) -> ProcessingConfig:
    config = ProcessingConfig.model_validate_json(path.read_text())
    for field in ("dataset", "robot_asset", "robot_profile", "split", "mujoco_model"):
        value = getattr(config, field)
        if value is not None:
            setattr(config, field, (path.parent / value).resolve())
    return config


def select_rows(config: ProcessingConfig):
    """Project only EEF/time/index columns; reject held-out selection before I/O."""
    import pyarrow.parquet as pq

    episodes = config.episode_indices
    split_hash = None
    if config.source_format == "mq03_eef":
        import yaml

        split = yaml.safe_load(config.split.read_text())
        calibration = set(split["calibration"]["episode_index"])
        held_out = set(split["held_out"]["episode_index"])
        if calibration & held_out:
            raise ValueError("calibration and held-out overlap")
        episodes = sorted(calibration) if episodes is None else episodes
        if not episodes or not set(episodes) <= calibration or set(episodes) & held_out:
            raise ValueError("process is calibration-only; held-out episodes are excluded")
        split_hash = _hash(config.split)
        fields = {"observation.state": "observation.state", "action": "action"}
        metadata = config.dataset / "meta/info.json"
        info = json.loads(metadata.read_text())
        expected = [
            name
            for side in range(2)
            for name in [
                f"gripper_{side}",
                *[f"epos_{side}_{k}" for k in ("qw", "qx", "qy", "qz", "x", "y", "z")],
            ]
        ]
        for field in fields.values():
            if info["features"][field]["shape"] != [16]:
                raise ValueError(f"MQ03 EEF shape mismatch: {field}")
            if info["features"][field].get("names") != expected:
                raise ValueError(f"MQ03 EEF layout mismatch: {field}")
        source = config.dataset / "data"
    else:
        fields = {"observation.state": "observation.eef", "action": "action.eef"}
        metadata = config.dataset / "manifest.json"
        source = config.dataset / "data/eef.parquet"
    columns = ["episode_index", "frame_index", "timestamp", *fields.values()]
    table = pq.read_table(source, columns=columns, filters=[("episode_index", "in", episodes)])
    rows = sorted(table.to_pylist(), key=lambda row: (row["episode_index"], row["frame_index"]))
    if {row["episode_index"] for row in rows} != set(episodes):
        raise ValueError("selected episodes are empty or missing")
    previous = {}
    for row in rows:
        ep, frame, timestamp = row["episode_index"], row["frame_index"], row["timestamp"]
        if not np.isfinite(timestamp) or timestamp < 0:
            raise ValueError("timestamps must be finite and nonnegative")
        if ep in previous and (frame != previous[ep][0] + 1 or timestamp <= previous[ep][1]):
            raise ValueError("Require contiguous frames and increasing timestamps")
        previous[ep] = (frame, timestamp)
    return (
        rows,
        fields,
        {
            "episode_indices": sorted(episodes),
            "columns_read": columns,
            "selected_rows_sha256": hashlib.sha256(
                json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            ).hexdigest(),
            "metadata_sha256": _hash(metadata),
            "split_sha256": split_hash,
            "held_out_read": False,
            "source_joint_columns_read": False,
        },
    )


def canonical_frame(config, profile, row, field):
    vector = np.asarray(row[field], dtype=float)
    if vector.shape != (16,) or not np.isfinite(vector).all():
        raise ValueError("expected finite 16-dimensional EEF vector")
    poses = {}
    raw_grippers = []
    for group, offset in zip(profile.groups, (0, 8), strict=True):
        if config.source_format == "openarm_eef_sidecar":
            position, quat, gripper = (
                vector[offset : offset + 3],
                vector[offset + 3 : offset + 7],
                vector[offset + 7],
            )
        else:
            position, quat, gripper = (
                vector[offset + 5 : offset + 8],
                vector[offset + 1 : offset + 5],
                vector[offset],
            )
        poses[group.name] = Pose(
            position_m=tuple(position), quaternion_wxyz=tuple(quat), frame=profile.root_frame
        )
        raw_grippers.append(float(gripper))
    return CanonicalFrame(timestamp_s=row["timestamp"], poses=poses), raw_grippers


def _summaries(records):
    groups = {}
    for row in records:
        groups.setdefault((row["episode_index"], row["stream"]), []).append(row)
    summaries = []
    for (episode, stream), rows in sorted(groups.items()):
        ratios = [r["max_velocity_ratio"] for r in rows if r["max_velocity_ratio"] is not None]
        summaries.append(
            {
                "episode_index": episode,
                "stream": stream,
                "frames": len(rows),
                "pose_pass": sum(r["pose_ok"] for r in rows),
                "limit_pass": sum(r["limits_ok"] for r in rows),
                "velocity_checks": len(ratios),
                "velocity_failures": sum(r > 1 + 1e-6 for r in ratios),
                "adjacent_transitions": sum(r["adjacent"] for r in rows),
                "collision_frames": sum(r["collision_free"] is False for r in rows),
                "collision_unassessed": sum(r["collision_free"] is None for r in rows),
                "kinematics_pass": sum(r["kinematics_valid"] for r in rows),
                "max_position_error_m": max(max(r["position_error_m"]) for r in rows),
                "max_orientation_error_rad": max(max(r["orientation_error_rad"]) for r in rows),
                "max_velocity_ratio": max(ratios, default=None),
            }
        )
    return summaries


def process_dataset(config_path: Path, output: Path, progress=None) -> dict:
    """Solve both streams, write diagnostic Parquet and verify its round trip."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    config = load_config(config_path)
    output = output.resolve()
    if output.is_relative_to(config.dataset):
        raise ValueError("output must be outside the read-only source dataset")
    if output.exists():
        raise ValueError("output directory already exists; use a new run directory")
    rows, fields, binding = select_rows(config)
    output.mkdir(parents=True)
    if config.source_format == "openarm_eef_sidecar":
        profile = load_openarm_bimanual_profile(config.robot_asset)
        validate_manifest(config.dataset, Path(profile.asset_dir) / profile.urdf_path)
        gripper_scope = "fixed 0.022m per finger; actual raw-to-aperture mapping unverified"
    else:
        if config.robot_profile is not None:
            profile = RobotProfile.model_validate_json(config.robot_profile.read_text())
            if profile.robot_id != "moqi_mq03_fixed_body" or profile.root_frame != "base_link":
                raise ValueError("MQ03 requires its registered fixed-body profile")
            if profile.collision is None:
                raise ValueError("explicit MQ03 profile must include collision assets")
            binding["robot_profile_sha256"] = _hash(config.robot_profile)
            audit = Path(profile.asset_dir) / "asset-manifest.json"
            if audit.exists():
                binding["asset_manifest_sha256"] = _hash(audit)
                binding["locked_joints"] = json.loads(audit.read_text())["locked_joints"]
            gripper_scope = "source collision meshes; static gripper; raw channel preserved"
        else:
            profile, locked = build_moqi(config.robot_asset, output / "robot-assets")
            binding["locked_joints"] = locked
            gripper_scope = "no dynamic gripper model; raw input preserved separately"
    if config.mujoco_model is not None:
        binding["mujoco_model_manifest_sha256"] = _hash(config.mujoco_model / "manifest.json")
    _json(output / "processing-config.json", config.model_dump(mode="json"))
    _json(output / "robot-profile.json", profile.model_dump(mode="json"))
    _json(
        output / "input-binding.json",
        {
            **binding,
            "source_format": config.source_format,
            "stream_mapping": fields,
            "root_frame": profile.root_frame,
            "pose_mapping": "identity in declared root; input already TCP; no T2 search",
            "position_unit": "m",
            "quaternion_order": "wxyz",
            "gripper_scope": gripper_scope,
        },
    )
    if config.backend == "pink":
        backend = PinkBackend(profile)
        audit = backend.pinocchio_backend
        comparison_collision = backend.collision_model
    else:
        from retargetlab.kinematics.mink_backend import MinkBackend
        from retargetlab.kinematics.pinocchio_backend import PinocchioBackend
        from retargetlab.robot.collision import PinocchioCollisionModel

        audit = PinocchioBackend(profile)
        backend = MinkBackend(
            profile, model_dir=config.mujoco_model, joint_names=list(audit.model.names)[1:]
        )
        comparison_collision = PinocchioCollisionModel(profile) if profile.collision else None
    model = audit.model
    if config.source_format == "mq03_eef":
        expected_names = {f"{side}arm{j}_Joint" for side in ("L", "R") for j in range(1, 8)}
        if model.nq != 14 or set(model.names[1:]) != expected_names:
            raise ValueError("MQ03 target must have exactly the 14 controlled arm joints")
    active = np.array(
        [
            model.joints[model.getJointId(name)].idx_q
            for group in profile.groups
            for name in group.joint_names
        ]
    )
    initial = (model.lowerPositionLimit + model.upperPositionLimit) / 2
    if config.source_format == "mq03_eef":
        initial = np.clip(np.zeros(model.nq), model.lowerPositionLimit, model.upperPositionLimit)
    rng = np.random.default_rng(config.solve_options.random_seed)
    seeds = [initial]
    for _ in range(config.solve_options.retry_seed_count - 1):
        seed = initial.copy()
        seed[active] = rng.uniform(
            model.lowerPositionLimit[active], model.upperPositionLimit[active]
        )
        seeds.append(seed)
    records = []
    started = time.monotonic()
    for stream, field in fields.items():
        previous = None
        for row in rows:
            frame, grippers = canonical_frame(config, profile, row, field)
            same = previous is not None and previous[0] == row["episode_index"]
            dt = frame.timestamp_s - previous[2] if same else None
            candidates = [previous[3]] if same else seeds
            attempts = []
            for seed in candidates:
                result = backend.solve_targets_frame(
                    frame.poses,
                    seed,
                    config.solve_options,
                    previous_q=previous[3] if same else None,
                    sample_dt_s=dt,
                    posture_cost=config.posture_cost,
                )
                attempts.append(result)
                if result.status.value == "CONVERGED":
                    break
            opts = config.solve_options
            best = min(
                attempts,
                key=lambda r: max(
                    r.position_error_m / opts.position_tolerance_m,
                    r.orientation_error_rad / opts.orientation_tolerance_rad,
                ),
            )
            q = np.asarray(best.q)
            errors = []
            for group, target in frame.poses.items():
                position, rotation = audit.fk(group, q)
                errors.append(
                    (
                        float(np.linalg.norm(position - target.position_m)),
                        quaternion_geodesic_angle_rad(rotation, target.quaternion_wxyz),
                    )
                )
            pose_ok = all(
                p <= opts.position_tolerance_m and a <= opts.orientation_tolerance_rad
                for p, a in errors
            )
            if config.backend == "mink" and (
                abs(max(p for p, _ in errors) - best.position_error_m) > 1e-5
                or abs(max(a for _, a in errors) - best.orientation_error_rad) > 1e-4
            ):
                raise RuntimeError("Mink/independent Pinocchio FK result mismatch")
            collision_free = (
                best.collision_free
                if config.backend == "pink"
                else (
                    comparison_collision.report(q).collision_free if comparison_collision else None
                )
            )
            limits_ok = bool(
                (q >= model.lowerPositionLimit - 1e-9).all()
                and (q <= model.upperPositionLimit + 1e-9).all()
            )
            ratio = (
                float(
                    np.max(
                        np.abs(q[active] - previous[3][active]) / dt / model.velocityLimit[active]
                    )
                )
                if same
                else None
            )
            records.append(
                {
                    "episode_index": row["episode_index"],
                    "frame_index": row["frame_index"],
                    "timestamp": frame.timestamp_s,
                    "stream": stream,
                    "source_field": field,
                    "joint_positions": q.tolist(),
                    "source_gripper_raw": grippers,
                    "position_error_m": [p for p, _ in errors],
                    "orientation_error_rad": [a for _, a in errors],
                    "pose_ok": pose_ok,
                    "limits_ok": limits_ok,
                    "max_velocity_ratio": ratio,
                    "adjacent": bool(same and row["frame_index"] == previous[1] + 1),
                    "collision_free": collision_free,
                    "kinematics_valid": pose_ok
                    and limits_ok
                    and (ratio is None or ratio <= 1 + 1e-6),
                    "solver_status": best.status.value,
                    "solver_iterations": best.iterations,
                    "termination_reason": best.termination_reason,
                    "backend_position_error_m": best.position_error_m,
                    "backend_orientation_error_rad": best.orientation_error_rad,
                    "backend_collision_free": best.collision_free
                    if config.backend == "mink"
                    else None,
                    "backend_clearance_ok": best.collision_clearance_ok,
                    "backend_min_distance_m": best.minimum_distance_m,
                }
            )
            previous = (row["episode_index"], row["frame_index"], frame.timestamp_s, q)
            if progress and len(records) % 500 == 0:
                progress(len(records), len(rows) * 2)
    table = pa.Table.from_pylist(records)
    # Stable nullable collision type even for the entire MQ03 dataset with no geometry.
    index = table.schema.get_field_index("collision_free")
    table = table.set_column(
        index, "collision_free", pa.array([r["collision_free"] for r in records], type=pa.bool_())
    )
    table = table.replace_schema_metadata(
        {
            b"artifact_kind": b"diagnostic_joint_trajectories",
            b"joint_names": json.dumps(list(model.names)[1:]).encode(),
            b"gripper_scope": gripper_scope.encode(),
        }
    )
    pq.write_table(table, output / "trajectories.parquet")
    restored = pq.read_table(output / "trajectories.parquet")
    if restored.to_pylist() != records or restored.schema.metadata != table.schema.metadata:
        raise RuntimeError("diagnostic Parquet round-trip mismatch")
    episodes = _summaries(records)
    with (output / "episodes.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(episodes[0]))
        writer.writeheader()
        writer.writerows(episodes)
    summaries = {}
    for stream in fields:
        parts = [row for row in episodes if row["stream"] == stream]
        summaries[stream] = {
            name: sum(r[name] for r in parts)
            for name in (
                "frames",
                "pose_pass",
                "limit_pass",
                "velocity_checks",
                "velocity_failures",
                "collision_frames",
                "collision_unassessed",
                "kinematics_pass",
            )
        }
    report = {
        "schema_version": "processing_report.0.1",
        "status": "COMPLETED",
        "quality_status": "REVIEW_REQUIRED",
        "training_ready": False,
        "dataset_alias": config.dataset_alias,
        "robot_id": profile.robot_id,
        "source_format": config.source_format,
        "backend": config.backend,
        "versions": {
            name: version(name)
            for name in (
                ("pin-pink", "pin", "qpsolvers", "osqp", "pyarrow")
                + (("mink", "mujoco") if config.backend == "mink" else ())
                + (("daqp",) if config.solve_options.qp_solver == "daqp" else ())
            )
        },
        "episodes": len(binding["episode_indices"]),
        "selected_input_frames": len(rows),
        "output_rows": len(records),
        "streams": summaries,
        "joint_names": list(model.names)[1:],
        "controlled_joint_names": [n for g in profile.groups for n in g.joint_names],
        "joint_units": ["rad" if i in active else "m" for i in range(model.nq)],
        "gripper_scope": gripper_scope,
        "collision_scope": (
            "SRDF-filtered self collision at assumed fixed gripper; "
            "no environment or segment checks"
            if profile.collision
            else "NOT_EVALUATED_missing_meshes"
        ),
        "collision_evaluator": "Pinocchio/Coal independent postcheck",
        "native_collision_avoidance": (
            {
                "enabled": config.solve_options.enable_self_collision_barrier,
                "geometry": backend.collision_geometry.summary()
                if backend.collision_geometry
                else None,
                "minimum_distance_m": config.solve_options.self_collision_min_distance_m,
                "recovery_margin_m": config.solve_options.self_collision_recovery_margin_m,
                "constraint_rows_normalized": bool(
                    config.solve_options.self_collision_recovery_margin_m
                ),
                "refinement_steps": config.solve_options.self_collision_refinement_steps,
                "refinement_cut_budget_per_retry": 8,
                "qp_solver": config.solve_options.qp_solver,
                "qp_settings": backend.qp_settings(config.solve_options),
                "detection_distance_m": max(
                    0.02, config.solve_options.self_collision_min_distance_m * 10
                ),
                "units_adapter": "Mink 1.3.0 velocity bound converted to displacement bound",
                "poststep_check": (
                    "all pairs; clear margins preserved, existing violations "
                    "not deepened within 1e-8m numerical tolerance"
                ),
                "swept_volume_checked": False,
            }
            if config.backend == "mink"
            else "OPTIONAL"
        ),
        "export_kind": "diagnostic Parquet; not a LeRobot dataset or certified command stream",
        "parquet_roundtrip": "PASS",
        "elapsed_s": time.monotonic() - started,
        "artifacts": [
            "trajectories.parquet",
            "episodes.csv",
            "report.md",
            "robot-profile.json",
            "input-binding.json",
        ],
    }
    _json(output / "report.json", report)
    lines = [
        f"# {config.dataset_alias}",
        "",
        f"Robot: {profile.robot_id}; backend: {config.backend}.",
        "",
        "Diagnostic export completed. Quality review remains required.",
        "",
        "| Stream | Frames | Pose pass | Limits pass | Speed failures | "
        "Collisions | Collision unassessed |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for stream, r in summaries.items():
        lines.append(
            f"| {stream} | {r['frames']} | {r['pose_pass']} | {r['limit_pass']} | "
            f"{r['velocity_failures']} | {r['collision_frames']} | {r['collision_unassessed']} |"
        )
    lines += [
        "",
        f"Gripper: {gripper_scope}.",
        "",
        "[Episode report](episodes.csv) · [Joint trajectories](trajectories.parquet)",
        "",
        "Source timestamps and row identities retained. No source joint columns read.",
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    source_files = [
        Path(__file__),
        Path(__import__(type(backend).__module__, fromlist=["x"]).__file__),
    ]
    if config.backend == "mink":
        from retargetlab.robot import native_collision

        source_files.append(Path(native_collision.__file__))
    snapshots = output / "code"
    snapshots.mkdir()
    for source in source_files:
        (snapshots / source.name).write_bytes(source.read_bytes())
    _json(
        output / "manifest.json",
        {
            "status": "COMPLETED",
            "config_sha256": _hash(config_path),
            "files": {
                p.relative_to(output).as_posix(): _hash(p) for p in output.rglob("*") if p.is_file()
            },
        },
    )
    return {"command": "process", **report, "output": str(output)}
