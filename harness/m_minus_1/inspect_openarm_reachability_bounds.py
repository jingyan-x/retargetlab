"""Necessary geometric bounds for fixed-base OpenArm pose reproduction.

An outside result certifies impossibility for the stated mapping scope.
An inside result does not establish IK feasibility, collision freedom or continuity.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import diagnose_openarm_separated_frames as separated
import numpy as np
import pinocchio as pin
import probe_openarm_reachability as harness
from scipy.optimize import minimize

SIDES = ("left", "right")


def arm_bounds(model):
    """Triangle-inequality outer radii from shoulder joint to link7."""
    data = model.createData()
    pin.forwardKinematics(model, data, pin.neutral(model))
    centers, radii = {}, {}
    for side in SIDES:
        ids = [model.getJointId(f"openarm_{side}_joint{i}") for i in range(1, 8)]
        if ids[0] == 0 or model.parents[ids[0]] != 0:
            raise ValueError("bound requires the fixed-base OpenArm chain")
        if any(model.parents[child] != parent for parent, child in zip(ids, ids[1:])):
            raise ValueError("arm chain changed")
        frame = model.frames[model.getFrameId(f"openarm_{side}_link7")]
        if frame.parentJoint != ids[-1]:
            raise ValueError("link7 is not attached to the last arm joint")
        centers[side] = data.oMi[ids[0]].translation.copy()
        radii[side] = float(
            sum(np.linalg.norm(model.jointPlacements[i].translation) for i in ids[1:])
            + np.linalg.norm(frame.placement.translation)
        )
    return centers, radii


def wrist_tolerance(position_tolerance, orientation_tolerance, tcp_length):
    return position_tolerance + 2 * tcp_length * math.sin(orientation_tolerance / 2)


def enclosing_ball(points):
    """Primal upper and dual lower bounds on the minimum enclosing radius."""
    points = np.asarray(points, dtype=float)
    initial_center = points.mean(axis=0)
    initial_radius2 = np.max(np.sum((points - initial_center) ** 2, axis=1))
    initial = np.r_[initial_center, initial_radius2]
    result = minimize(
        lambda x: x[3],
        initial,
        jac=lambda x: np.array([0.0, 0.0, 0.0, 1.0]),
        method="SLSQP",
        bounds=[(None, None)] * 3 + [(0.0, None)],
        constraints=[
            {
                "type": "ineq",
                "fun": lambda x: x[3] - np.sum((points - x[:3]) ** 2, axis=1),
                "jac": lambda x: np.c_[2 * (points - x[:3]), np.ones(len(points))],
            }
        ],
        options={"ftol": 1e-12, "maxiter": 300},
    )
    center = result.x[:3]
    upper = float(np.max(np.linalg.norm(points - center, axis=1)))
    # Any nonnegative weights summing to one give a valid Jensen dual bound;
    # optimality of the numerical optimizer is not required for that inequality.
    weights = np.maximum(np.asarray(result.multipliers), 0.0)
    if weights.sum() == 0:
        weights = np.ones(len(points))
    weights /= weights.sum()
    weighted_center = weights @ points
    lower2 = weights @ np.sum(points * points, axis=1) - weighted_center @ weighted_center
    lower = math.sqrt(max(0.0, float(lower2)))
    return center, lower, upper, bool(result.success)


def common_translation_bound(wrists, centers, radii, slack):
    if not np.isclose(radii["left"], radii["right"], atol=1e-12, rtol=0):
        raise ValueError("common enclosing-ball audit requires equal target arm radii")
    relative_points = np.concatenate([np.asarray(wrists[side]) - centers[side] for side in SIDES])
    center, lower, upper, success = enclosing_ball(relative_points)
    allowed = radii["left"] + slack
    return {
        "scope": "fixed current world rotation; optimize one common translation only",
        "minimum_required_outer_radius_lower_bound_m": lower,
        "enclosing_outer_radius_upper_bound_m": upper,
        "allowed_radius_with_pose_tolerance_m": allowed,
        "primal_dual_gap_m": upper - lower,
        "optimizer_success": success,
        "candidate_translation_delta_m": (-center).tolist(),
        "a_translation_satisfies_outer_bounds": upper <= allowed + 1e-10,
        "all_translations_ruled_out_by_lower_bound": lower > allowed + 1e-10,
        "passing_outer_bounds_does_not_prove_ik_feasibility": True,
    }


def summarize_bounds(wrists, centers, radii, slack):
    """Conservative exclusions; deliberately ignore restrictive joint limits."""
    count = len(wrists["left"])
    impossible = {}
    fixed = {}
    diameters = {}
    for side in SIDES:
        points = np.asarray(wrists[side])
        distances = np.linalg.norm(points - centers[side], axis=1)
        excess = distances - radii[side] - slack
        impossible[side] = excess > 1e-10
        fixed[side] = {
            "certified_impossible_frames": int(np.count_nonzero(impossible[side])),
            "largest_excess_after_tolerance_m": float(max(0, excess.max())),
        }
        pair_distances = np.linalg.norm(points[:, None] - points[None, :], axis=2)
        diameter_limit = 2 * (radii[side] + slack)
        conflicts = np.triu(pair_distances > diameter_limit + 1e-10, k=1)
        diameters[side] = {
            "pairwise_conflict_count": int(np.count_nonzero(conflicts)),
            "trajectory_diameter_m": float(pair_distances.max()),
            "maximum_allowed_diameter_m": float(diameter_limit),
            "all_frames_fit_one_fixed_placement_ruled_out": bool(np.any(conflicts)),
        }
    fixed_union = int(np.count_nonzero(impossible["left"] | impossible["right"]))
    separation = np.linalg.norm(centers["left"] - centers["right"])
    span_limit = radii["left"] + radii["right"] + separation + 2 * slack
    span = np.linalg.norm(np.asarray(wrists["left"]) - np.asarray(wrists["right"]), axis=1)
    span_bad = int(np.count_nonzero(span > span_limit + 1e-10))
    return {
        "frame_count": count,
        "fixed_current_placement": {
            "arms": fixed,
            "any_arm_certified_impossible_frames": fixed_union,
            "nominal_rate_upper_bound": (count - fixed_union) / count,
        },
        "any_common_rigid_placement": {
            "bimanual_span_certified_impossible_frames": span_bad,
            "nominal_rate_upper_bound_from_span": (count - span_bad) / count,
            "maximum_wrist_span_m": float(span.max()),
            "maximum_allowed_wrist_span_m": float(span_limit),
            "single_arm_trajectory_diameters": diameters,
        },
        "fixed_rotation_common_translation": common_translation_bound(
            wrists, centers, radii, slack
        ),
        "inside_bound_is_not_a_feasibility_certificate": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("refusing to overwrite bounds report")
    repo = Path(__file__).resolve().parents[2]
    recipe = harness.load_recipe(args.recipe)
    manifest_path = args.asset_dir / "asset_manifest.json"
    separated.check_fingerprint(
        manifest_path, recipe["robot"]["asset_manifest_sha256"], "target manifest"
    )
    manifest = json.loads(manifest_path.read_text())
    urdf = args.asset_dir / "urdf/openarm_bimanual_v10.urdf"
    separated.check_fingerprint(urdf, manifest["generated_urdf_sha256"], "target URDF")
    tcp_audit = separated.audit_tcp(urdf)
    data_path, episodes_path = harness.data_paths(args.dataset_root)
    input_hashes = {}
    for label, path in (
        ("data_parquet", data_path),
        ("episodes_parquet", episodes_path),
        ("info_json", args.dataset_root / "meta/info.json"),
    ):
        input_hashes[label] = separated.check_fingerprint(
            path, recipe["dataset"]["source_manifest"][label + "_sha256"], label
        )
    split_path = repo / recipe["dataset"]["splits_path"]
    separated.check_fingerprint(split_path, recipe["dataset"]["splits_sha256"], "split")
    splits = harness.load_splits(split_path)
    rows, lengths = harness.load_calibration_rows(args.dataset_root, splits["calibration"])
    indices = harness.pre_screen_indices(
        splits["calibration"], lengths, recipe["t2"]["budget"]["prescreen_frame_fractions"]
    )
    if len(indices) != 60:
        raise ValueError("expected frozen 60-frame calibration prescreen")
    model, _, _ = harness.prepare_geometry(
        args.asset_dir, harness.discover_manifest_srdf(args.asset_dir, None)
    )
    centers, radii = arm_bounds(model)
    anchor = harness.reachable_cloud_median(
        model,
        recipe["t2"]["anchor"]["point_cloud_samples"],
        recipe["t2"]["anchor"]["point_cloud_random_seed"],
    ) - harness.calibration_midpoint_median(rows)
    if len(recipe["t2"]["separated_candidates"]) != 1:
        raise ValueError("bounds audit requires exactly one frozen T2 candidate")
    candidate = recipe["t2"]["separated_candidates"][0]
    mapping = recipe["frame_mapping"]
    if (
        mapping["pose_direction"] != "forward"
        or mapping["target_frame"] != "hand_tcp"
        or mapping["side_mapping"] != "direct"
    ):
        raise ValueError("bounds audit requires forward/direct hand_tcp semantics")
    # R_tool * [0,0,L] is unchanged by every roll about +z. Identity is
    # representative for wrist bounds, not a claim about the opening axis.
    variants = {
        "current_data_derived": mapping["tool_rotation_by_side"],
        "positive_z_preserving_any_roll": {side: np.eye(3).tolist() for side in SIDES},
    }
    pos_tol = recipe["reachability"]["nominal"]["position_tolerance_m"]
    rot_tol = math.radians(recipe["reachability"]["nominal"]["orientation_tolerance_deg"])
    tcp_length = tcp_audit["sides"]["left"]["link7_to_tcp_translation_m"][2]
    slack = wrist_tolerance(pos_tol, rot_tol, tcp_length)
    results = {}
    for name, tools in variants.items():
        selected_mapping = {**mapping, "tool_rotation_by_side": tools}
        wrists = {side: [] for side in SIDES}
        for episode, frame in indices:
            for side in SIDES:
                target = separated.mapped_target(
                    harness.state_pose(rows[(episode, frame)], side),
                    candidate,
                    anchor,
                    selected_mapping,
                    side,
                )
                wrists[side].append(
                    target.translation - target.rotation @ np.array([0, 0, tcp_length])
                )
        results[name] = {
            "tool_rotations": tools,
            "target_positive_z_in_source_tcp": {
                side: np.asarray(tools[side])[:, 2].tolist() for side in SIDES
            },
            **summarize_bounds(wrists, centers, radii, slack),
        }
    report = {
        "schema_version": "m_minus_1.openarm_geometric_outer_bounds.v1",
        "recipe_id": recipe["recipe_id"],
        "recipe_sha256": harness.sha256_file(args.recipe),
        "harness_sha256": harness.sha256_file(Path(__file__)),
        "target_urdf_sha256": manifest["generated_urdf_sha256"],
        "input_sha256": input_hashes,
        "candidate": candidate,
        "arm_outer_radii_m": radii,
        "tcp_length_m": tcp_length,
        "wrist_tolerance_slack_m": slack,
        "sampling": {"split": "calibration", "frame_count": 60, "held_out_read": False},
        "assumptions": [
            "fixed target base and joint limits unmodified",
            "one common time-independent rigid source-base mapping, no trajectory scaling",
            "source EEF already TCP; subtract target TCP offset only to derive target wrist",
            "positive-z family covers every roll about z; opening-axis mapping is unverified",
            "upper bounds ignore joint-angle restrictions, collisions and continuity",
        ],
        "variants": results,
        "privacy": {
            "raw_pose_values_emitted": False,
            "raw_joint_values_emitted": False,
            "held_out_values_read": False,
            "target_training_data_exported": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                name: {
                    "fixed_impossible_frames": r["fixed_current_placement"][
                        "any_arm_certified_impossible_frames"
                    ],
                    "fixed_upper_bound": r["fixed_current_placement"]["nominal_rate_upper_bound"],
                    "any_placement_span_impossible_frames": r["any_common_rigid_placement"][
                        "bimanual_span_certified_impossible_frames"
                    ],
                    "translation_fit": r["fixed_rotation_common_translation"],
                    "trajectory_conflict_pairs": {
                        side: v["pairwise_conflict_count"]
                        for side, v in r["any_common_rigid_placement"][
                            "single_arm_trajectory_diameters"
                        ].items()
                    },
                }
                for name, r in results.items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
