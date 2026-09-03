"""Check the Panda target-reselection collision geometry and SRDF policy."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pinocchio as pin


SCHEMA = "m_minus_1.panda_collision_probe.v1"
URDF_RELATIVE = Path("urdf/panda_bimanual.urdf")
SRDF_RELATIVE = Path("srdf/panda_bimanual.srdf")
GEOMETRY_PATTERN = re.compile(
    r"^panda_[12]_(?:link[0-7]|hand)_sc_\d+$|"
    r"^panda_[12]_(?:leftfinger|rightfinger)_\d+$"
)
ALLOWED_CONTACT_BASE_PAIRS = {
    tuple(sorted(("panda_1_leftfinger", "panda_1_rightfinger"))),
    tuple(sorted(("panda_2_leftfinger", "panda_2_rightfinger"))),
}
REQUIRED_CROSS_ARM_BASES = {
    "panda_1_link0_sc",
    "panda_2_link0_sc",
}
PANDA_SAFE_ARM_SEED = (0.0, -0.7853981634, 0.0, -2.3561944902, 0.0, 1.5707963268, 0.7853981634)


def canonical_pair(first: str, second: str) -> tuple[str, str]:
    return tuple(sorted((first, second)))


def geometry_base(name: str) -> str:
    match = re.match(r"^(.*)_\d+$", name)
    if match is None:
        raise ValueError(f"unexpected geometry object name: {name}")
    return match.group(1)


def pair_names(
    geometry: pin.GeometryModel,
    pair: pin.CollisionPair,
) -> tuple[str, str]:
    return canonical_pair(
        geometry.geometryObjects[pair.first].name,
        geometry.geometryObjects[pair.second].name,
    )


def base_pair_names(
    geometry: pin.GeometryModel,
    pair: pin.CollisionPair,
) -> tuple[str, str]:
    names = pair_names(geometry, pair)
    return canonical_pair(geometry_base(names[0]), geometry_base(names[1]))


def parse_srdf(path: Path) -> tuple[set[tuple[str, str]], list[str]]:
    root = ET.parse(path).getroot()
    if root.tag.rsplit("}", 1)[-1] != "robot":
        raise ValueError("SRDF root is not robot")
    disabled: set[tuple[str, str]] = set()
    failures: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "disable_collisions":
            continue
        first = element.get("link1")
        second = element.get("link2")
        if not first or not second:
            failures.append("SRDF contains an incomplete disable_collisions entry")
            continue
        disabled.add(canonical_pair(first, second))
    return disabled, failures


def filter_self_collision_geometry(
    geometry: pin.GeometryModel,
) -> tuple[pin.GeometryModel, list[str]]:
    selected_names = [
        object_.name
        for object_ in geometry.geometryObjects
        if GEOMETRY_PATTERN.match(object_.name)
    ]
    if not selected_names:
        raise ValueError("no Panda coarse self-collision or finger geometry found")
    filtered = geometry.copy()
    names_to_remove = [
        object_.name
        for object_ in filtered.geometryObjects
        if object_.name not in selected_names
    ]
    for name in names_to_remove:
        filtered.removeGeometryObject(name)
    filtered.removeAllCollisionPairs()
    filtered.addAllCollisionPairs()
    selected_by_base = {}
    for object_ in filtered.geometryObjects:
        selected_by_base.setdefault(geometry_base(object_.name), []).append(object_.name)
    first_objects = selected_by_base.get("panda_1_link0_sc", [])
    second_objects = selected_by_base.get("panda_2_link0_sc", [])
    existing = {
        pair_names(filtered, pair)
        for pair in filtered.collisionPairs
    }
    for first in first_objects:
        for second in second_objects:
            pair = canonical_pair(first, second)
            if pair not in existing:
                first_index = filtered.getGeometryId(first)
                second_index = filtered.getGeometryId(second)
                filtered.addCollisionPair(pin.CollisionPair(first_index, second_index))
                existing.add(pair)
    return filtered, selected_names


def apply_srdf(
    geometry: pin.GeometryModel,
    disabled: set[tuple[str, str]],
) -> tuple[pin.GeometryModel, int, list[str]]:
    filtered = geometry.copy()
    unmatched: list[str] = []
    kept_pairs: list[tuple[int, int]] = []
    geometry_bases = {geometry_base(object_.name) for object_ in filtered.geometryObjects}
    for pair in disabled:
        if pair[0] not in geometry_bases or pair[1] not in geometry_bases:
            unmatched.append(f"SRDF pair does not match filtered geometry: {pair[0]} / {pair[1]}")
    for collision_pair in filtered.collisionPairs:
        if base_pair_names(filtered, collision_pair) not in disabled:
            kept_pairs.append((collision_pair.first, collision_pair.second))
    removed_count = len(filtered.collisionPairs) - len(kept_pairs)
    filtered.removeAllCollisionPairs()
    for first, second in kept_pairs:
        filtered.addCollisionPair(pin.CollisionPair(first, second))
    return filtered, removed_count, unmatched


def set_fingers(model: pin.Model, endpoint: float) -> Any:
    q = pin.neutral(model)
    for side in ("panda_1", "panda_2"):
        for joint_index, value in enumerate(PANDA_SAFE_ARM_SEED):
            joint_id = model.getJointId(f"{side}_joint{joint_index + 1}")
            q[int(model.idx_qs[joint_id])] = value
        first = model.getJointId(f"{side}_finger_joint1")
        second = model.getJointId(f"{side}_finger_joint2")
        q[int(model.idx_qs[first])] = endpoint
        q[int(model.idx_qs[second])] = endpoint
    return q


def evaluate(
    model: pin.Model,
    geometry: pin.GeometryModel,
    q: Any,
    disabled: set[tuple[str, str]],
) -> dict[str, Any]:
    data = model.createData()
    geometry_data = pin.GeometryData(geometry)
    pin.computeCollisions(model, data, geometry, geometry_data, q, False)
    raw = [
        pair_names(geometry, pair)
        for index, pair in enumerate(geometry.collisionPairs)
        if geometry_data.collisionResults[index].isCollision()
    ]
    active = []
    allowed = []
    for name_pair in raw:
        base_pair = canonical_pair(geometry_base(name_pair[0]), geometry_base(name_pair[1]))
        if base_pair in ALLOWED_CONTACT_BASE_PAIRS:
            allowed.append(name_pair)
        else:
            active.append(name_pair)
    cross_arm = [
        name_pair
        for name_pair in active
        if set(geometry_base(name) for name in name_pair) == REQUIRED_CROSS_ARM_BASES
    ]
    return {
        "raw_collision_count": len(raw),
        "allowed_finger_contact_count": len(allowed),
        "active_collision_count": len(active),
        "active_collision_pairs": [list(pair) for pair in active],
        "cross_arm_base_collision_count": len(cross_arm),
    }


def build_report(asset_dir: Path) -> dict[str, Any]:
    asset_dir = asset_dir.resolve()
    urdf_path = asset_dir / URDF_RELATIVE
    srdf_path = asset_dir / SRDF_RELATIVE
    if not urdf_path.is_file() or not srdf_path.is_file():
        raise ValueError("Panda URDF or SRDF is missing")
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
    checks: dict[str, bool] = {
        "srdf_valid": not srdf_failures,
        "srdf_pairs_match_filtered_geometry": not unmatched,
        "coarse_geometry_selected": bool(selected_names),
        "collision_pairs_after_srdf": bool(geometry.collisionPairs),
    }
    representative_cross_arm = canonical_pair("panda_1_link0_sc_0", "panda_2_link0_sc_0")
    configured_pairs = {pair_names(geometry, pair) for pair in geometry.collisionPairs}
    checks["cross_arm_base_pair_preserved"] = representative_cross_arm in configured_pairs
    samples = {
        "ready_seed_fingers_closed": evaluate(model, geometry, set_fingers(model, 0.0), disabled),
        "ready_seed_fingers_open": evaluate(model, geometry, set_fingers(model, 0.04), disabled),
    }
    checks["ready_seed_samples_clear"] = all(
        sample["active_collision_count"] == 0 for sample in samples.values()
    )
    checks["no_cross_arm_ready_seed_collision"] = all(
        sample["cross_arm_base_collision_count"] == 0 for sample in samples.values()
    )
    failures = list(srdf_failures) + list(unmatched)
    if not checks["cross_arm_base_pair_preserved"]:
        failures.append("required cross-arm base collision pair was disabled or removed")
    if not checks["ready_seed_samples_clear"]:
        failures.append("Panda ready-seed sample has an active collision")
    if not checks["no_cross_arm_ready_seed_collision"]:
        failures.append("Panda ready-seed sample has a cross-arm base collision")
    return {
        "schema_version": SCHEMA,
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failures": failures,
        "metrics": {
            "model_nq": model.nq,
            "model_nv": model.nv,
            "full_collision_object_count": len(full_geometry.geometryObjects),
            "selected_collision_object_count": len(selected_names),
            "full_collision_pair_count": len(full_geometry.collisionPairs),
            "collision_pair_count_after_srdf": len(geometry.collisionPairs),
            "srdf_disabled_base_pair_count": len(disabled),
            "srdf_removed_pair_count": removed_count,
            "samples": samples,
            "allowed_contact_policy": [list(pair) for pair in sorted(ALLOWED_CONTACT_BASE_PAIRS)],
        },
        "absolute_paths_emitted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build_report(args.asset_dir)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        report = {
            "schema_version": SCHEMA,
            "status": "ERROR",
            "checks": {},
            "failures": [f"collision probe failed ({type(exc).__name__})"],
            "absolute_paths_emitted": False,
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
