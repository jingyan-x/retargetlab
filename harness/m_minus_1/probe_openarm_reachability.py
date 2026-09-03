"""Run the disposable M-1.7 OpenArm bimanual reachability harness.

The harness is intentionally independent from ``src/``.  It reads only the
calibration rows from the private sample, applies the frozen T2 candidate
budget, solves both TCP tasks in one shared configuration, and emits aggregate
metrics without source paths, poses, or joint values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pinocchio as pin
import pyarrow.parquet as pq
import yaml
from pink import Configuration, FrameTask, JointCouplingTask, PostureTask, solve_ik
from pink.barriers import SelfCollisionBarrier
from pink.limits import ConfigurationLimit, VelocityLimit

from probe_openarm_collisions import (
    REQUIRED_BODY_PAIRS,
    add_required_body_pairs,
    canonical_pair,
    discover_manifest_srdf,
    load_disabled_pairs,
    pair_name,
)


SCHEMA = "m_minus_1.openarm_reachability.v1"
DATA_COLUMNS = (
    "episode_index",
    "frame_index",
    "observation.state",
    "observation.state.position",
)
TCP_FRAMES = {"left": "openarm_left_hand_tcp", "right": "openarm_right_hand_tcp"}
STATE_POSE_START = {"left": 1, "right": 9}
FRAME_ERROR_DIM = 6

EXPECTED_CONTACT_PAIRS = frozenset(
    {
        canonical_pair(
            "openarm_left_left_finger_0",
            "openarm_left_right_finger_0",
        ),
        canonical_pair(
            "openarm_right_left_finger_0",
            "openarm_right_right_finger_0",
        ),
    }
)


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    dx: float
    dy: float
    dz: float
    yaw_deg: float
    rotation: np.ndarray
    translation: np.ndarray


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_yaml(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path.name}: expected a mapping")
    return document


def load_recipe(path: Path) -> dict[str, Any]:
    recipe = load_yaml(path)
    if recipe.get("stage") != "M-1":
        raise ValueError("reachability harness requires an M-1 recipe")
    if recipe.get("purpose") != "openarm_bimanual_feasibility":
        raise ValueError("recipe purpose is not OpenArm bimanual feasibility")
    return recipe


def load_splits(path: Path) -> dict[str, list[int]]:
    document = load_yaml(path)
    result: dict[str, list[int]] = {}
    for name in ("calibration", "held_out"):
        values = document.get(name, {}).get("episode_index")
        if not isinstance(values, list) or not all(
            isinstance(value, int) for value in values
        ):
            raise ValueError(f"split {name}.episode_index must be integer list")
        result[name] = values
    if set(result["calibration"]) & set(result["held_out"]):
        raise ValueError("calibration and held_out splits overlap")
    return result


def load_sampling_manifest(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("status") != "PASS":
        raise ValueError("calibration sampling manifest is not PASS")
    if report.get("source_paths_emitted") or report.get("held_out_values_read"):
        raise ValueError("sampling manifest violates the private-data boundary")
    sampling = report.get("sampling")
    if not isinstance(sampling, dict):
        raise ValueError("sampling manifest is missing sampling section")
    return report


def data_paths(dataset_root: Path) -> tuple[Path, Path]:
    return (
        dataset_root / "data" / "chunk-000" / "file-000.parquet",
        dataset_root / "meta" / "episodes" / "chunk-000" / "file-000.parquet",
    )


def load_calibration_rows(
    dataset_root: Path,
    calibration: list[int],
) -> tuple[dict[tuple[int, int], dict[str, Any]], dict[int, int]]:
    data_path, episodes_path = data_paths(dataset_root.resolve())
    episodes_table = pq.read_table(
        episodes_path,
        columns=["episode_index", "length"],
    )
    lengths = {
        int(row["episode_index"]): int(row["length"])
        for row in episodes_table.to_pylist()
    }
    missing = sorted(set(calibration) - set(lengths))
    if missing:
        raise ValueError(f"calibration episode metadata missing: {missing}")
    table = pq.read_table(
        data_path,
        columns=list(DATA_COLUMNS),
        filters=[("episode_index", "in", calibration)],
    )
    rows: dict[tuple[int, int], dict[str, Any]] = {}
    for row in table.to_pylist():
        episode = int(row["episode_index"])
        frame = int(row["frame_index"])
        if episode not in calibration:
            raise ValueError("filtered rows include a held_out episode")
        rows[(episode, frame)] = row
    for episode in calibration:
        expected = lengths[episode]
        actual = sorted(frame for ep, frame in rows if ep == episode)
        if len(actual) != expected or actual != list(range(expected)):
            raise ValueError(f"episode {episode} calibration rows are incomplete")
    return rows, {episode: lengths[episode] for episode in calibration}


def require_vector(row: dict[str, Any], key: str, size: int) -> np.ndarray:
    value = row.get(key)
    if value is None or len(value) != size:
        raise ValueError(f"{key} must contain {size} values")
    result = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{key} contains non-finite values")
    return result


def quaternion_to_rotation(values: np.ndarray) -> np.ndarray:
    if values.shape != (4,):
        raise ValueError("quaternion must have four components")
    norm = float(np.linalg.norm(values))
    if norm <= 1e-12 or not math.isfinite(norm):
        raise ValueError("quaternion norm is invalid")
    w, x, y, z = values / norm
    return np.array(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=float,
    )


def state_pose(row: dict[str, Any], side: str) -> pin.SE3:
    state = require_vector(row, "observation.state", 16)
    start = STATE_POSE_START[side]
    rotation = quaternion_to_rotation(state[start : start + 4])
    translation = state[start + 4 : start + 7]
    return pin.SE3(rotation, translation)


def joint_value_index(model: pin.Model, joint_name: str) -> int:
    joint_id = model.getJointId(joint_name)
    if joint_id == 0:
        raise ValueError(f"joint is missing: {joint_name}")
    joint = model.joints[joint_id]
    if joint.nq != 1 or joint.nv != 1:
        raise ValueError(f"joint is not scalar: {joint_name}")
    return int(model.idx_qs[joint_id])


def set_finger_mimic(model: pin.Model, q: np.ndarray) -> None:
    for side in ("left", "right"):
        first = joint_value_index(model, f"openarm_{side}_finger_joint1")
        second = joint_value_index(model, f"openarm_{side}_finger_joint2")
        q[second] = q[first]


def clamp_configuration(model: pin.Model, q: np.ndarray) -> np.ndarray:
    result = np.asarray(q, dtype=float).copy()
    lower = model.lowerPositionLimit
    upper = model.upperPositionLimit
    bounded = np.logical_and(np.isfinite(lower), np.isfinite(upper))
    result[bounded] = np.clip(result[bounded], lower[bounded], upper[bounded])
    set_finger_mimic(model, result)
    return result


def midpoint_configuration(model: pin.Model, reference: np.ndarray) -> np.ndarray:
    q = pin.neutral(model)
    for joint_id, joint in enumerate(model.joints):
        if joint_id == 0 or joint.nq != 1 or joint.nv != 1:
            continue
        index = int(model.idx_qs[joint_id])
        lower = float(model.lowerPositionLimit[index])
        upper = float(model.upperPositionLimit[index])
        if math.isfinite(lower) and math.isfinite(upper) and upper > lower:
            q[index] = 0.5 * (lower + upper)
    for side in ("left", "right"):
        first = joint_value_index(model, f"openarm_{side}_finger_joint1")
        q[first] = reference[first]
    return clamp_configuration(model, q)


def target_reference_configuration(model: pin.Model) -> np.ndarray:
    """Return a deterministic OpenArm seed, independent of anonymous source qpos."""
    return midpoint_configuration(model, pin.neutral(model))


def random_target_configuration(
    model: pin.Model,
    rng: np.random.Generator,
) -> np.ndarray:
    """Create a bounded target-only seed without reading source joint values."""
    q = pin.neutral(model)
    for joint_id, joint in enumerate(model.joints):
        if joint_id == 0 or joint.nq != 1 or joint.nv != 1:
            continue
        index = int(model.idx_qs[joint_id])
        lower = float(model.lowerPositionLimit[index])
        upper = float(model.upperPositionLimit[index])
        if math.isfinite(lower) and math.isfinite(upper) and upper > lower:
            margin = 0.10 * (upper - lower)
            q[index] = rng.uniform(lower + margin, upper - margin)
    return clamp_configuration(model, q)


def target_initialization_configurations(
    model: pin.Model,
    seed: int,
    count: int,
) -> list[np.ndarray]:
    """Return a deterministic, de-duplicated set of target-only configurations."""
    if count < 1:
        raise ValueError("target initialization seed count must be positive")
    neutral = clamp_configuration(model, pin.neutral(model))
    configurations = [neutral, midpoint_configuration(model, neutral)]
    rng = np.random.default_rng(seed)
    while len(configurations) < count:
        candidate = random_target_configuration(model, rng)
        if not any(np.allclose(candidate, existing) for existing in configurations):
            configurations.append(candidate)
    return configurations[:count]


def rotation_z(angle_deg: float) -> np.ndarray:
    angle = math.radians(angle_deg)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return np.array(
        [[cosine, -sine, 0.0], [sine, cosine, 0.0], [0.0, 0.0, 1.0]],
        dtype=float,
    )


def build_candidates(
    anchor_translation: np.ndarray,
    x_offsets: tuple[float, ...] = (-0.10, 0.0, 0.10),
    y_offsets: tuple[float, ...] | None = None,
    z_offsets: tuple[float, ...] | None = None,
    yaw_offsets: tuple[float, ...] = (-10.0, 0.0, 10.0),
) -> list[Candidate]:
    candidates: list[Candidate] = []
    index = 0
    y_offsets = x_offsets if y_offsets is None else y_offsets
    z_offsets = x_offsets if z_offsets is None else z_offsets
    if not x_offsets or not y_offsets or not z_offsets or not yaw_offsets:
        raise ValueError("T2 offset grids must not be empty")
    for dx in x_offsets:
        for dy in y_offsets:
            for dz in z_offsets:
                for yaw in yaw_offsets:
                    candidates.append(
                        Candidate(
                            candidate_id=f"t2-{index:03d}",
                            dx=dx,
                            dy=dy,
                            dz=dz,
                            yaw_deg=yaw,
                            rotation=rotation_z(yaw),
                            translation=anchor_translation
                            + np.array([dx, dy, dz], dtype=float),
                        )
                    )
                    index += 1
    return candidates


def calibration_midpoint_median(
    rows: dict[tuple[int, int], dict[str, Any]],
) -> np.ndarray:
    points = []
    for row in rows.values():
        left = state_pose(row, "left").translation
        right = state_pose(row, "right").translation
        points.append(0.5 * (left + right))
    if not points:
        raise ValueError("calibration contains no EEF poses")
    return np.median(np.asarray(points), axis=0)


def reachable_cloud_median(
    model: pin.Model,
    samples: int,
    seed: int,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    lower = model.lowerPositionLimit
    upper = model.upperPositionLimit
    data = model.createData()
    frame_ids = [model.getFrameId(TCP_FRAMES[side]) for side in ("left", "right")]
    points: list[np.ndarray] = []
    for _ in range(samples):
        q = pin.neutral(model)
        for joint_id, joint in enumerate(model.joints):
            if joint_id == 0 or joint.nq != 1 or joint.nv != 1:
                continue
            index = int(model.idx_qs[joint_id])
            lo = float(lower[index])
            hi = float(upper[index])
            if math.isfinite(lo) and math.isfinite(hi) and hi > lo:
                margin = 0.05 * (hi - lo)
                q[index] = rng.uniform(lo + margin, hi - margin)
        set_finger_mimic(model, q)
        pin.forwardKinematics(model, data, q)
        pin.updateFramePlacements(model, data)
        points.extend(data.oMf[frame_id].translation.copy() for frame_id in frame_ids)
    if not points:
        raise ValueError("reachable point cloud is empty")
    return np.median(np.asarray(points), axis=0)


def transform_pose(candidate: Candidate, pose: pin.SE3) -> pin.SE3:
    return pin.SE3(
        candidate.rotation @ pose.rotation,
        candidate.rotation @ pose.translation + candidate.translation,
    )


def prepare_geometry(
    asset_dir: Path,
    srdf_path: Path | None,
) -> tuple[pin.Model, pin.GeometryModel, dict[str, Any]]:
    asset_dir = asset_dir.resolve()
    urdf_path = asset_dir / "urdf" / "openarm_bimanual_v10.urdf"
    if not urdf_path.is_file():
        raise ValueError("generated OpenArm URDF is missing")
    model = pin.buildModelFromUrdf(str(urdf_path))
    geometry_model = pin.buildGeomFromUrdf(
        model,
        str(urdf_path),
        pin.GeometryType.COLLISION,
        package_dirs=[str(asset_dir)],
    )
    geometry_model.addAllCollisionPairs()
    add_required_body_pairs(geometry_model)
    disabled_pairs, srdf_failures, srdf_available = load_disabled_pairs(
        srdf_path, geometry_model
    )
    if not srdf_available:
        raise ValueError("OpenArm SRDF is unavailable")
    if srdf_failures:
        raise ValueError("OpenArm SRDF contains invalid collision policy")
    if any(
        canonical_pair(*pair) in disabled_pairs for pair in REQUIRED_BODY_PAIRS
    ):
        raise ValueError("SRDF disables a required body-to-link0 pair")
    for pair in list(geometry_model.collisionPairs):
        if pair_name(geometry_model, pair) in disabled_pairs:
            geometry_model.removeCollisionPair(pair)
    return model, geometry_model, {
        "srdf_available": True,
        "srdf_disabled_pair_count": len(disabled_pairs),
        "collision_object_count": len(geometry_model.geometryObjects),
        "collision_pair_count_after_srdf": len(geometry_model.collisionPairs),
        "required_body_pairs_not_disabled": True,
    }


def angle_between_rotations(first: np.ndarray, second: np.ndarray) -> float:
    relative = first.T @ second
    cosine = np.clip((float(np.trace(relative)) - 1.0) / 2.0, -1.0, 1.0)
    return float(math.acos(cosine))


def joint_limit_metrics(model: pin.Model, q: np.ndarray) -> tuple[bool, float]:
    lower = model.lowerPositionLimit
    upper = model.upperPositionLimit
    bounded = np.logical_and(
        np.isfinite(lower),
        np.isfinite(upper),
    )
    violation = bool(
        np.any(q[bounded] < lower[bounded] - 1e-8)
        or np.any(q[bounded] > upper[bounded] + 1e-8)
    )
    ranges = upper[bounded] - lower[bounded]
    valid = ranges > 1e-10
    if not np.any(valid):
        return violation, 1.0
    margins = np.minimum(
        (q[bounded][valid] - lower[bounded][valid]) / ranges[valid],
        (upper[bounded][valid] - q[bounded][valid]) / ranges[valid],
    )
    return violation, float(np.mean(margins))


def max_joint_delta(model: pin.Model, previous: np.ndarray, current: np.ndarray, fps: float) -> float:
    deltas: list[float] = []
    for joint_id, joint in enumerate(model.joints):
        if joint_id == 0 or joint.nq != 1 or joint.nv != 1:
            continue
        q_index = int(model.idx_qs[joint_id])
        v_index = int(model.idx_vs[joint_id])
        velocity_limit = float(model.velocityLimit[v_index])
        if math.isfinite(velocity_limit) and velocity_limit > 0.0:
            deltas.append(
                abs(float(current[q_index] - previous[q_index]))
                / (3.0 * velocity_limit / fps)
            )
    return float(max(deltas, default=0.0))


def make_metrics(
    configuration: Configuration,
    tasks: tuple[FrameTask, FrameTask],
    model: pin.Model,
    geometry_model: pin.GeometryModel,
) -> dict[str, Any]:
    errors: list[np.ndarray] = [task.compute_error(configuration) for task in tasks]
    position_errors = [float(np.linalg.norm(error[:3])) for error in errors]
    orientation_errors = [
        float(np.linalg.norm(error[3:])) for error in errors
    ]
    current_rotations = [
        configuration.get_transform_frame_to_world(TCP_FRAMES[side]).rotation
        for side in ("left", "right")
    ]
    targets = [task.transform_target_to_world for task in tasks]
    if any(target is None for target in targets):
        raise ValueError("frame task target is unset")
    geometric_orientation_errors = [
        angle_between_rotations(current, target.rotation)
        for current, target in zip(current_rotations, targets)
    ]
    limit_violation, limit_margin = joint_limit_metrics(model, configuration.q)
    distances = []
    if configuration.collision_data is not None:
        distances = [
            float(result.min_distance)
            for index, result in enumerate(configuration.collision_data.distanceResults)
            if index < len(geometry_model.collisionPairs)
            and pair_name(geometry_model, geometry_model.collisionPairs[index])
            not in EXPECTED_CONTACT_PAIRS
        ]
    min_distance = min(distances, default=float("inf"))
    return {
        "position_error_m": max(position_errors),
        "orientation_error_rad": max(geometric_orientation_errors),
        "left_position_error_m": position_errors[0],
        "right_position_error_m": position_errors[1],
        "left_orientation_error_rad": geometric_orientation_errors[0],
        "right_orientation_error_rad": geometric_orientation_errors[1],
        "min_distance_m": min_distance,
        "collision": min_distance < -1e-8,
        "penetration": min_distance < -1e-8,
        "joint_limit_violation": limit_violation,
        "joint_limit_margin": limit_margin,
    }


def colliding_pairs(
    model: pin.Model,
    geometry_model: pin.GeometryModel,
    q: np.ndarray,
) -> list[tuple[str, str]]:
    data = model.createData()
    geometry_data = pin.GeometryData(geometry_model)
    pin.forwardKinematics(model, data, q)
    pin.updateGeometryPlacements(model, data, geometry_model, geometry_data)
    pin.computeCollisions(model, data, geometry_model, geometry_data, q, False)
    return [
        pair_name(geometry_model, pair)
        for index, pair in enumerate(geometry_model.collisionPairs)
        if geometry_data.collisionResults[index].isCollision()
    ]


def has_blocking_collision(
    model: pin.Model,
    geometry_model: pin.GeometryModel,
    q: np.ndarray,
) -> bool:
    return any(
        pair not in EXPECTED_CONTACT_PAIRS
        for pair in colliding_pairs(model, geometry_model, q)
    )


def classify_solver_exception(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    if "limit" in name:
        return "LIMIT_VIOLATION"
    if "nan" in name or "finite" in name or "numeric" in name:
        return "NUMERICAL_FAILURE"
    if "solution" in name or "qp" in name or "osqp" in name:
        return "QP_FAILED"
    return "QP_FAILED"


def nominal(metrics: dict[str, Any], position_tolerance: float, orientation_tolerance: float) -> bool:
    return bool(
        not metrics["penetration"]
        and not metrics["joint_limit_violation"]
        and metrics["position_error_m"] <= position_tolerance
        and metrics["orientation_error_rad"] <= orientation_tolerance
    )


def relaxed(metrics: dict[str, Any], position_tolerance: float, orientation_tolerance: float) -> bool:
    return bool(
        not metrics["penetration"]
        and not metrics["joint_limit_violation"]
        and metrics["position_error_m"] <= position_tolerance
        and metrics["orientation_error_rad"] <= orientation_tolerance
    )


def effective_task_costs(
    solve_options: dict[str, Any],
    position_tolerance: float,
    orientation_tolerance: float,
) -> tuple[float, float]:
    position_cost = float(solve_options["position_cost"])
    orientation_cost = float(solve_options["orientation_cost"])
    if bool(solve_options.get("normalize_task_costs", False)):
        position_cost /= max(position_tolerance, 1e-12)
        orientation_cost /= max(orientation_tolerance, 1e-12)
        common_scale = max(position_cost, orientation_cost, 1e-12)
        position_cost /= common_scale
        orientation_cost /= common_scale
    return position_cost, orientation_cost


def _solve_pose_once(
    model: pin.Model,
    geometry_model: pin.GeometryModel,
    seed: np.ndarray,
    target_left: pin.SE3,
    target_right: pin.SE3,
    solve_options: dict[str, Any],
    position_tolerance: float,
    orientation_tolerance: float,
    relaxed_orientation_tolerance: float,
    goal_mode: str,
) -> dict[str, Any]:
    if goal_mode not in {"full_pose", "position_only"}:
        raise ValueError(f"unknown solver goal mode: {goal_mode}")
    seed = clamp_configuration(model, seed)
    configuration = Configuration(
        model,
        model.createData(),
        seed,
        collision_model=geometry_model,
    )
    position_cost, orientation_cost = effective_task_costs(
        solve_options,
        position_tolerance,
        orientation_tolerance,
    )
    if goal_mode == "position_only":
        orientation_cost = 0.0
    left_task = FrameTask(TCP_FRAMES["left"], position_cost, orientation_cost)
    right_task = FrameTask(TCP_FRAMES["right"], position_cost, orientation_cost)
    left_task.set_target(target_left)
    right_task.set_target(target_right)
    posture_task = PostureTask(float(solve_options["posture_cost"]))
    posture_task.set_target(seed)
    coupling_tasks = [
        JointCouplingTask(
            [
                f"openarm_{side}_finger_joint1",
                f"openarm_{side}_finger_joint2",
            ],
            [1.0, -1.0],
            float(solve_options["mimic_constraint_cost"]),
            configuration,
        )
        for side in ("left", "right")
    ]
    limits = [ConfigurationLimit(model), VelocityLimit(model)]
    barriers = (
        [
            SelfCollisionBarrier(
                len(geometry_model.collisionPairs),
                d_min=float(solve_options["self_collision_min_distance_m"]),
            )
        ]
        if geometry_model.collisionPairs
        else []
    )
    tasks = (left_task, right_task)
    best_score = float("inf")
    no_progress = 0
    status = "MAX_ITER"
    iterations = 0
    try:
        for iteration in range(1, int(solve_options["max_iterations"]) + 1):
            iterations = iteration
            metrics = make_metrics(configuration, tasks, model, geometry_model)
            position_reached = bool(
                not metrics["penetration"]
                and not metrics["joint_limit_violation"]
                and metrics["position_error_m"] <= position_tolerance
            )
            if (
                position_reached
                if goal_mode == "position_only"
                else nominal(metrics, position_tolerance, orientation_tolerance)
            ):
                status = "CONVERGED"
                break
            score = metrics["position_error_m"] / position_tolerance
            if goal_mode == "full_pose":
                score = max(
                    score,
                    metrics["orientation_error_rad"] / orientation_tolerance,
                )
            if score < best_score - float(solve_options["no_progress_min_delta"]):
                best_score = score
                no_progress = 0
            else:
                no_progress += 1
            if no_progress >= int(solve_options["no_progress_window"]):
                status = "RESIDUAL_TOO_HIGH"
                break
            velocity = solve_ik(
                configuration,
                [*tasks, posture_task],
                float(solve_options["integration_dt_s"]),
                solver=str(solve_options["qp_solver"]),
                damping=float(solve_options["damping"]),
                limits=limits,
                barriers=barriers,
                constraints=coupling_tasks,
                safety_break=False,
                eps_abs=float(solve_options["qp_eps_abs"]),
                eps_rel=float(solve_options["qp_eps_rel"]),
                max_iter=int(solve_options["qp_max_iterations"]),
                polish=bool(solve_options["qp_polish"]),
            )
            if not np.all(np.isfinite(velocity)):
                status = "NUMERICAL_FAILURE"
                break
            next_q = pin.integrate(
                model,
                configuration.q,
                velocity * float(solve_options["integration_dt_s"]),
            )
            if not np.all(np.isfinite(next_q)):
                status = "NUMERICAL_FAILURE"
                break
            configuration.update(clamp_configuration(model, next_q))
        else:
            status = "MAX_ITER"
    except Exception as exc:  # noqa: BLE001 - disposable harness summarizes status.
        status = classify_solver_exception(exc)
    metrics = make_metrics(configuration, tasks, model, geometry_model)
    if status != "CONVERGED":
        if (
            bool(
                not metrics["penetration"]
                and not metrics["joint_limit_violation"]
                and metrics["position_error_m"] <= position_tolerance
            )
            if goal_mode == "position_only"
            else nominal(metrics, position_tolerance, orientation_tolerance)
        ):
            status = "CONVERGED"
    return {
        "status": status,
        "iterations": iterations,
        "metrics": metrics,
        "relaxed": relaxed(
            metrics,
            position_tolerance,
            relaxed_orientation_tolerance,
        ),
        "q": configuration.q.copy(),
    }


def solve_pose(
    model: pin.Model,
    geometry_model: pin.GeometryModel,
    initial_q: np.ndarray,
    target_left: pin.SE3,
    target_right: pin.SE3,
    solve_options: dict[str, Any],
    position_tolerance: float,
    orientation_tolerance: float,
    relaxed_orientation_tolerance: float,
    preferred_q: np.ndarray | None = None,
    postcheck_geometry_model: pin.GeometryModel | None = None,
    additional_seeds: list[np.ndarray] | None = None,
) -> dict[str, Any]:
    seeds: list[np.ndarray] = []
    for seed in (
        preferred_q,
        initial_q,
        *(additional_seeds or []),
        midpoint_configuration(model, initial_q),
    ):
        if seed is None:
            continue
        candidate = clamp_configuration(model, seed)
        if not any(np.allclose(candidate, existing) for existing in seeds):
            seeds.append(candidate)
    if not seeds:
        raise RuntimeError("no solver seed was available")
    best: dict[str, Any] | None = None
    strategy = str(solve_options.get("solver_strategy", "full_pose"))
    for seed in seeds[: int(solve_options["retry_seed_count"])]:
        if strategy == "position_then_full_pose":
            position_options = dict(solve_options)
            position_options["orientation_cost"] = 0.0
            position_result = _solve_pose_once(
                model,
                geometry_model,
                seed,
                target_left,
                target_right,
                position_options,
                position_tolerance,
                orientation_tolerance,
                relaxed_orientation_tolerance,
                "position_only",
            )
            result = _solve_pose_once(
                model,
                geometry_model,
                position_result["q"],
                target_left,
                target_right,
                solve_options,
                position_tolerance,
                orientation_tolerance,
                relaxed_orientation_tolerance,
                "full_pose",
            )
            result["iterations"] += position_result["iterations"]
            result["position_stage"] = {
                "status": position_result["status"],
                "iterations": position_result["iterations"],
                "metrics": position_result["metrics"],
            }
        elif strategy == "full_pose":
            result = _solve_pose_once(
                model,
                geometry_model,
                seed,
                target_left,
                target_right,
                solve_options,
                position_tolerance,
                orientation_tolerance,
                relaxed_orientation_tolerance,
                "full_pose",
            )
        else:
            raise ValueError(f"unknown solver strategy: {strategy}")
        metrics = result["metrics"]
        quality = (
            0 if nominal(metrics, position_tolerance, orientation_tolerance) else 1,
            max(
                metrics["position_error_m"] / position_tolerance,
                metrics["orientation_error_rad"] / orientation_tolerance,
            ),
            1 if metrics["penetration"] else 0,
            -metrics["joint_limit_margin"],
        )
        if best is None or quality < best["quality"]:
            result["quality"] = quality
            best = result
        if result["status"] == "CONVERGED":
            break
    if best is None:
        raise RuntimeError("no solver seed was available")
    best.pop("quality", None)
    collision = bool(best["metrics"].get("collision", best["metrics"]["penetration"]))
    if postcheck_geometry_model is not None:
        collision = has_blocking_collision(model, postcheck_geometry_model, best["q"])
        best["metrics"]["min_distance_m"] = None
    best["metrics"]["collision"] = collision
    best["metrics"]["penetration"] = collision
    return best


def new_aggregate() -> dict[str, Any]:
    return {
        "total_frames": 0,
        "nominal_frames": 0,
        "relaxed_frames": 0,
        "penetration_frames": 0,
        "joint_limit_violation_frames": 0,
        "delta_violation_frames": 0,
        "collision_barrier_fallbacks": 0,
        "position_error_sum_m": 0.0,
        "orientation_error_sum_rad": 0.0,
        "max_position_error_m": 0.0,
        "max_orientation_error_rad": 0.0,
        "min_distance_m": float("inf"),
        "mean_joint_limit_margin_sum": 0.0,
        "solver_status_counts": Counter(),
    }


def add_result(
    aggregate: dict[str, Any],
    result: dict[str, Any],
    position_tolerance: float,
    orientation_tolerance: float,
    delta_violation: bool = False,
    collision_barrier_fallback: bool = False,
) -> None:
    metrics = result["metrics"]
    aggregate["total_frames"] += 1
    if nominal(metrics, position_tolerance, orientation_tolerance):
        aggregate["nominal_frames"] += 1
    if result["relaxed"]:
        aggregate["relaxed_frames"] += 1
    if metrics["penetration"]:
        aggregate["penetration_frames"] += 1
    if metrics["joint_limit_violation"]:
        aggregate["joint_limit_violation_frames"] += 1
    if delta_violation:
        aggregate["delta_violation_frames"] += 1
    if collision_barrier_fallback:
        aggregate["collision_barrier_fallbacks"] += 1
    aggregate["position_error_sum_m"] += metrics["position_error_m"]
    aggregate["orientation_error_sum_rad"] += metrics["orientation_error_rad"]
    aggregate["max_position_error_m"] = max(
        aggregate["max_position_error_m"], metrics["position_error_m"]
    )
    aggregate["max_orientation_error_rad"] = max(
        aggregate["max_orientation_error_rad"], metrics["orientation_error_rad"]
    )
    if metrics["min_distance_m"] is not None:
        aggregate["min_distance_m"] = min(
            aggregate["min_distance_m"], metrics["min_distance_m"]
        )
    aggregate["mean_joint_limit_margin_sum"] += metrics["joint_limit_margin"]
    aggregate["solver_status_counts"][result["status"]] += 1


def finalize_aggregate(aggregate: dict[str, Any]) -> dict[str, Any]:
    total = int(aggregate["total_frames"])
    if total == 0:
        return {
            "frame_count": 0,
            "nominal_rate": 0.0,
            "relaxed_rate": 0.0,
            "penetration_fraction": 0.0,
            "joint_limit_violation_fraction": 0.0,
            "delta_violation_fraction": 0.0,
            "collision_barrier_fallbacks": 0,
            "mean_position_error_m": None,
            "mean_orientation_error_rad": None,
            "max_position_error_m": None,
            "max_orientation_error_rad": None,
            "minimum_distance_m": None,
            "mean_joint_limit_margin": None,
            "solver_status_counts": {},
        }
    minimum_distance = aggregate["min_distance_m"]
    return {
        "frame_count": total,
        "nominal_rate": aggregate["nominal_frames"] / total,
        "relaxed_rate": aggregate["relaxed_frames"] / total,
        "penetration_fraction": aggregate["penetration_frames"] / total,
        "joint_limit_violation_fraction": aggregate["joint_limit_violation_frames"]
        / total,
        "delta_violation_fraction": aggregate["delta_violation_frames"] / total,
        "collision_barrier_fallbacks": aggregate["collision_barrier_fallbacks"],
        "mean_position_error_m": aggregate["position_error_sum_m"] / total,
        "mean_orientation_error_rad": aggregate["orientation_error_sum_rad"] / total,
        "max_position_error_m": aggregate["max_position_error_m"],
        "max_orientation_error_rad": aggregate["max_orientation_error_rad"],
        "minimum_distance_m": None
        if not math.isfinite(minimum_distance)
        else minimum_distance,
        "mean_joint_limit_margin": aggregate["mean_joint_limit_margin_sum"] / total,
        "solver_status_counts": dict(sorted(aggregate["solver_status_counts"].items())),
    }


def reduced_barrier_geometry(
    full_geometry_model: pin.GeometryModel,
    pair_budget: int,
) -> pin.GeometryModel:
    if pair_budget < len(REQUIRED_BODY_PAIRS):
        raise ValueError("collision barrier pair budget omits required body pairs")
    required = []
    other_pairs = []
    required_names = {canonical_pair(*pair) for pair in REQUIRED_BODY_PAIRS}
    for pair in full_geometry_model.collisionPairs:
        if pair_name(full_geometry_model, pair) in required_names:
            required.append(pair)
        else:
            other_pairs.append(pair)
    selected = required + other_pairs[: pair_budget - len(required)]
    if len(selected) < pair_budget:
        raise ValueError("collision barrier pair budget exceeds available pairs")
    geometry_model = full_geometry_model.copy()
    geometry_model.removeAllCollisionPairs()
    for pair in selected:
        geometry_model.addCollisionPair(pair)
    return geometry_model


def solve_with_collision_fallback(
    model: pin.Model,
    solver_geometry_model: pin.GeometryModel,
    barrier_geometry_model: pin.GeometryModel,
    postcheck_geometry_model: pin.GeometryModel,
    initial_q: np.ndarray,
    target_left: pin.SE3,
    target_right: pin.SE3,
    solve_options: dict[str, Any],
    position_tolerance: float,
    orientation_tolerance: float,
    relaxed_orientation_tolerance: float,
    preferred_q: np.ndarray | None = None,
    additional_seeds: list[np.ndarray] | None = None,
) -> dict[str, Any]:
    result = solve_pose(
        model,
        solver_geometry_model,
        initial_q,
        target_left,
        target_right,
        solve_options,
        position_tolerance,
        orientation_tolerance,
        relaxed_orientation_tolerance,
        preferred_q=preferred_q,
        postcheck_geometry_model=postcheck_geometry_model,
        additional_seeds=additional_seeds,
    )
    if not result["metrics"]["collision"]:
        result["collision_barrier_fallback"] = False
        return result
    fallback = solve_pose(
        model,
        barrier_geometry_model,
        initial_q,
        target_left,
        target_right,
        solve_options,
        position_tolerance,
        orientation_tolerance,
        relaxed_orientation_tolerance,
        preferred_q=result["q"],
        postcheck_geometry_model=postcheck_geometry_model,
        additional_seeds=additional_seeds,
    )
    fallback["collision_barrier_fallback"] = True
    if not fallback["metrics"]["collision"]:
        return fallback
    result["collision_barrier_fallback"] = True
    return result


def pre_screen_indices(
    calibration: list[int],
    lengths: dict[int, int],
    fractions: list[float],
) -> list[tuple[int, int]]:
    return [
        (episode, round(fraction * (lengths[episode] - 1)))
        for episode in calibration
        for fraction in fractions
    ]


def evaluate_candidate_frames(
    candidate: Candidate,
    frame_indices: list[tuple[int, int]],
    rows: dict[tuple[int, int], dict[str, Any]],
    model: pin.Model,
    solver_geometry_model: pin.GeometryModel,
    barrier_geometry_model: pin.GeometryModel,
    postcheck_geometry_model: pin.GeometryModel,
    target_reference_q: np.ndarray,
    target_initialization_seeds: list[np.ndarray],
    solve_options: dict[str, Any],
    position_tolerance: float,
    orientation_tolerance: float,
    relaxed_orientation_tolerance: float,
) -> dict[str, Any]:
    aggregate = new_aggregate()
    for episode, frame in frame_indices:
        row = rows[(episode, frame)]
        result = solve_with_collision_fallback(
            model,
            solver_geometry_model,
            barrier_geometry_model,
            postcheck_geometry_model,
            target_reference_q,
            transform_pose(candidate, state_pose(row, "left")),
            transform_pose(candidate, state_pose(row, "right")),
            solve_options,
            position_tolerance,
            orientation_tolerance,
            relaxed_orientation_tolerance,
            additional_seeds=target_initialization_seeds,
        )
        add_result(
            aggregate,
            result,
            position_tolerance,
            orientation_tolerance,
            collision_barrier_fallback=bool(result["collision_barrier_fallback"]),
        )
    return finalize_aggregate(aggregate)


def evaluate_continuous_segments(
    candidate: Candidate,
    segments: list[dict[str, int]],
    rows: dict[tuple[int, int], dict[str, Any]],
    model: pin.Model,
    solver_geometry_model: pin.GeometryModel,
    barrier_geometry_model: pin.GeometryModel,
    postcheck_geometry_model: pin.GeometryModel,
    target_reference_q: np.ndarray,
    target_initialization_seeds: list[np.ndarray],
    solve_options: dict[str, Any],
    position_tolerance: float,
    orientation_tolerance: float,
    relaxed_orientation_tolerance: float,
    fps: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    aggregate = new_aggregate()
    segment_reports: list[dict[str, Any]] = []
    for segment in segments:
        previous_q: np.ndarray | None = None
        segment_nominal = True
        segment_delta_violations = 0
        segment_statuses: Counter[str] = Counter()
        for frame in range(segment["start_frame_index"], segment["end_frame_index"] + 1):
            row = rows[(segment["episode_index"], frame)]
            result = solve_with_collision_fallback(
                model,
                solver_geometry_model,
                barrier_geometry_model,
                postcheck_geometry_model,
                target_reference_q,
                transform_pose(candidate, state_pose(row, "left")),
                transform_pose(candidate, state_pose(row, "right")),
                solve_options,
                position_tolerance,
                orientation_tolerance,
                relaxed_orientation_tolerance,
                preferred_q=previous_q,
                additional_seeds=target_initialization_seeds,
            )
            delta_violation = False
            if previous_q is not None:
                delta_violation = max_joint_delta(model, previous_q, result["q"], fps) > 1.0
            add_result(
                aggregate,
                result,
                position_tolerance,
                orientation_tolerance,
                delta_violation,
                collision_barrier_fallback=bool(result["collision_barrier_fallback"]),
            )
            segment_statuses[result["status"]] += 1
            segment_nominal = segment_nominal and nominal(
                result["metrics"], position_tolerance, orientation_tolerance
            )
            if delta_violation:
                segment_delta_violations += 1
            previous_q = result["q"]
        segment_reports.append(
            {
                "segment_index": segment["segment_index"],
                "episode_index": segment["episode_index"],
                "start_frame_index": segment["start_frame_index"],
                "length": segment["length"],
                "nominal": segment_nominal and segment_delta_violations == 0,
                "delta_violation_count": segment_delta_violations,
                "solver_status_counts": dict(sorted(segment_statuses.items())),
            }
        )
    result = finalize_aggregate(aggregate)
    result["segment_count"] = len(segments)
    result["passing_segment_count"] = sum(
        bool(report["nominal"]) for report in segment_reports
    )
    result["segment_rate"] = (
        result["passing_segment_count"] / len(segment_reports)
        if segment_reports
        else 0.0
    )
    return result, segment_reports


def candidate_summary(
    candidate: Candidate,
    prescreen: dict[str, Any],
) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "translation_offset_m": [candidate.dx, candidate.dy, candidate.dz],
        "yaw_offset_deg": candidate.yaw_deg,
        "prescreen": prescreen,
    }


def gate_status(
    single: dict[str, Any],
    continuous: dict[str, Any],
    gate: dict[str, Any],
    orientation_relaxation_used: bool,
) -> str:
    penetration = max(
        single["penetration_fraction"], continuous["penetration_fraction"]
    )
    joint_violations = max(
        single["joint_limit_violation_fraction"],
        continuous["joint_limit_violation_fraction"],
    )
    green = (
        single["nominal_rate"] >= float(gate["single_frame_nominal_rate"]["green_min"])
        and continuous["segment_rate"]
        >= float(gate["continuous_segment_rate"]["green_min"])
        and penetration == 0.0
        and joint_violations == 0.0
        and not orientation_relaxation_used
    )
    if green:
        return "GREEN"
    yellow = (
        single["nominal_rate"] >= float(gate["single_frame_nominal_rate"]["yellow_min"])
        and continuous["segment_rate"]
        >= float(gate["continuous_segment_rate"]["yellow_min"])
        and penetration
        <= float(gate["penetration"]["yellow_max_fraction"])
        and joint_violations == 0.0
    )
    return "YELLOW" if yellow else "RED"


def load_frozen_prescreen(
    path: Path,
    recipe: dict[str, Any],
    candidates: list[Candidate],
    prescreen_indices: list[tuple[int, int]],
    sampling: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    try:
        frozen = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("prescreen report cannot be read as JSON") from exc
    if frozen.get("status") != "PASS":
        raise ValueError("prescreen report is not a PASS report")
    if frozen.get("run_mode") != "prescreen_only":
        raise ValueError("prescreen report must be prescreen_only")
    if frozen.get("recipe_id") != recipe["recipe_id"]:
        raise ValueError("prescreen report recipe does not match current recipe")
    if any(
        bool(frozen.get(field))
        for field in (
            "held_out_values_read",
            "private_values_emitted",
            "source_paths_emitted",
        )
    ):
        raise ValueError("prescreen report violates the private-data output policy")

    budget = frozen.get("candidate_budget", {})
    if int(budget.get("candidates_run", -1)) != len(candidates):
        raise ValueError("prescreen report does not cover the complete T2 grid")
    if int(budget.get("expected_candidates", -1)) != len(candidates):
        raise ValueError("prescreen report candidate budget does not match recipe")
    if int(budget.get("prescreen_frame_count", -1)) != len(prescreen_indices):
        raise ValueError("prescreen report sample size does not match recipe")

    frozen_dataset = frozen.get("dataset", {})
    for field in ("data_sha256", "info_sha256", "episodes_sha256"):
        if frozen_dataset.get(field) != sampling["dataset"][field]:
            raise ValueError(f"prescreen report {field} does not match dataset")

    expected = {candidate.candidate_id: candidate for candidate in candidates}
    summaries = frozen.get("candidates")
    if not isinstance(summaries, list) or len(summaries) != len(expected):
        raise ValueError("prescreen report has an incomplete candidate list")
    seen: set[str] = set()
    for summary in summaries:
        candidate_id = summary.get("candidate_id")
        candidate = expected.get(candidate_id)
        if candidate is None or candidate_id in seen:
            raise ValueError("prescreen report candidate IDs do not match recipe")
        if summary.get("translation_offset_m") != [
            candidate.dx,
            candidate.dy,
            candidate.dz,
        ] or summary.get("yaw_offset_deg") != candidate.yaw_deg:
            raise ValueError("prescreen report candidate transform does not match recipe")
        if not isinstance(summary.get("prescreen"), dict):
            raise ValueError("prescreen report candidate has no metrics")
        seen.add(candidate_id)
    if seen != set(expected):
        raise ValueError("prescreen report candidate IDs do not cover the recipe")
    return summaries, sha256_file(path)


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    if args.prescreen_only and args.full_candidate_id is not None:
        raise ValueError("full-candidate-id cannot be used with prescreen-only")
    repo_root = Path(__file__).resolve().parents[2]
    recipe_path = args.recipe.resolve()
    recipe = load_recipe(recipe_path)
    configured_contact_pairs = recipe.get("collision_policy", {}).get(
        "allowed_contact_pairs"
    )
    if configured_contact_pairs is not None:
        try:
            configured_pairs = {
                canonical_pair(str(pair[0]), str(pair[1]))
                for pair in configured_contact_pairs
            }
        except (IndexError, TypeError):
            raise ValueError("recipe collision_policy.allowed_contact_pairs is invalid")
        if configured_pairs != set(EXPECTED_CONTACT_PAIRS):
            raise ValueError(
                "recipe allowed contact pairs do not match the frozen OpenArm policy"
            )
    splits_path = repo_root / recipe["dataset"]["splits_path"]
    splits = load_splits(splits_path)
    sampling_path = repo_root / recipe["sampling"]["calibration_sample_path"]
    sampling = load_sampling_manifest(sampling_path)
    expected_sampling_hash = recipe["sampling"].get("calibration_sample_sha256")
    if expected_sampling_hash and sha256_file(sampling_path) != expected_sampling_hash:
        raise ValueError("sampling manifest hash does not match recipe")
    rows, lengths = load_calibration_rows(args.dataset_root, splits["calibration"])
    solve_options = dict(recipe["solve_options"])
    solve_options.setdefault("posture_cost", 0.01)
    solve_options.setdefault("mimic_constraint_cost", 1.0)
    solve_options.setdefault("self_collision_min_distance_m", 0.0)
    model, geometry_model, collision_report = prepare_geometry(
        args.asset_dir,
        discover_manifest_srdf(args.asset_dir.resolve(), args.srdf),
    )
    target_initialization = str(
        recipe["robot"].get(
            "target_initialization",
            "deterministic_openarm_midpoint_configuration",
        )
    )
    if target_initialization in {
        "deterministic_openarm_seed_set_neutral_midpoint_random",
        "deterministic_target_seed_set_neutral_midpoint_random",
    }:
        target_configurations = target_initialization_configurations(
            model,
            int(solve_options.get("random_seed", 20260902)),
            int(solve_options["retry_seed_count"]),
        )
        target_reference_q = target_configurations[0]
        target_initialization_seeds = target_configurations[1:]
    else:
        target_reference_q = target_reference_configuration(model)
        target_initialization_seeds = []
    barrier_pair_budget = int(solve_options.get("self_collision_barrier_pair_budget", 16))
    barrier_geometry_model = reduced_barrier_geometry(
        geometry_model,
        barrier_pair_budget,
    )
    solver_geometry_model = geometry_model.copy()
    solver_geometry_model.removeAllCollisionPairs()
    collision_report["full_collision_pair_count"] = len(geometry_model.collisionPairs)
    collision_report["solver_collision_pair_count"] = 0
    collision_report["fallback_barrier_pair_count"] = len(
        barrier_geometry_model.collisionPairs
    )
    collision_report["fallback_barrier_strategy"] = (
        "required_body_link0_pairs_plus_deterministic_prefix; "
        "full_geometry_boolean_postcheck"
    )
    collision_report["allowed_contact_pairs"] = [
        list(pair) for pair in sorted(EXPECTED_CONTACT_PAIRS)
    ]
    collision_report["blocking_collision_rule"] = (
        "all_active_collision_pairs_except_allowed_contact_pairs"
    )

    t2 = recipe["t2"]
    anchor_source = calibration_midpoint_median(rows)
    cloud_source = reachable_cloud_median(
        model,
        int(t2["anchor"]["point_cloud_samples"]),
        int(t2["anchor"]["point_cloud_random_seed"]),
    )
    anchor_translation = cloud_source - anchor_source
    translation_grid = t2["grid"]["translation_offsets_m"]
    if isinstance(translation_grid, dict):
        x_offsets = tuple(float(value) for value in translation_grid["x"])
        y_offsets = tuple(float(value) for value in translation_grid["y"])
        z_offsets = tuple(float(value) for value in translation_grid["z"])
    else:
        x_offsets = tuple(float(value) for value in translation_grid)
        y_offsets = x_offsets
        z_offsets = x_offsets
    yaw_offsets = tuple(float(value) for value in t2["grid"]["yaw_offsets_deg"])
    candidates = build_candidates(
        anchor_translation,
        x_offsets=x_offsets,
        y_offsets=y_offsets,
        z_offsets=z_offsets,
        yaw_offsets=yaw_offsets,
    )
    expected_count = int(t2["grid"]["expected_candidate_count"])
    if len(candidates) != expected_count:
        raise ValueError("T2 candidate count does not match recipe")

    position_tolerance = float(recipe["reachability"]["nominal"]["position_tolerance_m"])
    orientation_tolerance = math.radians(
        float(recipe["reachability"]["nominal"]["orientation_tolerance_deg"])
    )
    relaxed_orientation_tolerance = math.radians(
        max(recipe["reachability"]["relaxed"]["orientation_range_deg"])
    )
    calibration = splits["calibration"]
    prescreen_fractions = [
        float(value) for value in t2["budget"]["prescreen_frame_fractions"]
    ]
    prescreen_indices = pre_screen_indices(
        calibration,
        lengths,
        prescreen_fractions,
    )
    if args.frame_limit is not None:
        if args.frame_limit < 1 or args.frame_limit > len(prescreen_indices):
            raise ValueError("frame-limit is outside the prescreen sample")
        prescreen_indices = prescreen_indices[: args.frame_limit]
    prescreen_report_sha256 = None
    if args.prescreen_report is not None:
        if args.prescreen_only:
            raise ValueError("prescreen-report cannot be used with prescreen-only")
        if (
            args.candidate_start is not None
            or args.candidate_limit is not None
            or args.frame_limit is not None
        ):
            raise ValueError(
                "prescreen-report reuse requires the complete candidate and frame budget"
            )
        candidate_start = 0
        candidates_to_run = candidates
        summaries, prescreen_report_sha256 = load_frozen_prescreen(
            args.prescreen_report.resolve(),
            recipe,
            candidates,
            prescreen_indices,
            sampling,
        )
        print(
            "reusing frozen prescreen report",
            file=sys.stderr,
            flush=True,
        )
    else:
        candidate_start = args.candidate_start or 0
        if candidate_start < 0 or candidate_start >= len(candidates):
            raise ValueError("candidate-start is outside the frozen T2 budget")
        candidate_limit = args.candidate_limit or len(candidates) - candidate_start
        if (
            candidate_limit < 1
            or candidate_start + candidate_limit > len(candidates)
        ):
            raise ValueError("candidate-limit is outside the frozen T2 budget")
        candidates_to_run = candidates[
            candidate_start : candidate_start + candidate_limit
        ]
        summaries = []
        for index, candidate in enumerate(candidates_to_run, start=1):
            print(
                f"prescreen candidate {index}/{len(candidates_to_run)}",
                file=sys.stderr,
                flush=True,
            )
            prescreen = evaluate_candidate_frames(
                candidate,
                prescreen_indices,
                rows,
                model,
                solver_geometry_model,
                barrier_geometry_model,
                geometry_model,
                target_reference_q,
                target_initialization_seeds,
                solve_options,
                position_tolerance,
                orientation_tolerance,
                relaxed_orientation_tolerance,
            )
            summaries.append(candidate_summary(candidate, prescreen))

    if args.full_candidate_id is not None and (
        args.prescreen_only or len(candidates_to_run) != len(candidates)
    ):
        raise ValueError(
            "full-candidate-id requires a complete non-prescreen-only candidate budget"
        )

    summaries.sort(
        key=lambda item: (
            -item["prescreen"]["nominal_rate"],
            -item["prescreen"]["mean_joint_limit_margin"],
            item["candidate_id"],
        )
    )
    full_candidates = []
    if not args.prescreen_only and len(candidates_to_run) == len(candidates):
        retain = int(t2["budget"]["retain_top_candidates"])
        full_candidates = summaries[:retain]
        if args.full_candidate_id is not None:
            full_candidates = [
                item
                for item in full_candidates
                if item["candidate_id"] == args.full_candidate_id
            ]
            if len(full_candidates) != 1:
                raise ValueError(
                    "full-candidate-id must identify one of the prescreen top candidates"
                )
        single_frames = [
            (int(episode), int(frame))
            for episode, item in sorted(sampling["sampling"]["single_frames"].items(), key=lambda pair: int(pair[0]))
            for frame in item["frame_indices"]
        ]
        segments = sampling["sampling"]["continuous_segments"]
        for index, summary in enumerate(full_candidates, start=1):
            candidate = next(
                item for item in candidates if item.candidate_id == summary["candidate_id"]
            )
            print(
                f"full candidate {index}/{len(full_candidates)} {candidate.candidate_id}",
                file=sys.stderr,
                flush=True,
            )
            summary["full_single_frames"] = evaluate_candidate_frames(
                candidate,
                single_frames,
                rows,
                model,
                solver_geometry_model,
                barrier_geometry_model,
                geometry_model,
                target_reference_q,
                target_initialization_seeds,
                solve_options,
                position_tolerance,
                orientation_tolerance,
                relaxed_orientation_tolerance,
            )
            continuous, segment_reports = evaluate_continuous_segments(
                candidate,
                segments,
                rows,
                model,
                solver_geometry_model,
                barrier_geometry_model,
                geometry_model,
                target_reference_q,
                target_initialization_seeds,
                solve_options,
                position_tolerance,
                orientation_tolerance,
                relaxed_orientation_tolerance,
                float(sampling["dataset"]["fps"]),
            )
            summary["full_continuous_segments"] = continuous
            summary["continuous_segment_reports"] = segment_reports
        full_candidates.sort(
            key=lambda item: (
                -item["full_single_frames"]["nominal_rate"],
                -item["full_continuous_segments"]["segment_rate"],
                -item["full_single_frames"]["mean_joint_limit_margin"],
                item["candidate_id"],
            )
        )

    report: dict[str, Any] = {
        "schema_version": SCHEMA,
        "status": "PASS",
        "run_mode": "prescreen_only"
        if args.prescreen_only
        else "full_candidate"
        if args.full_candidate_id is not None
        else "full_budget"
        if len(candidates_to_run) == len(candidates)
        else "partial_smoke",
        "recipe_id": recipe["recipe_id"],
        "dataset_alias": recipe["dataset"]["alias"],
        "asset_alias": recipe["robot"]["name"],
        "source_paths_emitted": False,
        "private_values_emitted": False,
        "held_out_values_read": False,
        "dataset": {
            "calibration_episode_count": len(calibration),
            "calibration_frame_count": sum(lengths.values()),
            "single_frame_count": int(sampling["sampling"]["single_frame_total"]),
            "continuous_segment_count": int(
                sampling["sampling"]["continuous_segment_count"]
            ),
            "continuous_segment_length": int(
                sampling["sampling"]["continuous_segment_length"]
            ),
            "data_sha256": sampling["dataset"]["data_sha256"],
            "info_sha256": sampling["dataset"]["info_sha256"],
            "episodes_sha256": sampling["dataset"]["episodes_sha256"],
        },
        "source_joint_usage": {
            "target_fk_used_source_joint_state": False,
            "source_joint_state_loaded_for_schema_only": True,
            "source_joint_state_role": "provenance_only_anonymous_source_model",
            "source_fk_cross_check": "NOT_SUPPORTED_without_source_urdf",
            "target_initialization": target_initialization,
            "target_initialization_seed_count": len(target_initialization_seeds) + 1,
        },
        "frame_semantics": {
            "target_pose_mapping": recipe["robot"].get(
                "orientation_mapping", "identity_dataset_native_hypothesis"
            ),
            "status": recipe["robot"].get("frame_semantics_status", "unconfirmed"),
        },
        "solver": {
            "strategy": str(solve_options.get("solver_strategy", "full_pose")),
            "normalize_task_costs": bool(
                solve_options.get("normalize_task_costs", False)
            ),
            "retry_seed_count": int(solve_options["retry_seed_count"]),
            "effective_position_cost": effective_task_costs(
                solve_options,
                position_tolerance,
                orientation_tolerance,
            )[0],
            "effective_orientation_cost": effective_task_costs(
                solve_options,
                position_tolerance,
                orientation_tolerance,
            )[1],
        },
        "anchor": {
            "source": t2["anchor"]["source"],
            "point_cloud_samples": int(t2["anchor"]["point_cloud_samples"]),
            "point_cloud_random_seed": int(t2["anchor"]["point_cloud_random_seed"]),
            "computed": True,
            "rotation_roll_deg": float(t2["anchor"]["roll_deg"]),
            "rotation_pitch_deg": float(t2["anchor"]["pitch_deg"]),
        },
        "collision_policy": collision_report,
        "prescreen_source": {
            "mode": "reused_frozen_report"
            if prescreen_report_sha256
            else "computed_in_this_run",
            **(
                {"sha256": prescreen_report_sha256}
                if prescreen_report_sha256
                else {}
            ),
        },
        "candidate_budget": {
            "expected_candidates": len(candidates),
            "candidates_run": len(candidates_to_run),
            "candidate_start": candidate_start,
            "translation_offset_count": {
                "x": len(x_offsets),
                "y": len(y_offsets),
                "z": len(z_offsets),
            },
            "yaw_offset_count": len(yaw_offsets),
            "prescreen_frame_count": len(prescreen_indices),
            "retain_top_candidates": int(t2["budget"]["retain_top_candidates"]),
            "full_single_frame_count": int(t2["budget"]["full_single_frame_count"]),
            "full_segment_count": int(t2["budget"]["full_segment_count"]),
            "full_segment_length": int(t2["budget"]["full_segment_length"]),
        },
        "candidates": summaries,
        "full_candidates": full_candidates,
        "full_evaluation": {
            "mode": "single_candidate"
            if args.full_candidate_id is not None
            else "top_candidates"
            if full_candidates
            else "not_run",
            **(
                {"candidate_id": args.full_candidate_id}
                if args.full_candidate_id is not None
                else {}
            ),
        },
        "ranking": list(t2["ranking"]),
    }
    if full_candidates:
        best = full_candidates[0]
        report["best_candidate_id"] = best["candidate_id"]
        report["gate"] = {
            "status": gate_status(
                best["full_single_frames"],
                best["full_continuous_segments"],
                recipe["gate"],
                best["full_single_frames"]["relaxed_rate"]
                > best["full_single_frames"]["nominal_rate"],
            ),
            "single_frame_nominal_rate": best["full_single_frames"]["nominal_rate"],
            "continuous_segment_rate": best["full_continuous_segments"]["segment_rate"],
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--srdf", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-start", type=int)
    parser.add_argument("--candidate-limit", type=int)
    parser.add_argument("--frame-limit", type=int)
    parser.add_argument("--prescreen-only", action="store_true")
    parser.add_argument(
        "--prescreen-report",
        type=Path,
        help="reuse a matching complete prescreen_only report for the full budget",
    )
    parser.add_argument(
        "--full-candidate-id",
        help="evaluate exactly one candidate from the prescreen top-k set",
    )
    args = parser.parse_args()
    try:
        report = build_report(args)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        report = {
            "schema_version": SCHEMA,
            "status": "ERROR",
            "failures": [f"reachability harness failed ({type(exc).__name__})"],
            "source_paths_emitted": False,
            "private_values_emitted": False,
            "held_out_values_read": False,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
