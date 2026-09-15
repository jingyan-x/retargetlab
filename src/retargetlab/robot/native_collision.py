"""Explicit MuJoCo collision pairs and Mink 1.3.0 displacement-unit adaptation."""

from __future__ import annotations

from importlib.metadata import version
from itertools import combinations

import numpy as np


class NativeCollisionGeometry:
    """Keep the profile's pair policy, including non-excluded parent/child pairs.

    Fixed welds are omitted as in the reference Pinocchio geometry model.
    Source-Joint-derived training exceptions never enter this IK geometry.
    """

    def __init__(self, engine, profile):
        self.engine = engine
        self.model = engine.model
        if profile.collision and profile.collision.strategy != "srdf":
            raise ValueError("native collision supports the registered SRDF geometry strategy")
        entries = [g for g in engine.metadata["geometry_mapping"] if g["kind"] == "collision"]
        links = {self.model.geom(g["name"]).id: g["link"] for g in entries}
        source_names = {
            self.model.geom(g["name"]).id: (
                g["source_geometry_name"]
                if "source_geometry_name" in g
                else f"{g['link']}_{g['name'].rsplit('__', 1)[1]}"
            )
            for g in entries
        }
        disabled = {tuple(sorted(p)) for p in engine.metadata["srdf_exclusions"]}
        allowed = {
            tuple(sorted(p))
            for p in (profile.collision.allowed_contact_pairs if profile.collision else ())
        }
        pairs = []
        for a, b in combinations(sorted(links), 2):
            link_pair = tuple(sorted((links[a], links[b])))
            weld_a = self.model.body_weldid[self.model.geom_bodyid[a]]
            weld_b = self.model.body_weldid[self.model.geom_bodyid[b]]
            if weld_a == weld_b or link_pair in disabled or link_pair in allowed:
                continue
            if not (
                self.model.geom_contype[a] & self.model.geom_conaffinity[b]
                or self.model.geom_contype[b] & self.model.geom_conaffinity[a]
            ):
                raise ValueError("collision geometry contact masks conflict with the profile")
            pairs.append((a, b))
        self.pairs = tuple(pairs)
        self.source_pairs = tuple(
            tuple(sorted((source_names[a], source_names[b]))) for a, b in pairs
        )
        ids = np.asarray(pairs, dtype=int).reshape(-1, 2)
        self.first, self.second = ids[:, 0], ids[:, 1]
        self.radii = self.model.geom_rbound[self.first] + self.model.geom_rbound[self.second]
        self.geometry_status = engine.metadata.get("collision_status", "UNVALIDATED")

    def distances(self, data, cutoff):
        """Signed distances, clipped above cutoff; positive means separated."""
        import mujoco

        if not np.isfinite(cutoff) or cutoff <= 0:
            raise ValueError("collision distance cutoff must be finite and positive")
        result = np.full(len(self.pairs), cutoff)
        delta = data.geom_xpos[self.first] - data.geom_xpos[self.second]
        # All production assets are bounded mesh geoms. Unbounded primitives stay active.
        bounded = (self.model.geom_rbound[self.first] > 0) & (
            self.model.geom_rbound[self.second] > 0
        )
        nearby = ~bounded | (np.einsum("ij,ij->i", delta, delta) <= (self.radii + cutoff) ** 2)
        for i in np.flatnonzero(nearby):
            a, b = self.pairs[i]
            result[i] = mujoco.mj_geomDistance(self.model, data, a, b, cutoff, None)
        return result

    def minimum(self, data, cutoff):
        return float(self.distances(data, cutoff).min()) if self.pairs else None

    def summary(self):
        return {
            "geom_pairs": len(self.pairs),
            "source_geometry_pairs": len(set(self.source_pairs)),
            "geometry_status": self.geometry_status,
            "filter_policy": (
                "all different-weld collision geoms minus SRDF and profile allowances; "
                "no implicit parent filter"
            ),
            "training_source_contact_exceptions": "postcheck only; never supplied to IK",
        }


def make_collision_limit(geometry, minimum_distance, detection_distance, *, recovery_margin=0.0):
    """Use the pinned native Mink constraint with complete pairs and Δq units.

    Mink 1.3.0's limit returns a velocity-form upper bound, while build_ik
    optimizes displacement. Multiply h by dt; a two-sphere regression proves
    the need for this conversion. The internal pair-construction override is
    version-pinned and checked against the complete reference pair set.
    """
    import mink

    if version("mink") != "1.3.0":
        raise ValueError("collision-unit adapter is validated only for Mink 1.3.0")
    if not 0 < minimum_distance < detection_distance:
        raise ValueError("collision distances must satisfy 0 < minimum < detection")

    if recovery_margin < 0 or not np.isfinite(recovery_margin):
        raise ValueError("recovery margin must be finite and nonnegative")
    if minimum_distance + recovery_margin >= detection_distance:
        raise ValueError("recovery margin must remain inside collision detection distance")

    class ExplicitPairDisplacementLimit(mink.CollisionAvoidanceLimit):
        def _construct_geom_id_pairs(self, geom_pairs):
            return list(geometry.pairs)

        def compute_qp_inequalities(self, configuration, dt):
            constraint = super().compute_qp_inequalities(configuration, dt)
            finite = np.isfinite(constraint.h)
            if not finite.any():
                return mink.Constraint()
            matrix, bound = constraint.G[finite], constraint.h[finite] * dt
            if recovery_margin:
                distances = geometry.distances(configuration.data, detection_distance)[finite]
                # A small positive target gap supplies an outward recovery direction
                # when a tangent step stalls at the requested clearance boundary.
                # Existing penetration keeps the original non-deepening constraint.
                bound = np.where(
                    distances >= 0,
                    0.85 * (distances - minimum_distance - recovery_margin),
                    0.0,
                )
                scale = np.linalg.norm(matrix, axis=1)
                scale = np.where(scale > 1e-12, scale, 1.0)
                matrix, bound = matrix / scale[:, None], bound / scale
            return mink.Constraint(G=matrix, h=bound)

    limit = ExplicitPairDisplacementLimit(
        geometry.model,
        [],
        gain=0.85,
        minimum_distance_from_collisions=minimum_distance,
        collision_detection_distance=detection_distance,
        bound_relaxation=0,
        broadphase=True,
    )
    if set(limit.geom_id_pairs) != set(geometry.pairs):
        raise RuntimeError("Mink omitted explicit collision pairs")
    return limit


class CollisionRefinementLimit:
    """Additional local planes from rejected trial configurations."""

    def __init__(self):
        self.rows, self.bounds = [], []

    def compute_qp_inequalities(self, configuration, dt):
        import mink

        if not self.rows:
            return mink.Constraint()
        matrix = np.array(self.rows)
        return mink.Constraint(G=matrix, h=np.array(self.bounds) - matrix @ configuration.q)

    def add(self, model, data, geometry, indices, floor, before, detection_distance):
        import mujoco
        from mink.limits.collision_avoidance_limit import compute_contact_normal_jacobian

        added = 0
        for index in indices[:8]:
            a, b = geometry.pairs[index]
            fromto = np.empty(6)
            distance = mujoco.mj_geomDistance(model, data, a, b, detection_distance, fromto)
            derivative = compute_contact_normal_jacobian(
                model,
                data,
                a,
                b,
                fromto,
                np.empty(3),
                np.empty((3, model.nv)),
                np.empty((3, model.nv)),
            ) * (1 if distance >= 0 else -1)
            norm = np.linalg.norm(derivative)
            if norm < 1e-12:
                continue
            bound = max(0.0, distance - floor[index] - derivative @ (data.qpos - before))
            row = -derivative / norm
            self.rows.append(row)
            self.bounds.append(bound / norm + row @ before)
            added += 1
        return added
