"""Calibration-only OpenArm prescreen with separated world/tool semantics."""

from __future__ import annotations

import argparse
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import diagnose_openarm_axis_rotation as metrics
import diagnose_single_arm as single_arm
import numpy as np
import openarm_axis_candidates as transforms
import pinocchio as pin
import probe_openarm_reachability as harness


def audit_tcp(urdf: Path) -> dict:
    """Verify the same local TCP chain and opening axes on both hands."""
    root = ET.parse(urdf).getroot()
    joints = {item.get("name"): item for item in root.findall("joint")}
    sides = {}
    for side in ("left", "right"):
        chain = [
            (
                f"{side}_openarm_hand_joint",
                f"openarm_{side}_link7",
                f"openarm_{side}_hand",
                [0, 0, 0.1001],
            ),
            (
                f"openarm_{side}_hand_tcp_joint",
                f"openarm_{side}_hand",
                f"openarm_{side}_hand_tcp",
                [0, 0, 0.08],
            ),
        ]
        for name, parent, child, xyz in chain:
            joint = joints[name]
            origin = joint.find("origin")
            if (
                joint.get("type") != "fixed"
                or joint.find("parent").get("link") != parent
                or joint.find("child").get("link") != child
                or not np.allclose(np.fromstring(origin.get("xyz"), sep=" "), xyz)
                or not np.allclose(np.fromstring(origin.get("rpy"), sep=" "), 0)
            ):
                raise ValueError("target TCP fixed-chain convention changed")
        for number, axis in ((1, [0, -1, 0]), (2, [0, 1, 0])):
            joint = joints[f"openarm_{side}_finger_joint{number}"]
            if (
                joint.get("type") != "prismatic"
                or joint.find("parent").get("link") != f"openarm_{side}_hand"
                or not np.allclose(np.fromstring(joint.find("axis").get("xyz"), sep=" "), axis)
            ):
                raise ValueError("target finger opening axis changed")
        sides[side] = {
            "link7_to_tcp_translation_m": [0, 0, 0.1801],
            "link7_to_tcp_rotation": np.eye(3).astype(int).tolist(),
            "opening_axis": "plus_minus_y",
            "approach_axis": "plus_z",
        }
    return {
        "evidence": "URDF_VERIFIED",
        "sides": sides,
        "same_local_convention": True,
        "source_to_target_axis_pairing": "INFERRED_CANDIDATE",
    }


def gate(results: list[dict], frame_count: int) -> bool:
    return (
        frame_count == 60
        and len(results) == 2
        and {r["arm"] for r in results} == {"left", "right"}
        and all(
            r["aggregate"]["frame_count"] == 60
            and r["aggregate"]["nominal_rate"] >= 0.8
            and r["aggregate"]["joint_limit_violation_fraction"] == 0
            for r in results
        )
    )


def check_fingerprint(path: Path, expected: str, label: str) -> str:
    """Reject changed or absent inputs without exposing private paths."""
    actual = metrics.sha256_file(path)
    if actual is None or actual != expected:
        raise ValueError(f"{label} differs from frozen recipe")
    return actual


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--candidate-id")
    args = parser.parse_args()
    recipe = harness.load_recipe(args.recipe)
    frame_mapping = recipe["frame_mapping"]
    if (
        frame_mapping["pose_direction"] != "forward"
        or frame_mapping["target_frame"] != "hand_tcp"
        or frame_mapping["side_mapping"] != "direct"
        or not np.array_equal(frame_mapping["world_rotation"], np.eye(3))
    ):
        raise ValueError(
            "this diagnostic requires forward, direct, hand_tcp and identity-world mapping"
        )
    manifest_path = args.asset_dir / "asset_manifest.json"
    input_hashes = {
        "asset_manifest": check_fingerprint(
            manifest_path, recipe["robot"]["asset_manifest_sha256"], "target manifest"
        )
    }
    data_path, episodes_path = harness.data_paths(args.dataset_root)
    source_manifest = recipe["dataset"]["source_manifest"]
    for label, path in (
        ("data_parquet", data_path),
        ("episodes_parquet", episodes_path),
        ("info_json", args.dataset_root / "meta/info.json"),
    ):
        input_hashes[label] = check_fingerprint(path, source_manifest[label + "_sha256"], label)
    manifest = json.loads(manifest_path.read_text())
    urdf = args.asset_dir / "urdf/openarm_bimanual_v10.urdf"
    if metrics.sha256_file(urdf) != manifest["generated_urdf_sha256"]:
        raise ValueError("target URDF differs from its manifest")
    audit = audit_tcp(urdf)
    repo = Path(__file__).resolve().parents[2]
    splits_path = repo / recipe["dataset"]["splits_path"]
    input_hashes["splits"] = check_fingerprint(
        splits_path, recipe["dataset"]["splits_sha256"], "calibration split"
    )
    splits = harness.load_splits(splits_path)
    rows, lengths = harness.load_calibration_rows(args.dataset_root, splits["calibration"])
    indices = harness.pre_screen_indices(
        splits["calibration"], lengths, recipe["t2"]["budget"]["prescreen_frame_fractions"]
    )
    if len(indices) != 60:
        raise ValueError("expected frozen 60-frame calibration prescreen")
    harness.TCP_FRAMES = {side: f"openarm_{side}_hand_tcp" for side in ("left", "right")}
    model, geometry, _ = harness.prepare_geometry(
        args.asset_dir, harness.discover_manifest_srdf(args.asset_dir, None)
    )
    geometry.removeAllCollisionPairs()
    anchor = harness.reachable_cloud_median(
        model,
        recipe["t2"]["anchor"]["point_cloud_samples"],
        recipe["t2"]["anchor"]["point_cloud_random_seed"],
    ) - harness.calibration_midpoint_median(rows)
    options = dict(recipe["solve_options"])
    seeds = harness.target_initialization_configurations(
        model, options["random_seed"], options["retry_seed_count"]
    )
    pos_tol = recipe["reachability"]["nominal"]["position_tolerance_m"]
    rot_tol = math.radians(recipe["reachability"]["nominal"]["orientation_tolerance_deg"])
    relaxed = math.radians(max(recipe["reachability"]["relaxed"]["orientation_range_deg"]))
    candidates = recipe["t2"]["separated_candidates"]
    if args.candidate_id:
        candidates = [c for c in candidates if c["candidate_id"] == args.candidate_id]
        if not candidates:
            raise ValueError("candidate not in frozen recipe")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for candidate in candidates:
        output = args.output_dir / (candidate["candidate_id"] + ".json")
        if output.exists():
            raise FileExistsError("refusing to overwrite a candidate report")
        results = []
        success_by_side = {}
        for side in ("left", "right"):
            aggregate = metrics.aggregate_template()
            success_by_side[side] = []
            for episode, frame in indices:
                source = harness.state_pose(rows[(episode, frame)], side)
                position, rotation = transforms.apply_separated_frame_candidate(
                    source.translation,
                    source.rotation,
                    base_rotation=harness.rotation_z(candidate["yaw_deg"]),
                    base_translation=anchor + np.array(candidate["translation_offset_m"]),
                    world_rotation=frame_mapping["world_rotation"],
                    tool_rotation=frame_mapping["tool_rotation_by_side"][side],
                    pose_direction="forward",
                )
                result = single_arm.solve_pose(
                    model,
                    geometry,
                    side,
                    pin.SE3(rotation, position),
                    seeds,
                    options,
                    pos_tol,
                    rot_tol,
                )
                success_by_side[side].append(
                    not result["joint_limit_violation"]
                    and result["position_error_m"] <= pos_tol
                    and result["orientation_error_rad"] <= rot_tol
                )
                metrics.add_single_arm_result(
                    aggregate,
                    result,
                    position_tolerance=pos_tol,
                    orientation_tolerance=rot_tol,
                    relaxed_orientation_tolerance=relaxed,
                )
            results.append(
                {"arm": side, "aggregate": metrics.finalize_single_arm_aggregate(aggregate)}
            )
        report = {
            "schema_version": "m_minus_1.openarm_separated_frames.v1",
            "recipe_id": recipe["recipe_id"],
            "candidate": candidate,
            "recipe_sha256": metrics.sha256_file(args.recipe),
            "target_urdf_sha256": metrics.sha256_file(urdf),
            "harness_sha256": metrics.sha256_file(Path(__file__)),
            "input_sha256": input_hashes,
            "helper_sha256": {
                module.__name__: metrics.sha256_file(Path(module.__file__))
                for module in (metrics, single_arm, transforms, harness)
            },
            "same_frame_independent_both_nominal_rate": sum(
                left and right
                for left, right in zip(
                    success_by_side["left"], success_by_side["right"], strict=True
                )
            )
            / len(indices),
            "frame_mapping": frame_mapping,
            "target_tcp_audit": audit,
            "sampling": {"split": "calibration", "frame_count": 60, "held_out_read": False},
            "ik_budget": options,
            "single_arm_results": results,
            "bimanual_eligible": gate(results, len(indices)),
            "bimanual_evaluated": False,
            "formal_recipe_promoted": False,
            "collision_evaluation": "not_evaluated_single_arm_pairs_removed",
            "privacy": {
                "raw_values_emitted": False,
                "held_out_values_read": False,
                "training_data_exported": False,
            },
        }
        output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        print(
            json.dumps(
                {
                    "candidate": candidate["candidate_id"],
                    "nominal": {r["arm"]: r["aggregate"]["nominal_rate"] for r in results},
                    "bimanual_eligible": report["bimanual_eligible"],
                }
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
