"""Run a disposable OpenArm single-arm kinematic isolation diagnostic."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pinocchio as pin
from pink import Configuration, FrameTask, JointCouplingTask, PostureTask, solve_ik
from pink.limits import ConfigurationLimit, VelocityLimit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import diagnose_pose_sweep as pose_diagnostic
import probe_openarm_reachability as harness


def solve_once(
    model: pin.Model,
    geometry_model: pin.GeometryModel,
    side: str,
    target: pin.SE3,
    seed: np.ndarray,
    solve_options: dict[str, Any],
    position_tolerance: float,
    orientation_tolerance: float,
    goal_mode: str,
) -> dict[str, Any]:
    if goal_mode not in {"full_pose", "position_only"}:
        raise ValueError(f"unknown goal mode: {goal_mode}")
    configuration = Configuration(
        model,
        model.createData(),
        harness.clamp_configuration(model, seed),
        collision_model=geometry_model,
    )
    position_cost, orientation_cost = harness.effective_task_costs(
        solve_options,
        position_tolerance,
        orientation_tolerance,
    )
    if goal_mode == "position_only":
        orientation_cost = 0.0
    task = FrameTask(harness.TCP_FRAMES[side], position_cost, orientation_cost)
    task.set_target(target)
    posture = PostureTask(float(solve_options["posture_cost"]))
    posture.set_target(seed)
    coupling_tasks = [
        JointCouplingTask(
            [
                f"openarm_{joint_side}_finger_joint1",
                f"openarm_{joint_side}_finger_joint2",
            ],
            [1.0, -1.0],
            float(solve_options["mimic_constraint_cost"]),
            configuration,
        )
        for joint_side in ("left", "right")
    ]
    limits = [ConfigurationLimit(model), VelocityLimit(model)]
    best_score = float("inf")
    no_progress = 0
    status = "MAX_ITER"
    iterations = 0
    for iteration in range(1, int(solve_options["max_iterations"]) + 1):
        iterations = iteration
        error = task.compute_error(configuration)
        position_error = float(np.linalg.norm(error[:3]))
        orientation_error = harness.angle_between_rotations(
            configuration.get_transform_frame_to_world(harness.TCP_FRAMES[side]).rotation,
            target.rotation,
        )
        position_reached = position_error <= position_tolerance
        reached = position_reached if goal_mode == "position_only" else (
            position_reached and orientation_error <= orientation_tolerance
        )
        if reached:
            status = "CONVERGED"
            break
        score = position_error / position_tolerance
        if goal_mode == "full_pose":
            score = max(score, orientation_error / orientation_tolerance)
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
            [task, posture],
            float(solve_options["integration_dt_s"]),
            solver=str(solve_options["qp_solver"]),
            damping=float(solve_options["damping"]),
            limits=limits,
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
        configuration.update(harness.clamp_configuration(model, next_q))
    error = task.compute_error(configuration)
    position_error = float(np.linalg.norm(error[:3]))
    orientation_error = harness.angle_between_rotations(
        configuration.get_transform_frame_to_world(harness.TCP_FRAMES[side]).rotation,
        target.rotation,
    )
    if (
        position_error <= position_tolerance
        and (goal_mode == "position_only" or orientation_error <= orientation_tolerance)
    ):
        status = "CONVERGED"
    limit_violation, limit_margin = harness.joint_limit_metrics(model, configuration.q)
    return {
        "status": status,
        "iterations": iterations,
        "position_error_m": position_error,
        "orientation_error_rad": orientation_error,
        "joint_limit_violation": limit_violation,
        "joint_limit_margin": limit_margin,
        "q": configuration.q.copy(),
    }


def solve_pose(
    model: pin.Model,
    geometry_model: pin.GeometryModel,
    side: str,
    target: pin.SE3,
    seeds: list[np.ndarray],
    solve_options: dict[str, Any],
    position_tolerance: float,
    orientation_tolerance: float,
) -> dict[str, Any]:
    best: dict[str, Any] | None = None
    strategy = str(solve_options.get("solver_strategy", "full_pose"))
    for seed in seeds[: int(solve_options["retry_seed_count"])]:
        if strategy == "position_then_full_pose":
            position_options = dict(solve_options)
            position_options["orientation_cost"] = 0.0
            position_result = solve_once(
                model,
                geometry_model,
                side,
                target,
                seed,
                position_options,
                position_tolerance,
                orientation_tolerance,
                "position_only",
            )
            result = solve_once(
                model,
                geometry_model,
                side,
                target,
                position_result["q"],
                solve_options,
                position_tolerance,
                orientation_tolerance,
                "full_pose",
            )
            result["iterations"] += position_result["iterations"]
        elif strategy == "full_pose":
            result = solve_once(
                model,
                geometry_model,
                side,
                target,
                seed,
                solve_options,
                position_tolerance,
                orientation_tolerance,
                "full_pose",
            )
        else:
            raise ValueError(f"unknown solver strategy: {strategy}")
        quality = (
            0
            if (
                not result["joint_limit_violation"]
                and result["position_error_m"] <= position_tolerance
                and result["orientation_error_rad"] <= orientation_tolerance
            )
            else 1,
            max(
                result["position_error_m"] / position_tolerance,
                result["orientation_error_rad"] / orientation_tolerance,
            ),
            -result["joint_limit_margin"],
        )
        if best is None or quality < best["quality"]:
            result["quality"] = quality
            best = result
        if result["status"] == "CONVERGED":
            break
    if best is None:
        raise RuntimeError("no solver seed was available")
    best.pop("quality", None)
    return best


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--candidate-id", default="t2-023")
    parser.add_argument("--arm", choices=("left", "right"), required=True)
    parser.add_argument("--sample-mode", choices=("single", "prescreen"), default="prescreen")
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--frame-limit", type=int)
    parser.add_argument("--target-frame", choices=("hand_tcp", "link7"), default="hand_tcp")
    parser.add_argument(
        "--orientation-hypothesis",
        choices=pose_diagnostic.ORIENTATION_HYPOTHESES,
        default="identity",
    )
    parser.add_argument("--max-iterations", type=int)
    parser.add_argument("--retry-seed-count", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    recipe = harness.load_recipe(args.recipe.resolve())
    splits = harness.load_splits(repo_root / recipe["dataset"]["splits_path"])
    rows, lengths = harness.load_calibration_rows(args.dataset_root, splits["calibration"])
    model, geometry_model, _ = harness.prepare_geometry(
        args.asset_dir,
        harness.discover_manifest_srdf(args.asset_dir.resolve(), None),
    )
    no_collision_geometry = geometry_model.copy()
    no_collision_geometry.removeAllCollisionPairs()
    base_options = dict(recipe["solve_options"])
    if args.max_iterations is not None:
        if args.max_iterations < 1:
            raise ValueError("max-iterations must be positive")
        base_options["max_iterations"] = args.max_iterations
    if args.retry_seed_count is not None:
        if args.retry_seed_count < 1:
            raise ValueError("retry-seed-count must be positive")
        base_options["retry_seed_count"] = args.retry_seed_count
    base_options.setdefault("posture_cost", 0.01)
    base_options.setdefault("mimic_constraint_cost", 1.0)
    target_seeds = harness.target_initialization_configurations(
        model,
        int(base_options.get("random_seed", 20260902)),
        int(base_options["retry_seed_count"]),
    )
    anchor_source = harness.calibration_midpoint_median(rows)
    cloud_source = harness.reachable_cloud_median(
        model,
        int(recipe["t2"]["anchor"]["point_cloud_samples"]),
        int(recipe["t2"]["anchor"]["point_cloud_random_seed"]),
    )
    candidates = pose_diagnostic.recipe_candidates(recipe, cloud_source - anchor_source)
    try:
        candidate = next(item for item in candidates if item.candidate_id == args.candidate_id)
    except StopIteration as exc:
        raise ValueError("candidate is not present in the recipe T2 grid") from exc

    harness.TCP_FRAMES = {
        "left": f"openarm_left_{args.target_frame}",
        "right": f"openarm_right_{args.target_frame}",
    }
    position_tolerance = float(recipe["reachability"]["nominal"]["position_tolerance_m"])
    orientation_tolerance = math.radians(
        float(recipe["reachability"]["nominal"]["orientation_tolerance_deg"])
    )
    if args.sample_mode == "single":
        frame_indices = [(splits["calibration"][0], args.frame)]
    else:
        frame_indices = harness.pre_screen_indices(
            splits["calibration"],
            lengths,
            [float(value) for value in recipe["t2"]["budget"]["prescreen_frame_fractions"]],
        )
        if args.frame_limit is not None:
            if args.frame_limit < 1 or args.frame_limit > len(frame_indices):
                raise ValueError("frame-limit is outside the frozen prescreen sample")
            frame_indices = frame_indices[: args.frame_limit]

    statuses: Counter[str] = Counter()
    nominal_count = 0
    position_sum = 0.0
    orientation_sum = 0.0
    position_max = 0.0
    orientation_max = 0.0
    joint_limit_count = 0
    margin_sum = 0.0
    for episode, frame in frame_indices:
        row = rows[(episode, frame)]
        source_pose = harness.state_pose(row, args.arm)
        mapped_pose = pose_diagnostic.apply_orientation_hypothesis(
            source_pose,
            args.orientation_hypothesis,
        )
        target = harness.transform_pose(candidate, mapped_pose)
        result = solve_pose(
            model,
            no_collision_geometry,
            args.arm,
            target,
            target_seeds,
            base_options,
            position_tolerance,
            orientation_tolerance,
        )
        statuses[result["status"]] += 1
        nominal = (
            not result["joint_limit_violation"]
            and result["position_error_m"] <= position_tolerance
            and result["orientation_error_rad"] <= orientation_tolerance
        )
        nominal_count += int(nominal)
        joint_limit_count += int(result["joint_limit_violation"])
        position_sum += result["position_error_m"]
        orientation_sum += result["orientation_error_rad"]
        position_max = max(position_max, result["position_error_m"])
        orientation_max = max(orientation_max, result["orientation_error_rad"])
        margin_sum += result["joint_limit_margin"]

    total = len(frame_indices)
    report = {
        "schema_version": "m_minus_1.openarm_single_arm_diagnostic.v1",
        "status": "PASS",
        "recipe_id": recipe["recipe_id"],
        "candidate_id": candidate.candidate_id,
        "candidate_translation_offset_m": [candidate.dx, candidate.dy, candidate.dz],
        "candidate_yaw_offset_deg": candidate.yaw_deg,
        "arm": args.arm,
        "sample_mode": args.sample_mode,
        "sample_frame_count": total,
        "target_frame_hypothesis": args.target_frame,
        "orientation_hypothesis": args.orientation_hypothesis,
        "constraint_mode": "single_arm_no_collision",
        "diagnostic_solve_budget": {
            "max_iterations": int(base_options["max_iterations"]),
            "retry_seed_count": int(base_options["retry_seed_count"]),
            "recipe_budget_overridden": bool(
                args.max_iterations is not None or args.retry_seed_count is not None
            ),
        },
        "aggregate": {
            "nominal_rate": nominal_count / total if total else 0.0,
            "joint_limit_violation_fraction": joint_limit_count / total if total else 0.0,
            "mean_position_error_m": position_sum / total if total else None,
            "max_position_error_m": position_max if total else None,
            "mean_orientation_error_rad": orientation_sum / total if total else None,
            "max_orientation_error_rad": orientation_max if total else None,
            "mean_joint_limit_margin": margin_sum / total if total else None,
            "solver_status_counts": dict(sorted(statuses.items())),
        },
        "source_paths_emitted": False,
        "private_values_emitted": False,
        "selected_frame_indices_emitted": False,
        "held_out_values_read": False,
    }
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
