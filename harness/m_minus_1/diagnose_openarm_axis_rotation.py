"""Prescreen strict data-only OpenArm frame candidates on calibration data.

This harness is intentionally disposable and aggregate-only.  It fixes the
current T2 base candidate, enumerates all 24 proper axis rotations with both
full-pose directions, and applies each rigid candidate to position and
orientation together.  Single-arm calibration prescreening is the first gate;
bimanual evaluation is authorized only for candidates that pass both arms.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pinocchio as pin

sys.path.insert(0, str(Path(__file__).resolve().parent))
import diagnose_pose_sweep as pose_diagnostic
import diagnose_single_arm as single_arm
import openarm_axis_candidates as axis_candidates
import probe_openarm_reachability as harness

DEFAULT_MAX_ITERATIONS = 120
DEFAULT_RETRY_SEED_COUNT = 1
TARGET_FRAMES = ("link7", "hand_tcp")
SIDES = ("left", "right")


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_side_for_target(target_side: str, side_mapping: str) -> str:
    if side_mapping == "direct":
        return target_side
    if side_mapping == "swapped":
        return "right" if target_side == "left" else "left"
    raise ValueError(f"unknown side mapping: {side_mapping}")


def aggregate_template() -> dict[str, Any]:
    return {
        "frame_count": 0,
        "nominal_frames": 0,
        "relaxed_frames": 0,
        "joint_limit_violation_frames": 0,
        "position_error_sum_m": 0.0,
        "orientation_error_sum_rad": 0.0,
        "max_position_error_m": 0.0,
        "max_orientation_error_rad": 0.0,
        "joint_limit_margin_sum": 0.0,
        "min_joint_limit_margin": float("inf"),
        "solver_status_counts": Counter(),
        "failure_reasons": Counter(),
    }


def add_single_arm_result(
    aggregate: dict[str, Any],
    result: dict[str, Any],
    *,
    position_tolerance: float,
    orientation_tolerance: float,
    relaxed_orientation_tolerance: float,
) -> None:
    position_error = float(result["position_error_m"])
    orientation_error = float(result["orientation_error_rad"])
    joint_limit_violation = bool(result["joint_limit_violation"])
    nominal = (
        not joint_limit_violation
        and position_error <= position_tolerance
        and orientation_error <= orientation_tolerance
    )
    relaxed = (
        not joint_limit_violation
        and position_error <= position_tolerance
        and orientation_error <= relaxed_orientation_tolerance
    )
    aggregate["frame_count"] += 1
    aggregate["nominal_frames"] += int(nominal)
    aggregate["relaxed_frames"] += int(relaxed)
    aggregate["joint_limit_violation_frames"] += int(joint_limit_violation)
    aggregate["position_error_sum_m"] += position_error
    aggregate["orientation_error_sum_rad"] += orientation_error
    aggregate["max_position_error_m"] = max(
        aggregate["max_position_error_m"], position_error
    )
    aggregate["max_orientation_error_rad"] = max(
        aggregate["max_orientation_error_rad"], orientation_error
    )
    margin = float(result["joint_limit_margin"])
    aggregate["joint_limit_margin_sum"] += margin
    aggregate["min_joint_limit_margin"] = min(
        aggregate["min_joint_limit_margin"], margin
    )
    status = str(result["status"])
    aggregate["solver_status_counts"][status] += 1
    if status != "CONVERGED":
        aggregate["failure_reasons"][status] += 1
    if joint_limit_violation:
        aggregate["failure_reasons"]["JOINT_LIMIT_VIOLATION"] += 1
    if position_error > position_tolerance:
        aggregate["failure_reasons"]["POSITION_RESIDUAL"] += 1
    if orientation_error > orientation_tolerance:
        aggregate["failure_reasons"]["ORIENTATION_RESIDUAL"] += 1


def finalize_single_arm_aggregate(aggregate: dict[str, Any]) -> dict[str, Any]:
    total = int(aggregate["frame_count"])
    if total == 0:
        return {
            "frame_count": 0,
            "nominal_rate": 0.0,
            "relaxed_rate": 0.0,
            "joint_limit_violation_fraction": 0.0,
            "mean_position_error_m": None,
            "max_position_error_m": None,
            "mean_orientation_error_rad": None,
            "max_orientation_error_rad": None,
            "mean_joint_limit_margin": None,
            "minimum_joint_limit_margin": None,
            "solver_status_counts": {},
            "failure_reasons": {},
        }
    minimum_margin = aggregate["min_joint_limit_margin"]
    return {
        "frame_count": total,
        "nominal_rate": aggregate["nominal_frames"] / total,
        "relaxed_rate": aggregate["relaxed_frames"] / total,
        "joint_limit_violation_fraction": (
            aggregate["joint_limit_violation_frames"] / total
        ),
        "mean_position_error_m": aggregate["position_error_sum_m"] / total,
        "max_position_error_m": aggregate["max_position_error_m"],
        "mean_orientation_error_rad": aggregate["orientation_error_sum_rad"] / total,
        "max_orientation_error_rad": aggregate["max_orientation_error_rad"],
        "mean_joint_limit_margin": aggregate["joint_limit_margin_sum"] / total,
        "minimum_joint_limit_margin": (
            None if not math.isfinite(minimum_margin) else minimum_margin
        ),
        "solver_status_counts": dict(sorted(aggregate["solver_status_counts"].items())),
        "failure_reasons": dict(sorted(aggregate["failure_reasons"].items())),
    }


def failed_solver_result(
    model: pin.Model,
    seed: np.ndarray,
    exc: Exception,
) -> dict[str, Any]:
    return {
        "status": harness.classify_solver_exception(exc),
        "iterations": 0,
        "position_error_m": float("inf"),
        "orientation_error_rad": float("inf"),
        "joint_limit_violation": False,
        "joint_limit_margin": 0.0,
        "q": harness.clamp_configuration(model, seed),
    }


def make_target_pose(
    candidate: axis_candidates.RigidCandidate,
    base_candidate: harness.Candidate,
    source_pose: pin.SE3,
) -> pin.SE3:
    mapped_position, mapped_rotation = axis_candidates.apply_rigid_candidate(
        source_pose.translation,
        source_pose.rotation,
        base_rotation=base_candidate.rotation,
        base_translation=base_candidate.translation,
        axis_rotation=np.asarray(candidate.axis_matrix, dtype=float),
        pose_direction=candidate.pose_direction,
    )
    return pin.SE3(mapped_rotation, mapped_position)


def evaluate_single_arm_candidate(
    candidate: axis_candidates.RigidCandidate,
    base_candidate: harness.Candidate,
    target_side: str,
    frame_indices: list[tuple[int, int]],
    rows: dict[tuple[int, int], dict[str, Any]],
    model: pin.Model,
    geometry_model: pin.GeometryModel,
    target_seeds: list[np.ndarray],
    solve_options: dict[str, Any],
    position_tolerance: float,
    orientation_tolerance: float,
    relaxed_orientation_tolerance: float,
) -> dict[str, Any]:
    aggregate = aggregate_template()
    geometry_model = geometry_model.copy()
    geometry_model.removeAllCollisionPairs()
    source_side = source_side_for_target(target_side, candidate.side_mapping)
    for episode, frame in frame_indices:
        source_pose = harness.state_pose(rows[(episode, frame)], source_side)
        target = make_target_pose(candidate, base_candidate, source_pose)
        try:
            result = single_arm.solve_pose(
                model,
                geometry_model,
                target_side,
                target,
                target_seeds,
                solve_options,
                position_tolerance,
                orientation_tolerance,
            )
        except Exception as exc:  # noqa: BLE001 - aggregate-only diagnostic
            result = failed_solver_result(model, target_seeds[0], exc)
        add_single_arm_result(
            aggregate,
            result,
            position_tolerance=position_tolerance,
            orientation_tolerance=orientation_tolerance,
            relaxed_orientation_tolerance=relaxed_orientation_tolerance,
        )
    return finalize_single_arm_aggregate(aggregate)


def evaluate_bimanual_candidate(
    candidate: axis_candidates.RigidCandidate,
    base_candidate: harness.Candidate,
    frame_indices: list[tuple[int, int]],
    rows: dict[tuple[int, int], dict[str, Any]],
    model: pin.Model,
    full_geometry: pin.GeometryModel,
    target_reference_q: np.ndarray,
    target_seeds: list[np.ndarray],
    solve_options: dict[str, Any],
    position_tolerance: float,
    orientation_tolerance: float,
    relaxed_orientation_tolerance: float,
) -> dict[str, Any]:
    solver_geometry = full_geometry.copy()
    solver_geometry.removeAllCollisionPairs()
    barrier_geometry = harness.reduced_barrier_geometry(
        full_geometry,
        int(solve_options.get("self_collision_barrier_pair_budget", 16)),
    )
    aggregate = harness.new_aggregate()
    source_sides = {
        side: source_side_for_target(side, candidate.side_mapping) for side in SIDES
    }
    for episode, frame in frame_indices:
        row = rows[(episode, frame)]
        target_left = make_target_pose(
            candidate,
            base_candidate,
            harness.state_pose(row, source_sides["left"]),
        )
        target_right = make_target_pose(
            candidate,
            base_candidate,
            harness.state_pose(row, source_sides["right"]),
        )
        result = harness.solve_with_collision_fallback(
            model,
            solver_geometry,
            barrier_geometry,
            full_geometry,
            target_reference_q,
            target_left,
            target_right,
            solve_options,
            position_tolerance,
            orientation_tolerance,
            relaxed_orientation_tolerance,
            additional_seeds=target_seeds,
        )
        harness.add_result(
            aggregate,
            result,
            position_tolerance,
            orientation_tolerance,
            collision_barrier_fallback=bool(result["collision_barrier_fallback"]),
        )
    report = harness.finalize_aggregate(aggregate)
    report["collision_evaluation"] = "full_bimanual_geometry_with_postcheck"
    report["failure_reasons"] = dict(
        sorted(
            {
                **{
                    f"solver_{key}": value
                    for key, value in report["solver_status_counts"].items()
                },
                "penetration": aggregate["penetration_frames"],
                "joint_limit_violation": aggregate["joint_limit_violation_frames"],
            }.items()
        )
    )
    return report


def candidate_descriptor(candidate: axis_candidates.RigidCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "base_candidate_id": candidate.base_candidate_id,
        "rotation_id": candidate.rotation_id,
        "axis_matrix": candidate.axis_matrix,
        "pose_direction": candidate.pose_direction,
        "target_frame": candidate.target_frame,
        "side_mapping": candidate.side_mapping,
        "candidate_sha256": candidate.candidate_hash,
    }


def result_sort_key(result: dict[str, Any]) -> tuple[float, float, float, str]:
    aggregate = result["aggregate"]
    margin = aggregate["mean_joint_limit_margin"]
    return (
        -float(aggregate["nominal_rate"]),
        -float(aggregate["relaxed_rate"]),
        -float(margin) if margin is not None else float("inf"),
        str(result["candidate_id"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--candidate-id", default="t2-023")
    parser.add_argument("--side-mapping", choices=("direct", "swapped"), default="direct")
    parser.add_argument(
        "--target-frame",
        choices=("all", *TARGET_FRAMES),
        default="all",
        help="all compares link7 and hand_tcp; link7 is listed first",
    )
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument("--retry-seed-count", type=int, default=DEFAULT_RETRY_SEED_COUNT)
    parser.add_argument("--frame-limit", type=int)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--mapping-spec", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.max_iterations < 1 or args.retry_seed_count < 1:
        raise ValueError("IK budget values must be positive")
    if args.top_k < 1:
        raise ValueError("top-k must be positive")

    repo_root = Path(__file__).resolve().parents[2]
    recipe = harness.load_recipe(args.recipe.resolve())
    splits = harness.load_splits(repo_root / recipe["dataset"]["splits_path"])
    rows, lengths = harness.load_calibration_rows(args.dataset_root, splits["calibration"])
    frame_indices = harness.pre_screen_indices(
        splits["calibration"],
        lengths,
        [
            float(value)
            for value in recipe["t2"]["budget"]["prescreen_frame_fractions"]
        ],
    )
    if args.frame_limit is not None:
        if args.frame_limit < 1 or args.frame_limit > len(frame_indices):
            raise ValueError("frame-limit is outside the frozen calibration prescreen")
        frame_indices = frame_indices[: args.frame_limit]
    if args.frame_limit is None and len(frame_indices) != 60:
        raise ValueError("the frozen calibration prescreen must contain 60 frames")

    # The base candidate is the existing T2 diagnostic point.  Compute its
    # anchor with the original hand_tcp cloud before testing either target
    # frame, so changing the target frame cannot silently change T2.
    harness.TCP_FRAMES = {
        "left": "openarm_left_hand_tcp",
        "right": "openarm_right_hand_tcp",
    }
    model, full_geometry, _ = harness.prepare_geometry(
        args.asset_dir,
        harness.discover_manifest_srdf(args.asset_dir.resolve(), None),
    )
    anchor_source = harness.calibration_midpoint_median(rows)
    cloud_source = harness.reachable_cloud_median(
        model,
        int(recipe["t2"]["anchor"]["point_cloud_samples"]),
        int(recipe["t2"]["anchor"]["point_cloud_random_seed"]),
    )
    t2_candidates = pose_diagnostic.recipe_candidates(
        recipe,
        cloud_source - anchor_source,
    )
    try:
        base_candidate = next(
            item for item in t2_candidates if item.candidate_id == args.candidate_id
        )
    except StopIteration as exc:
        raise ValueError("candidate is not present in the recipe T2 grid") from exc

    target_frames = TARGET_FRAMES if args.target_frame == "all" else (args.target_frame,)
    candidates = axis_candidates.enumerate_candidates(
        target_frames=target_frames,
        side_mapping=args.side_mapping,
        base_candidate_id=base_candidate.candidate_id,
    )
    rotations = axis_candidates.enumerate_axis_rotations()
    solve_options = dict(recipe["solve_options"])
    solve_options["max_iterations"] = args.max_iterations
    solve_options["retry_seed_count"] = args.retry_seed_count
    solve_options.setdefault("posture_cost", 0.01)
    solve_options.setdefault("mimic_constraint_cost", 1.0)
    target_configurations = harness.target_initialization_configurations(
        model,
        int(solve_options.get("random_seed", 20260902)),
        args.retry_seed_count,
    )
    position_tolerance = float(recipe["reachability"]["nominal"]["position_tolerance_m"])
    orientation_tolerance = math.radians(
        float(recipe["reachability"]["nominal"]["orientation_tolerance_deg"])
    )
    relaxed_orientation_tolerance = math.radians(
        max(float(value) for value in recipe["reachability"]["relaxed"]["orientation_range_deg"])
    )

    single_arm_results: list[dict[str, Any]] = []
    for candidate in candidates:
        harness.TCP_FRAMES = {
            "left": f"openarm_left_{candidate.target_frame}",
            "right": f"openarm_right_{candidate.target_frame}",
        }
        for side in SIDES:
            aggregate = evaluate_single_arm_candidate(
                candidate,
                base_candidate,
                side,
                frame_indices,
                rows,
                model,
                full_geometry.copy(),
                target_configurations,
                solve_options,
                position_tolerance,
                orientation_tolerance,
                relaxed_orientation_tolerance,
            )
            single_arm_results.append(
                {
                    **candidate_descriptor(candidate),
                    "arm": side,
                    "aggregate": aggregate,
                    "collision_evaluation": "not_evaluated_single_arm_collision_pairs_removed",
                }
            )

    results_by_candidate: dict[str, dict[str, dict[str, Any]]] = {}
    for result in single_arm_results:
        results_by_candidate.setdefault(result["candidate_id"], {})[result["arm"]] = result
    shortlist = [
        candidate
        for candidate in candidates
        if all(
            results_by_candidate[candidate.candidate_id][side]["aggregate"]["nominal_rate"]
            >= 0.80
            for side in SIDES
        )
    ]
    shortlist.sort(key=lambda item: item.candidate_id)

    bimanual_results: list[dict[str, Any]] = []
    if shortlist:
        target_reference_q = target_configurations[0]
        additional_seeds = target_configurations[1:]
        for candidate in shortlist:
            harness.TCP_FRAMES = {
                "left": f"openarm_left_{candidate.target_frame}",
                "right": f"openarm_right_{candidate.target_frame}",
            }
            aggregate = evaluate_bimanual_candidate(
                candidate,
                base_candidate,
                frame_indices,
                rows,
                model,
                full_geometry,
                target_reference_q,
                additional_seeds,
                solve_options,
                position_tolerance,
                orientation_tolerance,
                relaxed_orientation_tolerance,
            )
            bimanual_results.append(
                {
                    **candidate_descriptor(candidate),
                    "aggregate": aggregate,
                    "collision_evaluation": aggregate["collision_evaluation"],
                }
            )

    top_single_arm = {}
    for side in SIDES:
        ranked = sorted(
            (item for item in single_arm_results if item["arm"] == side),
            key=result_sort_key,
        )
        top_single_arm[side] = ranked[: args.top_k]
    top_bimanual = sorted(
        bimanual_results,
        key=lambda item: (
            -float(item["aggregate"]["nominal_rate"]),
            -float(item["aggregate"]["relaxed_rate"]),
            -float(item["aggregate"].get("mean_joint_limit_margin") or 0.0),
            str(item["candidate_id"]),
        ),
    )[: args.top_k]

    report = {
        "schema_version": "m_minus_1.openarm_axis_rotation_prescreen.v1",
        "status": "PASS",
        "run_mode": "calibration_single_arm_prescreen_then_gated_bimanual",
        "recipe_id": recipe["recipe_id"],
        "base_candidate_id": base_candidate.candidate_id,
        "semantic_status": "UNRESOLVED",
        "kinematic_status": "RED",
        "robot_status": {
            "panda": {
                "semantic_status": "UNCONFIRMED",
                "kinematic_status": "YELLOW",
            },
            "openarm": {
                "semantic_status": "UNRESOLVED",
                "kinematic_status": "RED",
            },
        },
        "candidate_budget": {
            "axis_rotation_count": len(rotations),
            "pose_direction_count": 2,
            "target_frame_count": len(target_frames),
            "candidate_count": len(candidates),
            "side_mapping": args.side_mapping,
            "side_mapping_role": (
                "formal_default" if args.side_mapping == "direct" else "negative_control_only"
            ),
            "axis_rotation_set_sha256": hashlib.sha256(
                canonical_json([rotation.matrix for rotation in rotations]).encode("utf-8")
            ).hexdigest(),
            "candidate_set_sha256": axis_candidates.candidate_set_hash(candidates),
        },
        "sampling": {
            "split": "calibration",
            "frame_count": len(frame_indices),
            "frozen_prescreen": args.frame_limit is None,
            "held_out_read": False,
        },
        "ik_budget": {
            "max_iterations": args.max_iterations,
            "retry_seed_count": args.retry_seed_count,
            "budget_basis": "current_bounded_openarm_diagnostic",
            "same_budget_for_all_candidates": True,
        },
        "target_frames": list(target_frames),
        "transform_semantics": {
            "position_and_orientation_share_one_rigid_candidate": True,
            "pose_directions": ["forward", "inverse"],
            "source_tcp_offset": "already_baked_into_dataset_eef; not re-applied",
            "source_urdf_required": False,
            "source_urdf_role": "optional_cross_check_only",
        },
        "single_arm": {
            "gate_nominal_rate": 0.80,
            "collision_evaluation": "not_evaluated_single_arm_collision_pairs_removed",
            "results": single_arm_results,
            "top_by_arm": top_single_arm,
        },
        "bimanual": {
            "authorized": bool(shortlist),
            "shortlist_count": len(shortlist),
            "shortlist_candidate_ids": [item.candidate_id for item in shortlist],
            "results": bimanual_results,
            "top": top_bimanual,
            "status": (
                "EVALUATED_SHORTLIST"
                if shortlist
                else "NOT_AUTHORIZED_BELOW_SINGLE_ARM_80_PERCENT_GATE"
            ),
        },
        "inputs": {
            "recipe_sha256": sha256_file(args.recipe.resolve()),
            "mapping_spec_sha256": (
                sha256_file(args.mapping_spec.resolve())
                if args.mapping_spec is not None
                else None
            ),
        },
        "privacy": {
            "private_data_read": True,
            "private_pose_values_read": True,
            "private_values_emitted": False,
            "source_paths_emitted": False,
            "absolute_paths_emitted": False,
            "held_out_values_read": False,
            "target_training_data_modified": False,
            "target_training_data_exported": False,
        },
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists():
            raise FileExistsError(f"refusing to overwrite existing output: {args.output}")
        args.output.write_text(serialized, encoding="utf-8", newline="\n")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
