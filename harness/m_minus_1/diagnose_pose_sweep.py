"""Run a small target-only OpenArm solver strategy sweep for one calibration frame."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pinocchio as pin
import probe_openarm_reachability as harness

ORIENTATION_HYPOTHESES = (
    "identity",
    "viser_right",
    "viser_right_inverse",
    "viser_left",
    "viser_left_inverse",
)
SOLVER_VARIANTS = (
    "normalized_position_first",
    "normalized_position_dominant",
    "normalized_position_strict",
    "normalized_full_pose",
    "position_only",
)


def recipe_candidates(
    recipe: dict[str, Any],
    anchor_translation: np.ndarray,
) -> list[harness.Candidate]:
    """Build the exact candidate grid frozen in the supplied recipe."""
    grid = recipe["t2"]["grid"]
    translation_grid = grid["translation_offsets_m"]
    if isinstance(translation_grid, dict):
        x_offsets = tuple(float(value) for value in translation_grid["x"])
        y_offsets = tuple(float(value) for value in translation_grid["y"])
        z_offsets = tuple(float(value) for value in translation_grid["z"])
    else:
        x_offsets = tuple(float(value) for value in translation_grid)
        y_offsets = x_offsets
        z_offsets = x_offsets
    candidates = harness.build_candidates(
        anchor_translation,
        x_offsets=x_offsets,
        y_offsets=y_offsets,
        z_offsets=z_offsets,
        yaw_offsets=tuple(float(value) for value in grid["yaw_offsets_deg"]),
    )
    if len(candidates) != int(grid["expected_candidate_count"]):
        raise ValueError("recipe candidate count does not match its T2 grid")
    return candidates


def apply_orientation_hypothesis(pose: pin.SE3, hypothesis: str) -> pin.SE3:
    orientation_matrix = np.array(
        [[0.0, -1.0, 0.0], [0.0, 0.0, -1.0], [1.0, 0.0, 0.0]],
        dtype=float,
    )
    if hypothesis == "identity":
        rotation = pose.rotation
    elif hypothesis == "viser_right":
        rotation = pose.rotation @ orientation_matrix
    elif hypothesis == "viser_right_inverse":
        rotation = pose.rotation @ orientation_matrix.T
    elif hypothesis == "viser_left":
        rotation = orientation_matrix @ pose.rotation
    elif hypothesis == "viser_left_inverse":
        rotation = orientation_matrix.T @ pose.rotation
    else:
        raise ValueError(f"unknown orientation hypothesis: {hypothesis}")
    return pin.SE3(rotation, pose.translation)


def solver_variants(base_options: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    variants: list[tuple[str, dict[str, Any]]] = []
    for name, strategy, normalize, position_cost, orientation_cost in (
        ("normalized_position_first", "position_then_full_pose", True, 1.0, 1.0),
        ("normalized_position_dominant", "position_then_full_pose", True, 5.0, 1.0),
        ("normalized_position_strict", "position_then_full_pose", True, 25.0, 1.0),
        ("normalized_full_pose", "full_pose", True, 1.0, 1.0),
        ("position_only", "full_pose", True, 1.0, 0.0),
    ):
        options = dict(base_options)
        options.update(
            solver_strategy=strategy,
            normalize_task_costs=normalize,
            position_cost=position_cost,
            orientation_cost=orientation_cost,
        )
        variants.append((name, options))
    return variants


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--candidate-id", default="t2-057")
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument(
        "--sample-mode",
        choices=("single", "prescreen"),
        default="single",
        help="single uses one frame; prescreen uses the frozen calibration fractions",
    )
    parser.add_argument(
        "--frame-limit",
        type=int,
        help="diagnostic-only prefix limit within the frozen prescreen sample",
    )
    parser.add_argument(
        "--variant",
        choices=("all", *SOLVER_VARIANTS),
        default="all",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        help="diagnostic-only outer Pink iteration cap; recorded in the report",
    )
    parser.add_argument(
        "--retry-seed-count",
        type=int,
        help="diagnostic-only seed budget; recorded in the report",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="optional exclusive JSON output path for the aggregate-only report",
    )
    parser.add_argument(
        "--side-mapping",
        choices=("direct", "swapped"),
        default="direct",
        help="diagnostic-only mapping from dataset streams to OpenArm sides",
    )
    parser.add_argument(
        "--target-frame",
        choices=("hand_tcp", "link7"),
        default="hand_tcp",
        help="diagnostic-only target frame hypothesis",
    )
    parser.add_argument(
        "--orientation-hypothesis",
        choices=ORIENTATION_HYPOTHESES,
        default="identity",
        help="diagnostic-only orientation mapping hypothesis",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    recipe = harness.load_recipe(args.recipe.resolve())
    splits = harness.load_splits(repo_root / recipe["dataset"]["splits_path"])
    rows, lengths = harness.load_calibration_rows(args.dataset_root, splits["calibration"])
    model, geometry_model, _ = harness.prepare_geometry(
        args.asset_dir,
        harness.discover_manifest_srdf(args.asset_dir.resolve(), None),
    )
    barrier_geometry_model = harness.reduced_barrier_geometry(
        geometry_model,
        int(recipe["solve_options"].get("self_collision_barrier_pair_budget", 16)),
    )
    solver_geometry_model = geometry_model.copy()
    solver_geometry_model.removeAllCollisionPairs()
    base_options = dict(recipe["solve_options"])
    if args.max_iterations is not None:
        if args.max_iterations < 1:
            raise ValueError("max-iterations must be positive")
        base_options["max_iterations"] = args.max_iterations
    if args.retry_seed_count is not None:
        if args.retry_seed_count < 1:
            raise ValueError("retry-seed-count must be positive")
        base_options["retry_seed_count"] = args.retry_seed_count
    target_configurations = harness.target_initialization_configurations(
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
    candidates = recipe_candidates(recipe, cloud_source - anchor_source)
    try:
        candidate = next(item for item in candidates if item.candidate_id == args.candidate_id)
    except StopIteration as exc:
        raise ValueError("candidate is not present in the recipe T2 grid") from exc

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
    harness.TCP_FRAMES = {
        "left": f"openarm_left_{args.target_frame}",
        "right": f"openarm_right_{args.target_frame}",
    }
    position_tolerance = float(recipe["reachability"]["nominal"]["position_tolerance_m"])
    orientation_tolerance = np.deg2rad(
        float(recipe["reachability"]["nominal"]["orientation_tolerance_deg"])
    )
    relaxed_orientation_tolerance = np.deg2rad(
        max(recipe["reachability"]["relaxed"]["orientation_range_deg"])
    )
    base_options.setdefault("posture_cost", 0.01)
    base_options.setdefault("mimic_constraint_cost", 1.0)
    base_options.setdefault("self_collision_min_distance_m", 0.0)
    variants = solver_variants(base_options)
    if args.variant != "all":
        variants = [item for item in variants if item[0] == args.variant]

    output = []
    for name, options in variants:
        aggregate = harness.new_aggregate()
        failure_reasons: Counter[str] = Counter()
        side_error_sums = Counter()
        side_error_maxima: dict[str, float] = {
            "left_position_error_m": 0.0,
            "right_position_error_m": 0.0,
            "left_orientation_error_rad": 0.0,
            "right_orientation_error_rad": 0.0,
        }
        source_sides = ("left", "right") if args.side_mapping == "direct" else ("right", "left")
        for episode, frame in frame_indices:
            row = rows[(episode, frame)]
            target_left = harness.transform_pose(
                candidate,
                apply_orientation_hypothesis(
                    harness.state_pose(row, source_sides[0]),
                    args.orientation_hypothesis,
                ),
            )
            target_right = harness.transform_pose(
                candidate,
                apply_orientation_hypothesis(
                    harness.state_pose(row, source_sides[1]),
                    args.orientation_hypothesis,
                ),
            )
            result = harness.solve_with_collision_fallback(
                model,
                solver_geometry_model,
                barrier_geometry_model,
                geometry_model,
                target_configurations[0],
                target_left,
                target_right,
                options,
                position_tolerance,
                orientation_tolerance,
                relaxed_orientation_tolerance,
                additional_seeds=target_configurations[1:],
            )
            metrics = result["metrics"]
            harness.add_result(
                aggregate,
                result,
                position_tolerance,
                orientation_tolerance,
                collision_barrier_fallback=bool(result.get("collision_barrier_fallback", False)),
            )
            if metrics["collision"]:
                failure_reasons["collision"] += 1
            if metrics["joint_limit_violation"]:
                failure_reasons["joint_limit"] += 1
            if metrics["position_error_m"] > position_tolerance:
                failure_reasons["position_residual"] += 1
            if metrics["orientation_error_rad"] > orientation_tolerance:
                failure_reasons["orientation_residual"] += 1
            for key in side_error_maxima:
                value = float(metrics[key])
                side_error_sums[key] += value
                side_error_maxima[key] = max(side_error_maxima[key], value)
        summary = harness.finalize_aggregate(aggregate)
        summary["variant"] = name
        summary["failure_reason_counts"] = dict(sorted(failure_reasons.items()))
        summary["side_mean_errors"] = {
            key: side_error_sums[key] / len(frame_indices) for key in side_error_maxima
        }
        summary["side_max_errors"] = side_error_maxima
        summary["mean_orientation_error_deg"] = math.degrees(
            float(summary["mean_orientation_error_rad"])
        )
        summary["max_orientation_error_deg"] = math.degrees(
            float(summary["max_orientation_error_rad"])
        )
        output.append(summary)
    report = {
        "schema_version": "m_minus_1.openarm_pose_diagnostic.v2",
        "status": "PASS",
        "recipe_id": recipe["recipe_id"],
        "candidate_id": args.candidate_id,
        "candidate_translation_offset_m": [
            candidate.dx,
            candidate.dy,
            candidate.dz,
        ],
        "candidate_yaw_offset_deg": candidate.yaw_deg,
        "sample_mode": args.sample_mode,
        "sample_frame_count": len(frame_indices),
        "target_frame_hypothesis": args.target_frame,
        "orientation_hypothesis": args.orientation_hypothesis,
        "side_mapping_hypothesis": args.side_mapping,
        "diagnostic_solve_budget": {
            "max_iterations": int(base_options["max_iterations"]),
            "retry_seed_count": int(base_options["retry_seed_count"]),
            "recipe_budget_overridden": bool(
                args.max_iterations is not None or args.retry_seed_count is not None
            ),
        },
        "source_paths_emitted": False,
        "private_values_emitted": False,
        "selected_frame_indices_emitted": False,
        "held_out_values_read": False,
        "results": output,
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
