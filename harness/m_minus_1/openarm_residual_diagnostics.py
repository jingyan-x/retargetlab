"""Aggregate-only attribution of fixed-candidate bimanual IK failures."""

from collections import Counter

import numpy as np


class ResidualAudit:
    """Separate solve stages and arm-joint limits without retaining poses or q."""

    def __init__(self, joint_specs, near_limit_fraction=0.01):
        self.joint_specs = joint_specs
        self.near_limit_fraction = near_limit_fraction
        self.frames = 0
        self.stage = Counter()
        self.failures = Counter()
        self.near_limits = Counter()
        self.failed_min_margins = []

    def add(self, result, position_tolerance, orientation_tolerance):
        self.frames += 1
        final = result["metrics"]
        bad_sides = []
        for side in ("left", "right"):
            bad_position = final[f"{side}_position_error_m"] > position_tolerance
            bad_orientation = final[f"{side}_orientation_error_rad"] > orientation_tolerance
            if bad_position:
                self.failures[f"{side}_position"] += 1
            if bad_orientation:
                self.failures[f"{side}_orientation"] += 1
            if bad_position or bad_orientation:
                bad_sides.append(side)
        category = "_and_".join(bad_sides) if bad_sides else "neither"
        self.failures[f"residual_sides_{category}"] += 1
        position_stage = result.get("position_stage")
        if position_stage is not None:
            stage_metrics = position_stage["metrics"]
            reached = all(
                stage_metrics[f"{side}_position_error_m"] <= position_tolerance
                for side in ("left", "right")
            )
            self.stage[
                "position_stage_both_reached" if reached else "position_stage_not_both_reached"
            ] += 1
            if reached and bad_sides:
                self.stage["position_reached_then_full_pose_failed"] += 1
        if final["penetration"]:
            self.failures["collision"] += 1
        if final["joint_limit_violation"]:
            self.failures["hard_limit_violation"] += 1
        if not bad_sides:
            return
        margins = []
        for name, (index, lower, upper) in self.joint_specs.items():
            # Only arm joints enter this view: a closed gripper is normally
            # at its lower limit and would obscure the attribution.
            q = result["q"][index]
            margin = min(q - lower, upper - q) / (upper - lower)
            margins.append(float(margin))
            if margin <= self.near_limit_fraction:
                self.near_limits[name] += 1
        self.failed_min_margins.append(min(margins))

    def report(self):
        margins = np.asarray(self.failed_min_margins, dtype=float)
        return {
            "frame_count": self.frames,
            "position_stage": dict(sorted(self.stage.items())),
            "final_failure_counts": dict(sorted(self.failures.items())),
            "failed_frames_near_arm_limit_counts": dict(sorted(self.near_limits.items())),
            "near_limit_threshold_fraction": self.near_limit_fraction,
            "failed_frames_min_arm_margin": (
                {
                    "min": float(margins.min()),
                    "median": float(np.median(margins)),
                    "max": float(margins.max()),
                }
                if len(margins)
                else None
            ),
            "collision_and_limit_counts_overlap_residual_counts": True,
            "raw_pose_or_joint_values_emitted": False,
        }
