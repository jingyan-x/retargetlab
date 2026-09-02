"""Run a small target-only OpenArm solver strategy sweep for one calibration frame."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pinocchio as pin

import probe_openarm_reachability as harness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--candidate-id", default="t2-057")
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument(
        "--target-frame",
        choices=("hand_tcp", "link7"),
        default="hand_tcp",
        help="diagnostic-only target frame hypothesis",
    )
    parser.add_argument(
        "--orientation-hypothesis",
        choices=("identity", "viser_right", "viser_right_inverse", "viser_left", "viser_left_inverse"),
        default="identity",
        help="diagnostic-only orientation mapping hypothesis",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    recipe = harness.load_recipe(args.recipe.resolve())
    splits = harness.load_splits(repo_root / recipe["dataset"]["splits_path"])
    rows, _ = harness.load_calibration_rows(args.dataset_root, splits["calibration"])
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
    target_configurations = harness.target_initialization_configurations(
        model,
        int(recipe["solve_options"].get("random_seed", 20260902)),
        int(recipe["solve_options"]["retry_seed_count"]),
    )
    anchor_source = harness.calibration_midpoint_median(rows)
    cloud_source = harness.reachable_cloud_median(
        model,
        int(recipe["t2"]["anchor"]["point_cloud_samples"]),
        int(recipe["t2"]["anchor"]["point_cloud_random_seed"]),
    )
    candidate = next(
        item
        for item in harness.build_candidates(cloud_source - anchor_source)
        if item.candidate_id == args.candidate_id
    )
    episode = splits["calibration"][0]
    row = rows[(episode, args.frame)]
    orientation_matrix = np.array(
        [[0.0, -1.0, 0.0], [0.0, 0.0, -1.0], [1.0, 0.0, 0.0]],
        dtype=float,
    )

    def apply_orientation_hypothesis(pose: pin.SE3) -> pin.SE3:
        if args.orientation_hypothesis == "identity":
            rotation = pose.rotation
        elif args.orientation_hypothesis == "viser_right":
            rotation = pose.rotation @ orientation_matrix
        elif args.orientation_hypothesis == "viser_right_inverse":
            rotation = pose.rotation @ orientation_matrix.T
        elif args.orientation_hypothesis == "viser_left":
            rotation = orientation_matrix @ pose.rotation
        else:
            rotation = orientation_matrix.T @ pose.rotation
        return pin.SE3(rotation, pose.translation)

    target_left = harness.transform_pose(
        candidate,
        apply_orientation_hypothesis(harness.state_pose(row, "left")),
    )
    target_right = harness.transform_pose(
        candidate,
        apply_orientation_hypothesis(harness.state_pose(row, "right")),
    )
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
    base_options = dict(recipe["solve_options"])
    base_options.setdefault("posture_cost", 0.01)
    base_options.setdefault("mimic_constraint_cost", 1.0)
    base_options.setdefault("self_collision_min_distance_m", 0.0)
    variants: list[tuple[str, dict[str, object]]] = []
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

    output = []
    for name, options in variants:
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
        output.append(
            {
                "variant": name,
                "status": result["status"],
                "iterations": result["iterations"],
                "position_error_m": metrics["position_error_m"],
                "orientation_error_rad": metrics["orientation_error_rad"],
                "left_position_error_m": metrics["left_position_error_m"],
                "right_position_error_m": metrics["right_position_error_m"],
                "left_orientation_error_rad": metrics["left_orientation_error_rad"],
                "right_orientation_error_rad": metrics["right_orientation_error_rad"],
                "collision": metrics["collision"],
                "joint_limit_violation": metrics["joint_limit_violation"],
                "position_stage": result.get("position_stage"),
            }
        )
    print(
        json.dumps(
            {
                "candidate_id": args.candidate_id,
                "target_frame_hypothesis": args.target_frame,
                "orientation_hypothesis": args.orientation_hypothesis,
                "results": output,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
