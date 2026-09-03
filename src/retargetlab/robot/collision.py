"""Pinocchio collision geometry with explicit SRDF pair filtering."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from retargetlab.contracts import RobotProfile
from retargetlab.robot.assets import (
    resolve_asset_file,
    sha256_file,
    verify_profile_urdf,
)

try:
    import pinocchio as pin  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - exercised only in a missing-optional-dependency env
    pin = None  # type: ignore[assignment]


FloatArray = NDArray[np.float64]
_TRAILING_COMPONENT = re.compile(r"^(.*)_\d+$")
_PANDA_COARSE_PATTERN = re.compile(
    r"^panda_[12]_(?:link[0-7]|hand)_sc_\d+$|"
    r"^panda_[12]_(?:leftfinger|rightfinger)_\d+$"
)


def canonical_pair(first: str, second: str) -> tuple[str, str]:
    return (first, second) if first <= second else (second, first)


def geometry_base(name: str) -> str:
    """Remove Pinocchio's trailing geometry component index."""

    match = _TRAILING_COMPONENT.match(name)
    return match.group(1) if match else name


def parse_srdf_disabled_pairs(path: Path) -> set[tuple[str, str]]:
    """Read only disable-collision entries from an SRDF file."""

    import xml.etree.ElementTree as ET

    root = ET.parse(path).getroot()
    if root.tag.rsplit("}", 1)[-1] != "robot":
        raise ValueError("SRDF root is not robot")
    pairs: set[tuple[str, str]] = set()
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "disable_collisions":
            continue
        first = element.get("link1")
        second = element.get("link2")
        if not first or not second:
            raise ValueError("SRDF disable_collisions entry is incomplete")
        pairs.add(canonical_pair(first, second))
    return pairs


def _geometry_pair_names(geometry: Any, pair: Any) -> tuple[str, str]:
    return canonical_pair(
        geometry.geometryObjects[pair.first].name,
        geometry.geometryObjects[pair.second].name,
    )


def _base_geometry_pair_names(geometry: Any, pair: Any) -> tuple[str, str]:
    names = _geometry_pair_names(geometry, pair)
    return canonical_pair(geometry_base(names[0]), geometry_base(names[1]))


def _filter_geometry_for_strategy(geometry: Any, strategy: str) -> Any:
    """Apply a named, manifest-controlled collision geometry reduction."""

    if strategy != "coarse_sc_links_plus_finger_primitives":
        return geometry
    selected_names = [
        object_.name
        for object_ in geometry.geometryObjects
        if _PANDA_COARSE_PATTERN.match(object_.name)
    ]
    if not selected_names:
        raise ValueError("Panda coarse collision strategy selected no geometry objects")
    filtered = geometry.copy()
    selected = set(selected_names)
    names_to_remove = [
        object_.name for object_ in geometry.geometryObjects if object_.name not in selected
    ]
    for name in names_to_remove:
        filtered.removeGeometryObject(name)
    filtered.removeAllCollisionPairs()
    filtered.addAllCollisionPairs()

    first_objects = [
        object_.name
        for object_ in filtered.geometryObjects
        if geometry_base(object_.name) == "panda_1_link0_sc"
    ]
    second_objects = [
        object_.name
        for object_ in filtered.geometryObjects
        if geometry_base(object_.name) == "panda_2_link0_sc"
    ]
    existing = {_geometry_pair_names(filtered, pair) for pair in filtered.collisionPairs}
    for first in first_objects:
        for second in second_objects:
            names = canonical_pair(first, second)
            if names in existing:
                continue
            filtered.addCollisionPair(
                pin.CollisionPair(filtered.getGeometryId(first), filtered.getGeometryId(second))
            )
            existing.add(names)
    return filtered


def _apply_srdf(geometry: Any, disabled_pairs: set[tuple[str, str]]) -> tuple[Any, int]:
    kept_pairs = [
        (int(pair.first), int(pair.second))
        for pair in geometry.collisionPairs
        if _base_geometry_pair_names(geometry, pair) not in disabled_pairs
    ]
    removed_count = len(geometry.collisionPairs) - len(kept_pairs)
    filtered = geometry.copy()
    filtered.removeAllCollisionPairs()
    for first, second in kept_pairs:
        filtered.addCollisionPair(pin.CollisionPair(first, second))
    return filtered, removed_count


@dataclass(frozen=True)
class CollisionReport:
    """Collision result after applying allowed contact semantics."""

    raw_pairs: tuple[tuple[str, str], ...]
    active_pairs: tuple[tuple[str, str], ...]
    allowed_pairs: tuple[tuple[str, str], ...]

    @property
    def collision_free(self) -> bool:
        return not self.active_pairs


class PinocchioCollisionModel:
    """A loaded Pinocchio collision model and its immutable pair policy."""

    def __init__(self, profile: RobotProfile) -> None:
        if pin is None:
            raise RuntimeError("Pinocchio is required for collision geometry")
        urdf_path = resolve_asset_file(Path(profile.asset_dir), profile.urdf_path)
        verify_profile_urdf(Path(profile.asset_dir), urdf_path, profile.urdf_sha256)
        self.profile = profile
        self.model = pin.buildModelFromUrdf(str(urdf_path))
        full_geometry = pin.buildGeomFromUrdf(
            self.model,
            str(urdf_path),
            pin.GeometryType.COLLISION,
            package_dirs=[profile.asset_dir],
        )
        full_geometry.addAllCollisionPairs()
        self.full_geometry = full_geometry
        strategy = profile.collision.strategy if profile.collision else "srdf"
        policy_geometry = _filter_geometry_for_strategy(full_geometry, strategy)
        self.srdf_disabled_pairs: set[tuple[str, str]] = set()
        if profile.collision is not None and profile.collision.srdf_path:
            srdf_path = resolve_asset_file(Path(profile.asset_dir), profile.collision.srdf_path)
            if profile.collision.srdf_sha256 is not None:
                actual_hash = sha256_file(srdf_path)
                if actual_hash.lower() != profile.collision.srdf_sha256.lower():
                    raise ValueError(
                        "SRDF hash mismatch: "
                        f"expected {profile.collision.srdf_sha256.lower()}, "
                        f"got {actual_hash.lower()}"
                    )
            self.srdf_disabled_pairs = parse_srdf_disabled_pairs(srdf_path)
        self.geometry, self.srdf_removed_pair_count = _apply_srdf(
            policy_geometry, self.srdf_disabled_pairs
        )
        allowed = profile.collision.allowed_contact_pairs if profile.collision else ()
        self.allowed_contact_pairs = {canonical_pair(first, second) for first, second in allowed}
        self.data = self.model.createData()

    def _validate_q(self, q: NDArray[np.floating] | list[float] | tuple[float, ...]) -> FloatArray:
        values = np.asarray(q, dtype=float)
        if values.shape != (self.model.nq,):
            raise ValueError(f"q must have shape ({self.model.nq},)")
        if not np.all(np.isfinite(values)):
            raise ValueError("q must contain only finite values")
        return values

    def report(
        self,
        q: NDArray[np.floating] | list[float] | tuple[float, ...],
    ) -> CollisionReport:
        """Compute collisions without modifying the model or geometry policy."""

        values = self._validate_q(q)
        geometry_data = pin.GeometryData(self.geometry)
        pin.computeCollisions(
            self.model,
            self.data,
            self.geometry,
            geometry_data,
            values,
            False,
        )
        raw: list[tuple[str, str]] = []
        active: list[tuple[str, str]] = []
        allowed: list[tuple[str, str]] = []
        for index, pair in enumerate(self.geometry.collisionPairs):
            if not geometry_data.collisionResults[index].isCollision():
                continue
            names = _geometry_pair_names(self.geometry, pair)
            raw.append(names)
            base_pair = canonical_pair(geometry_base(names[0]), geometry_base(names[1]))
            if base_pair in self.allowed_contact_pairs:
                allowed.append(names)
            else:
                active.append(names)
        return CollisionReport(tuple(raw), tuple(active), tuple(allowed))

    def barrier_geometry(self, pair_budget: int) -> Any:
        """Return a deterministic barrier subset with required pairs retained."""

        if pair_budget <= 0:
            raise ValueError("collision barrier pair budget must be positive")
        all_pairs = list(self.geometry.collisionPairs)
        if pair_budget >= len(all_pairs):
            return self.geometry.copy()
        required_bases = {
            canonical_pair(first, second)
            for first, second in (
                self.profile.collision.required_barrier_pairs
                if self.profile.collision is not None
                else ()
            )
        }
        required: list[Any] = []
        other: list[Any] = []
        for pair in all_pairs:
            if _base_geometry_pair_names(self.geometry, pair) in required_bases:
                required.append(pair)
            else:
                other.append(pair)
        if len(required) > pair_budget:
            raise ValueError("collision barrier pair budget omits required barrier pairs")
        selected = required + other[: pair_budget - len(required)]
        barrier = self.geometry.copy()
        barrier.removeAllCollisionPairs()
        for pair in selected:
            barrier.addCollisionPair(pin.CollisionPair(int(pair.first), int(pair.second)))
        return barrier

    def summary(self) -> dict[str, int]:
        """Return stable counts for reports and diagnostics."""

        return {
            "model_nq": int(self.model.nq),
            "model_nv": int(self.model.nv),
            "full_collision_object_count": len(self.full_geometry.geometryObjects),
            "collision_object_count": len(self.geometry.geometryObjects),
            "full_collision_pair_count": len(self.full_geometry.collisionPairs),
            "collision_pair_count_after_srdf": len(self.geometry.collisionPairs),
            "srdf_disabled_pair_count": len(self.srdf_disabled_pairs),
            "srdf_removed_pair_count": int(self.srdf_removed_pair_count),
        }
