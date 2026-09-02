"""Probe OpenArm self-collision pairs before the M-1 SRDF policy is available.

The probe is deliberately independent of src/. It builds every pair in
Pinocchio's GeometryModel, evaluates conservative gripper endpoints, and
checks the body-to-arm-base pairs that the planned SRDF policy must not hide.
It is diagnostic only: without an explicit SRDF it returns a blocked status.
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pinocchio as pin

PROBE_SCHEMA = "m_minus_1.openarm_collision_probe.v1"
DEFAULT_URDF = Path("urdf/openarm_bimanual_v10.urdf")
FINGER_ENDPOINTS = (0.0, 0.044)
REQUIRED_BODY_PAIRS = (
    ("openarm_body_link0_0", "openarm_left_link0_0"),
    ("openarm_body_link0_0", "openarm_right_link0_0"),
)


def canonical_pair(first: str, second: str) -> tuple[str, str]:
    return tuple(sorted((first, second)))


def pair_name(geometry_model: pin.GeometryModel, pair: Any) -> tuple[str, str]:
    return canonical_pair(
        geometry_model.geometryObjects[pair.first].name,
        geometry_model.geometryObjects[pair.second].name,
    )


def set_finger_endpoint(model: pin.Model, endpoint: float) -> Any:
    q = pin.neutral(model)
    for side in ("left", "right"):
        for index in (1, 2):
            joint_id = model.getJointId(f"openarm_{side}_finger_joint{index}")
            q[int(model.idx_qs[joint_id])] = endpoint
    return q


def add_required_body_pairs(geometry_model: pin.GeometryModel) -> None:
    geometry_indexes = {
        geometry_object.name: index
        for index, geometry_object in enumerate(geometry_model.geometryObjects)
    }
    existing_pairs = {
        pair_name(geometry_model, pair)
        for pair in geometry_model.collisionPairs
    }
    for first, second in REQUIRED_BODY_PAIRS:
        pair = canonical_pair(first, second)
        if pair in existing_pairs:
            continue
        try:
            first_index = geometry_indexes[first]
            second_index = geometry_indexes[second]
        except KeyError as exc:
            raise ValueError("required body-to-link0 collision object is missing") from exc
        geometry_model.addCollisionPair(pin.CollisionPair(first_index, second_index))
        existing_pairs.add(pair)


def load_disabled_pairs(
    srdf_path: Path | None,
    geometry_model: pin.GeometryModel,
) -> tuple[set[tuple[str, str]], list[str], bool]:
    if srdf_path is None or not srdf_path.is_file():
        return set(), [], False

    try:
        root = ET.parse(srdf_path).getroot()
    except (OSError, ET.ParseError):
        return set(), ["srdf: invalid XML"], True

    geometry_names = {
        geometry_object.name for geometry_object in geometry_model.geometryObjects
    }
    disabled: set[tuple[str, str]] = set()
    unmatched: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "disable_collisions":
            continue
        first = element.get("link1")
        second = element.get("link2")
        if not first or not second:
            unmatched.append("srdf: disable_collisions entry is incomplete")
            continue
        first_geometry = first if first in geometry_names else f"{first}_0"
        second_geometry = second if second in geometry_names else f"{second}_0"
        pair = canonical_pair(first_geometry, second_geometry)
        if first_geometry not in geometry_names or second_geometry not in geometry_names:
            unmatched.append("srdf: a disabled pair does not match a collision object")
            continue
        disabled.add(pair)
    return disabled, unmatched, True


def discover_manifest_srdf(
    asset_dir: Path,
    explicit_srdf: Path | None,
) -> Path | None:
    if explicit_srdf is not None:
        return explicit_srdf

    manifest_path = asset_dir / "asset_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    relative_path = manifest.get("srdf_path")
    if not isinstance(relative_path, str) or not relative_path:
        return None
    candidate = (asset_dir / Path(relative_path)).resolve()
    try:
        candidate.relative_to(asset_dir.resolve())
    except ValueError:
        return None
    return candidate


def evaluate_sample(
    model: pin.Model,
    geometry_model: pin.GeometryModel,
    geometry_data: pin.GeometryData,
    q: Any,
    disabled_pairs: set[tuple[str, str]],
) -> dict[str, Any]:
    data = model.createData()
    pin.computeCollisions(model, data, geometry_model, geometry_data, q, False)
    raw_pairs = [
        pair_name(geometry_model, pair)
        for index, pair in enumerate(geometry_model.collisionPairs)
        if geometry_data.collisionResults[index].isCollision()
    ]
    active_pairs = [pair for pair in raw_pairs if pair not in disabled_pairs]
    required_pairs = set(REQUIRED_BODY_PAIRS)
    body_pairs = [pair for pair in raw_pairs if pair in required_pairs]
    return {
        "raw_collision_count": len(raw_pairs),
        "raw_collision_pairs": [list(pair) for pair in raw_pairs],
        "active_collision_count": len(active_pairs),
        "active_collision_pairs": [list(pair) for pair in active_pairs],
        "body_link0_collision_pairs": [list(pair) for pair in body_pairs],
    }


def build_report(asset_dir: Path, srdf_path: Path | None) -> dict[str, Any]:
    asset_dir = asset_dir.resolve()
    urdf_path = asset_dir / DEFAULT_URDF
    checks: dict[str, bool] = {}
    failures: list[str] = []
    metrics: dict[str, Any] = {}

    if not urdf_path.is_file():
        checks["urdf_present"] = False
        failures.append("urdf: generated URDF is missing")
        return {
            "schema_version": PROBE_SCHEMA,
            "status": "FAIL",
            "checks": checks,
            "failures": failures,
            "metrics": metrics,
            "absolute_paths_emitted": False,
        }
    checks["urdf_present"] = True

    try:
        model = pin.buildModelFromUrdf(str(urdf_path))
        geometry_model = pin.buildGeomFromUrdf(
            model,
            str(urdf_path),
            pin.GeometryType.COLLISION,
            package_dirs=[str(asset_dir)],
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        checks["geometry_model_loaded"] = False
        failures.append(f"pinocchio: geometry load failed ({type(exc).__name__})")
        return {
            "schema_version": PROBE_SCHEMA,
            "status": "FAIL",
            "checks": checks,
            "failures": failures,
            "metrics": metrics,
            "absolute_paths_emitted": False,
        }
    checks["geometry_model_loaded"] = True

    geometry_model.addAllCollisionPairs()
    add_required_body_pairs(geometry_model)
    metrics["collision_object_count"] = len(geometry_model.geometryObjects)
    metrics["collision_pair_count"] = len(geometry_model.collisionPairs)
    checks["collision_pairs_generated"] = len(geometry_model.collisionPairs) > 0
    if not checks["collision_pairs_generated"]:
        failures.append("collision: no collision pairs were generated")

    pair_names = {
        pair_name(geometry_model, pair) for pair in geometry_model.collisionPairs
    }
    missing_body_pairs = [
        pair for pair in REQUIRED_BODY_PAIRS if canonical_pair(*pair) not in pair_names
    ]
    checks["body_link0_pairs_present"] = not missing_body_pairs
    if missing_body_pairs:
        failures.append("collision: body-to-link0 pair is missing")

    disabled_pairs, srdf_failures, srdf_available = load_disabled_pairs(
        srdf_path, geometry_model
    )
    checks["srdf_available"] = srdf_available
    checks["srdf_disabled_pairs_valid"] = not srdf_failures
    failures.extend(srdf_failures)
    if srdf_available and any(
        canonical_pair(*pair) in disabled_pairs for pair in REQUIRED_BODY_PAIRS
    ):
        checks["body_link0_not_disabled"] = False
        failures.append("collision: SRDF disables a required body-to-link0 pair")
    else:
        checks["body_link0_not_disabled"] = True
    metrics["srdf_disabled_pair_count"] = len(disabled_pairs)

    geometry_data = pin.GeometryData(geometry_model)
    samples = {
        "neutral_fingers_closed": set_finger_endpoint(model, FINGER_ENDPOINTS[0]),
        "neutral_fingers_open": set_finger_endpoint(model, FINGER_ENDPOINTS[1]),
    }
    sample_reports = {
        name: evaluate_sample(
            model, geometry_model, geometry_data, q, disabled_pairs
        )
        for name, q in samples.items()
    }
    metrics["samples"] = sample_reports
    checks["body_link0_clear_at_samples"] = all(
        not report["body_link0_collision_pairs"]
        for report in sample_reports.values()
    )
    if not checks["body_link0_clear_at_samples"]:
        failures.append("collision: body-to-link0 collision at a probe sample")

    checks["srdf_policy_applied"] = srdf_available and not srdf_failures
    if not srdf_available:
        status = "BLOCKED_MISSING_SRDF"
    elif failures:
        status = "FAIL"
    else:
        status = "PASS"
    return {
        "schema_version": PROBE_SCHEMA,
        "status": status,
        "checks": checks,
        "failures": failures,
        "metrics": metrics,
        "absolute_paths_emitted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--srdf", type=Path)
    args = parser.parse_args()
    try:
        srdf_path = discover_manifest_srdf(args.asset_dir.resolve(), args.srdf)
        report = build_report(args.asset_dir, srdf_path)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        report = {
            "schema_version": PROBE_SCHEMA,
            "status": "ERROR",
            "checks": {},
            "failures": [f"collision probe failed ({type(exc).__name__})"],
            "metrics": {},
            "absolute_paths_emitted": False,
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
