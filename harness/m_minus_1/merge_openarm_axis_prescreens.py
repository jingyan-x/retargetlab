"""Merge link7 and hand_tcp OpenArm axis-rotation prescreen reports."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

EXPECTED_SCHEMA = "m_minus_1.openarm_axis_rotation_prescreen.v1"
SIDES = ("left", "right")


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("schema_version") != EXPECTED_SCHEMA:
        raise ValueError("axis prescreen report has an unexpected schema")
    if report.get("status") != "PASS":
        raise ValueError("axis prescreen report is not PASS")
    if report.get("bimanual", {}).get("authorized"):
        raise ValueError("source report must be a single-arm-only prescreen")
    if report.get("sampling", {}).get("frame_count") != 60:
        raise ValueError("source report must cover the frozen 60-frame calibration prescreen")
    return report


def result_sort_key(result: dict[str, Any]) -> tuple[float, float, float, str]:
    aggregate = result["aggregate"]
    margin = aggregate["mean_joint_limit_margin"]
    return (
        -float(aggregate["nominal_rate"]),
        -float(aggregate["relaxed_rate"]),
        -float(margin) if margin is not None else float("inf"),
        str(result["candidate_id"]),
    )


def build_report(link7_path: Path, hand_tcp_path: Path) -> dict[str, Any]:
    link7 = load_report(link7_path)
    hand_tcp = load_report(hand_tcp_path)
    for field in ("recipe_id", "base_candidate_id", "semantic_status", "kinematic_status"):
        if link7.get(field) != hand_tcp.get(field):
            raise ValueError(f"source reports disagree on {field}")
    if link7.get("ik_budget") != hand_tcp.get("ik_budget"):
        raise ValueError("source reports use different IK budgets")
    if link7.get("candidate_budget", {}).get("side_mapping") != "direct" or hand_tcp.get(
        "candidate_budget", {}
    ).get("side_mapping") != "direct":
        raise ValueError("only the direct mapping is a formal prescreen")

    results = list(link7["single_arm"]["results"]) + list(hand_tcp["single_arm"]["results"])
    candidate_ids = [str(result["candidate_id"]) for result in results]
    if len(candidate_ids) != 192 or len(set(candidate_ids)) != 96:
        raise ValueError("merged result coverage must contain 96 candidates and two arms each")
    candidate_descriptors = {
        result["candidate_id"]: {
            key: result[key]
            for key in (
                "candidate_id",
                "base_candidate_id",
                "rotation_id",
                "axis_matrix",
                "pose_direction",
                "target_frame",
                "side_mapping",
                "candidate_sha256",
            )
        }
        for result in results
    }
    if set(candidate_descriptors) != set(candidate_ids):
        raise ValueError("candidate descriptors are incomplete")
    ordered_descriptors = [candidate_descriptors[key] for key in sorted(candidate_descriptors)]
    candidate_set_hash = hashlib.sha256(
        canonical_json(ordered_descriptors).encode("utf-8")
    ).hexdigest()

    by_candidate: dict[str, dict[str, dict[str, Any]]] = {}
    for result in results:
        by_candidate.setdefault(result["candidate_id"], {})[result["arm"]] = result
    shortlist = [
        candidate_id
        for candidate_id, sides in by_candidate.items()
        if all(
            sides.get(side, {}).get("aggregate", {}).get("nominal_rate", 0.0) >= 0.80
            for side in SIDES
        )
    ]

    top_by_arm: dict[str, list[dict[str, Any]]] = {}
    for side in SIDES:
        top_by_arm[side] = sorted(
            (result for result in results if result["arm"] == side),
            key=result_sort_key,
        )[:10]

    return {
        "schema_version": "m_minus_1.openarm_axis_rotation_prescreen_merged.v1",
        "status": "PASS",
        "run_mode": "calibration_single_arm_prescreen_then_gated_bimanual",
        "recipe_id": link7["recipe_id"],
        "base_candidate_id": link7["base_candidate_id"],
        "semantic_status": link7["semantic_status"],
        "kinematic_status": link7["kinematic_status"],
        "robot_status": link7["robot_status"],
        "candidate_budget": {
            "axis_rotation_count": link7["candidate_budget"]["axis_rotation_count"],
            "pose_direction_count": link7["candidate_budget"]["pose_direction_count"],
            "target_frame_count": 2,
            "candidate_count": 96,
            "per_target_frame_candidate_count": 48,
            "side_mapping": "direct",
            "side_mapping_role": "formal_default",
            "axis_rotation_set_sha256": link7["candidate_budget"]["axis_rotation_set_sha256"],
            "candidate_set_sha256": candidate_set_hash,
        },
        "sampling": link7["sampling"],
        "ik_budget": link7["ik_budget"],
        "target_frames": ["link7", "hand_tcp"],
        "transform_semantics": link7["transform_semantics"],
        "single_arm": {
            "gate_nominal_rate": 0.80,
            "collision_evaluation": "not_evaluated_single_arm_collision_pairs_removed",
            "results": sorted(results, key=lambda item: (item["candidate_id"], item["arm"])),
            "top_by_arm": top_by_arm,
        },
        "bimanual": {
            "authorized": bool(shortlist),
            "shortlist_count": len(shortlist),
            "shortlist_candidate_ids": sorted(shortlist),
            "results": [],
            "top": [],
            "status": (
                "EVALUATED_SHORTLIST"
                if shortlist
                else "NOT_AUTHORIZED_BELOW_SINGLE_ARM_80_PERCENT_GATE"
            ),
        },
        "source_reports": {
            "link7_sha256": sha256_file(link7_path),
            "hand_tcp_sha256": sha256_file(hand_tcp_path),
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--link7", type=Path, required=True)
    parser.add_argument("--hand-tcp", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.link7.resolve(), args.hand_tcp.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {args.output}")
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"status": report["status"], "candidate_count": 96}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
