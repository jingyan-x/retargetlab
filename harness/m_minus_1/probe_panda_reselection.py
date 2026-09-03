"""Run a target-reselection Panda spike through the disposable M-1 solver.

The existing OpenArm harness supplies the data sampling, candidate bookkeeping,
Pink loop, and report schema.  This adapter replaces only the robot-specific
parts: Panda frame names, finger mimic names, target seeds, collision geometry,
and the recipe-purpose check.  It keeps the OpenArm result and this spike
strictly separate; no OpenArm prescreen is reused.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pinocchio as pin
from pink import JointCouplingTask as PinkJointCouplingTask

import probe_openarm_reachability as base
from probe_panda_collisions import (
    ALLOWED_CONTACT_BASE_PAIRS,
    apply_srdf,
    filter_self_collision_geometry,
    parse_srdf,
    pair_names,
)


base.SCHEMA = "m_minus_1.panda_reselection.v1"
base.TCP_FRAMES = {
    "left": "panda_2_hand_tcp",
    "right": "panda_1_hand_tcp",
}


def panda_finger_geometry_names(side: str) -> tuple[str, ...]:
    return tuple(
        f"{side}_{finger}_{index}"
        for finger in ("leftfinger", "rightfinger")
        for index in range(4)
    )


base.EXPECTED_CONTACT_PAIRS = frozenset(
    base.canonical_pair(first, second)
    for side in ("panda_1", "panda_2")
    for first in panda_finger_geometry_names(side)[:4]
    for second in panda_finger_geometry_names(side)[4:]
)
base.REQUIRED_BODY_PAIRS = tuple(
    base.canonical_pair(f"panda_1_link0_sc_{first}", f"panda_2_link0_sc_{second}")
    for first in range(3)
    for second in range(3)
)


def panda_load_recipe(path: Path) -> dict[str, Any]:
    recipe = base.load_yaml(path)
    if recipe.get("stage") != "M-1":
        raise ValueError("Panda target spike requires an M-1 recipe")
    if recipe.get("purpose") != "panda_bimanual_target_reselection":
        raise ValueError("recipe purpose is not Panda target reselection")
    policy = recipe.get("collision_policy", {})
    base_pairs = policy.get("allowed_contact_base_pairs")
    if base_pairs != [
        ["panda_1_leftfinger", "panda_1_rightfinger"],
        ["panda_2_leftfinger", "panda_2_rightfinger"],
    ]:
        raise ValueError("Panda recipe must declare the two same-hand finger contact pairs")
    policy["allowed_contact_pairs"] = [
        list(pair) for pair in sorted(base.EXPECTED_CONTACT_PAIRS)
    ]
    recipe["collision_policy"] = policy
    return recipe


base.load_recipe = panda_load_recipe


def panda_set_finger_mimic(model: pin.Model, q: np.ndarray) -> None:
    for side in ("panda_1", "panda_2"):
        first = model.getJointId(f"{side}_finger_joint1")
        second = model.getJointId(f"{side}_finger_joint2")
        q[int(model.idx_qs[second])] = q[int(model.idx_qs[first])]


base.set_finger_mimic = panda_set_finger_mimic


def panda_clamp_configuration(model: pin.Model, q: np.ndarray) -> np.ndarray:
    result = np.asarray(q, dtype=float).copy()
    lower = model.lowerPositionLimit
    upper = model.upperPositionLimit
    bounded = np.logical_and(np.isfinite(lower), np.isfinite(upper))
    result[bounded] = np.clip(result[bounded], lower[bounded], upper[bounded])
    panda_set_finger_mimic(model, result)
    return result


base.clamp_configuration = panda_clamp_configuration


def panda_midpoint_configuration(model: pin.Model, reference: np.ndarray) -> np.ndarray:
    q = pin.neutral(model)
    for joint_id, joint in enumerate(model.joints):
        if joint_id == 0 or joint.nq != 1 or joint.nv != 1:
            continue
        index = int(model.idx_qs[joint_id])
        lower = float(model.lowerPositionLimit[index])
        upper = float(model.upperPositionLimit[index])
        if math.isfinite(lower) and math.isfinite(upper) and upper > lower:
            q[index] = 0.5 * (lower + upper)
    for side in ("panda_1", "panda_2"):
        first = model.getJointId(f"{side}_finger_joint1")
        q[int(model.idx_qs[first])] = reference[int(model.idx_qs[first])]
    return panda_clamp_configuration(model, q)


base.midpoint_configuration = panda_midpoint_configuration


PANDA_READY = np.array(
    (0.0, -0.7853981634, 0.0, -2.3561944902, 0.0, 1.5707963268, 0.7853981634),
    dtype=float,
)


def panda_target_reference_configuration(model: pin.Model) -> np.ndarray:
    q = pin.neutral(model)
    for side in ("panda_1", "panda_2"):
        for joint_index, value in enumerate(PANDA_READY, start=1):
            joint_id = model.getJointId(f"{side}_joint{joint_index}")
            q[int(model.idx_qs[joint_id])] = value
        first = model.getJointId(f"{side}_finger_joint1")
        q[int(model.idx_qs[first])] = 0.02
    return panda_clamp_configuration(model, q)


base.target_reference_configuration = panda_target_reference_configuration


def panda_random_target_configuration(
    model: pin.Model,
    rng: np.random.Generator,
) -> np.ndarray:
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
    return panda_clamp_configuration(model, q)


base.random_target_configuration = panda_random_target_configuration


def panda_target_initialization_configurations(
    model: pin.Model,
    seed: int,
    count: int,
) -> list[np.ndarray]:
    if count < 1:
        raise ValueError("target initialization seed count must be positive")
    configurations = [panda_target_reference_configuration(model)]
    rng = np.random.default_rng(seed)
    while len(configurations) < count:
        candidate = panda_random_target_configuration(model, rng)
        if not any(np.allclose(candidate, existing) for existing in configurations):
            configurations.append(candidate)
    return configurations


base.target_initialization_configurations = panda_target_initialization_configurations


def panda_joint_coupling_task(
    joint_names: list[str],
    coefficients: list[float],
    cost: float,
    configuration: Any,
) -> Any:
    mapped = []
    for name in joint_names:
        if name.startswith("openarm_left_"):
            mapped.append(name.replace("openarm_left_", "panda_2_", 1))
        elif name.startswith("openarm_right_"):
            mapped.append(name.replace("openarm_right_", "panda_1_", 1))
        else:
            mapped.append(name)
    return PinkJointCouplingTask(mapped, coefficients, cost, configuration)


base.JointCouplingTask = panda_joint_coupling_task


def panda_prepare_geometry(
    asset_dir: Path,
    srdf_path: Path | None,
) -> tuple[pin.Model, pin.GeometryModel, dict[str, Any]]:
    asset_dir = asset_dir.resolve()
    urdf_path = asset_dir / "urdf" / "panda_bimanual.urdf"
    if not urdf_path.is_file():
        raise ValueError("Panda target URDF is missing")
    if srdf_path is None or not srdf_path.is_file():
        raise ValueError("Panda target SRDF is missing")
    model = pin.buildModelFromUrdf(str(urdf_path))
    full_geometry = pin.buildGeomFromUrdf(
        model,
        str(urdf_path),
        pin.GeometryType.COLLISION,
        package_dirs=[str(asset_dir)],
    )
    full_geometry.addAllCollisionPairs()
    geometry, selected_names = filter_self_collision_geometry(full_geometry)
    disabled, srdf_failures = parse_srdf(srdf_path)
    geometry, removed_count, unmatched = apply_srdf(geometry, disabled)
    if srdf_failures or unmatched:
        raise ValueError("Panda SRDF collision policy is invalid")
    present_pairs = {pair_names(geometry, pair) for pair in geometry.collisionPairs}
    if any(pair not in present_pairs for pair in base.REQUIRED_BODY_PAIRS):
        raise ValueError("Panda SRDF/geometry omitted a required cross-arm base pair")
    return model, geometry, {
        "srdf_available": True,
        "srdf_disabled_pair_count": len(disabled),
        "srdf_removed_pair_count": removed_count,
        "full_collision_object_count": len(full_geometry.geometryObjects),
        "collision_object_count": len(selected_names),
        "collision_pair_count_after_srdf": len(geometry.collisionPairs),
        "required_cross_arm_base_pairs_not_disabled": True,
        "collision_geometry_strategy": "coarse_sc_links_plus_finger_primitives",
    }


base.prepare_geometry = panda_prepare_geometry


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
