"""MuJoCo/Mink IK with explicit named vectors and whole-sample bounds."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib.metadata import version
from pathlib import Path

import numpy as np

from retargetlab.contracts import IKResult, IKStatus, Pose, RobotProfile, SolveOptions
from retargetlab.kinematics.base import Capabilities
from retargetlab.kinematics.transforms import (
    matrix_to_quaternion_wxyz,
    pose_to_se3,
    quaternion_geodesic_angle_rad,
)
from retargetlab.robot.mujoco_model import MujocoKinematics


class _ConfigurationBox:
    """Immutable sample bounds expressed in MuJoCo's scalar tangent order."""

    def __init__(self, lower, upper):
        self.lower, self.upper = lower, upper
        self.matrix = np.vstack((np.eye(len(lower)), -np.eye(len(lower))))

    def compute_qp_inequalities(self, configuration, dt):
        from mink import Constraint

        return Constraint(
            G=self.matrix, h=np.r_[self.upper - configuration.q, configuration.q - self.lower]
        )


class MinkBackend:
    """Native MuJoCo FK/Jacobians and Mink solves; no Pinocchio calls in IK.

    Public q vectors use the explicitly supplied joint-name order. The process
    layer independently checks the result against its established Pinocchio
    model and collision policy.
    """

    name = "mink"

    def __init__(
        self,
        profile: RobotProfile | None = None,
        *,
        model_dir: Path,
        joint_names: Sequence[str] | None = None,
    ):
        import mink
        import mujoco

        self.mink, self.mujoco = mink, mujoco
        self.version = version("mink")
        self.model_dir = Path(model_dir)
        self._requested_names = tuple(joint_names) if joint_names is not None else None
        self.profile = None
        if profile is not None:
            self.load(profile)

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            batch_targets=True,
            world_collision=False,
            self_collision_barrier=True,
            multi_group_joint_solve=True,
        )

    def load(self, profile: RobotProfile) -> None:
        stored = RobotProfile.model_validate_json(
            (self.model_dir / "source-profile.json").read_text()
        )
        if stored != profile:
            raise ValueError("MuJoCo model must match the complete robot profile")
        self.engine = MujocoKinematics(self.model_dir)
        self.model = self.engine.model
        if self.model.nq != self.model.nv:
            raise ValueError("sample bounds require a fixed-body scalar-joint model")
        self.profile = profile
        self.collision_geometry = None
        self._collision_limit_cache = None
        mapping = self.engine.metadata["joints"]
        self.joint_names = self._requested_names or tuple(mapping)
        if len(set(self.joint_names)) != len(self.joint_names) or set(self.joint_names) != set(
            mapping
        ):
            raise ValueError("public joint order must name all model joints exactly once")
        self.q_indices = np.array([mapping[n]["qpos_address"] for n in self.joint_names])
        self.v_indices = np.array([mapping[n]["qvel_address"] for n in self.joint_names])
        # This adapter intentionally supports only scalar joints with equal q/v addresses.
        if not np.array_equal(self.q_indices, self.v_indices):
            raise ValueError("scalar model qpos and qvel mappings must agree")
        self.lower = np.array([mapping[n]["lower"] for n in self.joint_names])
        self.upper = np.array([mapping[n]["upper"] for n in self.joint_names])
        self.speed = np.array([mapping[n]["velocity"] for n in self.joint_names])
        self.velocity_limit = self.mink.VelocityLimit(
            self.model, {n: mapping[n]["velocity"] for n in self.joint_names}
        )
        self.groups = {g.name: g for g in profile.groups}
        self.sites = {
            g: self.model.site(entry["site"]).id
            for g, entry in self.engine.metadata["tcp_sites"].items()
        }
        self.root_id = self.model.body(profile.root_frame).id
        root = self.root_id
        while root:
            if self.model.body_jntnum[root]:
                raise ValueError("the declared root must be fixed in MuJoCo world")
            root = self.model.body_parentid[root]

    def _validate(self, q):
        if self.profile is None:
            raise RuntimeError("MinkBackend.load(profile) must be called first")
        values = np.asarray(q, dtype=float)
        if values.shape != (len(self.joint_names),) or not np.isfinite(values).all():
            raise ValueError("configuration must be finite and match the public joint order")
        self.engine.set_configuration(self.joint_names, values)
        return values.copy()

    def _native(self, values):
        native = np.empty(self.model.nq)
        native[self.q_indices] = values
        return native

    def _configuration(self, q):
        return self.mink.Configuration(self.model, self._native(self._validate(q)))

    def fk(self, group: str, q):
        if group not in self.groups:
            raise KeyError(f"unknown kinematic group: {group}")
        values = np.asarray(q, dtype=float)
        if values.ndim == 2:
            if not len(values):
                raise ValueError("FK batch must not be empty")
            poses = [self.fk(group, row) for row in values]
            return np.stack([p for p, _ in poses]), np.stack([r for _, r in poses])
        config = self._configuration(values)
        root_r = config.data.xmat[self.root_id].reshape(3, 3)
        site = self.sites[group]
        p = root_r.T @ (config.data.site_xpos[site] - config.data.xpos[self.root_id])
        r = root_r.T @ config.data.site_xmat[site].reshape(3, 3)
        return p, matrix_to_quaternion_wxyz(r)

    def jacobian(self, group: str, q):
        if group not in self.groups:
            raise KeyError(f"unknown kinematic group: {group}")
        values = np.asarray(q, dtype=float)
        if values.ndim == 2:
            if not len(values):
                raise ValueError("Jacobian batch must not be empty")
            return np.stack([self.jacobian(group, row) for row in values])
        config = self._configuration(values)
        jp, jr = np.zeros((3, self.model.nv)), np.zeros((3, self.model.nv))
        self.mujoco.mj_jacSite(self.model, config.data, jp, jr, self.sites[group])
        root_r = config.data.xmat[self.root_id].reshape(3, 3)
        return np.vstack((root_r.T @ jp, root_r.T @ jr))[:, self.v_indices]

    def _metrics(self, config, group, world_target):
        site = self.sites[group]
        p = float(np.linalg.norm(config.data.site_xpos[site] - world_target[:3, 3]))
        angle = quaternion_geodesic_angle_rad(
            matrix_to_quaternion_wxyz(config.data.site_xmat[site].reshape(3, 3)),
            matrix_to_quaternion_wxyz(world_target[:3, :3]),
        )
        return p, angle

    @staticmethod
    def qp_settings(opts):
        """DAQP uses absolute primal/dual tolerances; OSQP options stay unchanged."""
        if opts.qp_solver == "daqp":
            return dict(
                primal_tol=opts.qp_eps_abs,
                dual_tol=opts.qp_eps_abs,
                iter_limit=opts.qp_max_iterations,
            )
        return dict(
            eps_abs=opts.qp_eps_abs,
            eps_rel=opts.qp_eps_rel,
            max_iter=opts.qp_max_iterations,
            polish=opts.qp_polish,
        )

    def _refined_collision_step(
        self, config, tasks, opts, limits, lower, upper, floor, world_targets, detection_distance
    ):
        from retargetlab.robot.native_collision import CollisionRefinementLimit

        before = config.q.copy()
        cuts = CollisionRefinementLimit()
        best_step = None
        for refinement in range(opts.self_collision_refinement_steps + 1):
            config.update(before)
            try:
                velocity = self.mink.solve_ik(
                    config,
                    tasks,
                    opts.integration_dt_s,
                    solver=opts.qp_solver,
                    damping=opts.damping,
                    safety_break=True,
                    limits=limits + [cuts],
                    **self.qp_settings(opts),
                )
            except self.mink.NoSolutionFound:
                if best_step is None:
                    raise
                break
            if not np.isfinite(velocity).all():
                raise self.mink.NoSolutionFound(opts.qp_solver)
            proposed = np.clip(config.integrate(velocity, opts.integration_dt_s), lower, upper)
            rejected = None
            accepted = False
            for reduction in range(13):
                config.update(before + (proposed - before) * 2.0 ** (-reduction))
                checked = self.collision_geometry.distances(config.data, detection_distance)
                bad = np.flatnonzero(checked < floor - 1e-8)
                if len(bad) == 0:
                    errors = [self._metrics(config, g, t) for g, t in world_targets.items()]
                    value = max(
                        max(p / opts.position_tolerance_m, a / opts.orientation_tolerance_rad)
                        for p, a in errors
                    )
                    if best_step is None or value < best_step[2]:
                        best_step = (config.q.copy(), checked.copy(), value)
                    accepted = True
                    break
                rejected = (config.q.copy(), bad[np.argsort(checked[bad] - floor[bad])])
            if accepted and reduction <= 3:
                break
            if rejected is None or refinement == opts.self_collision_refinement_steps:
                break
            config.update(rejected[0])
            if (
                cuts.add(
                    self.model,
                    config.data,
                    self.collision_geometry,
                    rejected[1],
                    floor,
                    before,
                    detection_distance,
                )
                == 0
            ):
                break
        config.update(before if best_step is None else best_step[0])
        return best_step

    def solve_targets_frame(
        self,
        targets: Mapping[str, Pose],
        seed,
        opts: SolveOptions,
        *,
        previous_q=None,
        sample_dt_s=None,
        posture_cost=0.005,
    ) -> IKResult:
        if not targets:
            raise ValueError("at least one group target is required")
        if not opts.enforce_configuration_limits:
            raise ValueError("sample solve requires configuration limits")
        if not np.isfinite(posture_cost) or posture_cost < 0:
            raise ValueError("posture_cost must be finite and nonnegative")
        q = self._validate(seed)
        lower, upper = self.lower.copy(), self.upper.copy()
        if (q < lower).any() or (q > upper).any():
            raise ValueError("seed is outside joint bounds")
        if (previous_q is None) != (sample_dt_s is None):
            raise ValueError("previous_q and sample_dt_s must be supplied together")
        reference = q.copy()
        if previous_q is not None:
            reference = self._validate(previous_q)
            if not np.isfinite(sample_dt_s) or sample_dt_s <= 0:
                raise ValueError("sample_dt_s must be finite and positive")
            if (reference < lower).any() or (reference > upper).any():
                raise ValueError("previous_q is outside joint bounds")
            lower = np.maximum(lower, reference - self.speed * sample_dt_s)
            upper = np.minimum(upper, reference + self.speed * sample_dt_s)
            if (q < lower - 1e-12).any() or (q > upper + 1e-12).any():
                raise ValueError("seed exceeds the previous-frame velocity box")
        config = self.mink.Configuration(self.model, self._native(q))
        root_transform = np.eye(4)
        root_transform[:3, :3] = config.data.xmat[self.root_id].reshape(3, 3)
        root_transform[:3, 3] = config.data.xpos[self.root_id]
        active, tasks, world_targets = set(), [], {}
        for group, target in targets.items():
            if group not in self.groups:
                raise KeyError(f"unknown kinematic group: {group}")
            if target.frame != self.profile.root_frame:
                raise ValueError("target frame does not match the declared robot root")
            active.update(self.joint_names.index(n) for n in self.groups[group].joint_names)
            world_target = root_transform @ pose_to_se3(target.position_m, target.quaternion_wxyz)
            task = self.mink.FrameTask(
                frame_name=self.engine.metadata["tcp_sites"][group]["site"],
                frame_type="site",
                position_cost=opts.position_cost,
                orientation_cost=opts.orientation_cost,
            )
            task.set_target(self.mink.SE3.from_matrix(world_target))
            tasks.append(task)
            world_targets[group] = world_target
        inactive = sorted(set(range(len(q))) - active)
        lower[inactive], upper[inactive] = q[inactive], q[inactive]
        native_lower, native_upper = self._native(lower), self._native(upper)
        box = _ConfigurationBox(native_lower, native_upper)
        if posture_cost:
            posture = self.mink.PostureTask(self.model, cost=posture_cost)
            posture.set_target(self._native(reference))
            tasks.append(posture)
        collision_limit = None
        distances = None
        detection_distance = max(0.02, opts.self_collision_min_distance_m * 10)
        if opts.enable_self_collision_barrier:
            from retargetlab.robot.native_collision import (
                NativeCollisionGeometry,
                make_collision_limit,
            )

            if self.collision_geometry is None:
                self.collision_geometry = NativeCollisionGeometry(self.engine, self.profile)
            if not self.collision_geometry.pairs:
                raise ValueError("native avoidance requires collision geometry pairs")
            if opts.collision_barrier_pair_budget < len(self.collision_geometry.pairs):
                raise ValueError(
                    "collision pair budget must cover every registered pair: "
                    f"need {len(self.collision_geometry.pairs)}"
                )
            settings = (
                opts.self_collision_min_distance_m,
                detection_distance,
                opts.self_collision_recovery_margin_m,
            )
            if self._collision_limit_cache is None or self._collision_limit_cache[0] != settings:
                self._collision_limit_cache = (
                    settings,
                    make_collision_limit(
                        self.collision_geometry, *settings[:2], recovery_margin=settings[2]
                    ),
                )
            collision_limit = self._collision_limit_cache[1]
            distances = self.collision_geometry.distances(config.data, detection_distance)
            distance_floor = np.minimum(distances, opts.self_collision_min_distance_m)
        limits = [box, self.velocity_limit]
        if collision_limit is not None:
            limits.append(collision_limit)
        best_score, stale = float("inf"), 0
        status, reason, iterations = IKStatus.MAX_ITER, "max_iterations", 0
        try:
            for iteration in range(opts.max_iterations):
                errors = [self._metrics(config, g, t) for g, t in world_targets.items()]
                score = max(
                    max(p / opts.position_tolerance_m, a / opts.orientation_tolerance_rad)
                    for p, a in errors
                )
                clearance_ok = distances is None or bool(
                    np.all(distances >= opts.self_collision_min_distance_m - 1e-8)
                )
                if score <= 1 and clearance_ok:
                    status, reason = IKStatus.CONVERGED, "all_target_pose_tolerances"
                    break
                if score < best_score - opts.no_progress_min_delta:
                    best_score, stale = score, 0
                else:
                    stale += 1
                if stale >= opts.no_progress_window:
                    status, reason = IKStatus.RESIDUAL_TOO_HIGH, "no_progress_window"
                    break
                if distances is not None and opts.self_collision_refinement_steps:
                    step = self._refined_collision_step(
                        config,
                        tasks,
                        opts,
                        limits,
                        native_lower,
                        native_upper,
                        distance_floor,
                        world_targets,
                        detection_distance,
                    )
                    if step is None:
                        status, reason = IKStatus.RESIDUAL_TOO_HIGH, "collision_step_rejected"
                        break
                    distances = step[1]
                    distance_floor = np.maximum(
                        distance_floor, np.minimum(distances, opts.self_collision_min_distance_m)
                    )
                else:
                    velocity = self.mink.solve_ik(
                        config,
                        tasks,
                        opts.integration_dt_s,
                        solver=opts.qp_solver,
                        damping=opts.damping,
                        safety_break=True,
                        limits=limits,
                        **self.qp_settings(opts),
                    )
                    if not np.isfinite(velocity).all():
                        status, reason = IKStatus.NUMERICAL_FAILURE, "nonfinite_velocity"
                        break
                    next_q = config.integrate(velocity, opts.integration_dt_s)
                    # The projection only handles finite QP tolerances; FK is recomputed.
                    proposed = np.clip(next_q, native_lower, native_upper)
                    if distances is None:
                        config.update(proposed)
                    else:
                        # Linearized geometry can miss curved-surface crossings. Accept
                        # only steps that keep every clear pair above the margin and
                        # never deepen an existing margin violation. This is a discrete
                        # configuration check, not swept-volume collision certification.
                        before = config.q.copy()
                        accepted = False
                        for reduction in range(13):
                            config.update(before + (proposed - before) * 2.0 ** (-reduction))
                            checked = self.collision_geometry.distances(
                                config.data, detection_distance
                            )
                            if np.all(checked >= distance_floor - 1e-8):
                                distance_floor = np.maximum(
                                    distance_floor,
                                    np.minimum(checked, opts.self_collision_min_distance_m),
                                )
                                distances = checked
                                accepted = True
                                break
                        if not accepted:
                            config.update(before)
                            status, reason = IKStatus.RESIDUAL_TOO_HIGH, "collision_step_rejected"
                            break
                iterations = iteration + 1
        except self.mink.NoSolutionFound as exc:
            status, reason = IKStatus.QP_FAILED, str(exc)
        except self.mink.NotWithinConfigurationLimits as exc:
            status, reason = IKStatus.LIMIT_VIOLATION, str(exc)
        errors = [self._metrics(config, g, t) for g, t in world_targets.items()]
        p, a = max(v[0] for v in errors), max(v[1] for v in errors)
        result_q = config.q[self.q_indices]
        violation = bool((result_q < self.lower).any() or (result_q > self.upper).any())
        clearance_ok = (
            None
            if distances is None
            else bool(np.all(distances >= opts.self_collision_min_distance_m - 1e-8))
        )
        if p <= opts.position_tolerance_m and a <= opts.orientation_tolerance_rad and not violation:
            if clearance_ok is False:
                status, reason = IKStatus.COLLISION_VIOLATION, "native_clearance_not_satisfied"
            else:
                status, reason = IKStatus.CONVERGED, "all_target_pose_tolerances"
        return IKResult(
            status=status,
            q=tuple(float(v) for v in result_q),
            iterations=iterations,
            position_error_m=p,
            orientation_error_rad=a,
            termination_reason=reason,
            solver=opts.qp_solver,
            collision_free=None if distances is None else bool(np.all(distances >= -1e-8)),
            collision_clearance_ok=clearance_ok,
            minimum_distance_m=None if distances is None else float(distances.min()),
            joint_limit_violation=violation,
        )

    def solve_frame(self, group: str, target: Pose, seed, opts: SolveOptions) -> IKResult:
        return self.solve_targets_frame({group: target}, seed, opts)

    def solve_sequence(
        self, group: str, targets: Sequence[Pose], seed, opts: SolveOptions
    ) -> list[IKResult]:
        """Legacy target-only sequence; timestamped process uses solve_targets_frame."""
        results = []
        current = np.asarray(seed, dtype=float)
        for target in targets:
            result = self.solve_frame(group, target, current, opts)
            results.append(result)
            current = np.asarray(result.q)
        return results

    def min_distance(self, q):
        """Native signed distance clipped at 20 mm; not the Coal quality policy."""
        from retargetlab.robot.native_collision import NativeCollisionGeometry

        config = self._configuration(q)
        if self.collision_geometry is None:
            self.collision_geometry = NativeCollisionGeometry(self.engine, self.profile)
        value = self.collision_geometry.minimum(config.data, 0.02)
        return None if value is None else {"minimum_distance_m": value, "distance_clip_m": 0.02}
