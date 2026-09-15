"""Pink differential IK backend with an explicit observable solve loop."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from retargetlab.contracts import IKResult, IKStatus, Pose, RobotProfile, SolveOptions
from retargetlab.kinematics.base import Capabilities
from retargetlab.kinematics.pinocchio_backend import PinocchioBackend
from retargetlab.kinematics.transforms import (
    matrix_to_quaternion_wxyz,
    pose_to_se3,
    quaternion_geodesic_angle_rad,
)
from retargetlab.robot.collision import PinocchioCollisionModel

try:
    import pinocchio as pin  # type: ignore[import-untyped]
    from pink import Configuration, FrameTask, PostureTask, solve_ik  # type: ignore[import-untyped]
    from pink.barriers import SelfCollisionBarrier  # type: ignore[import-untyped]
    from pink.limits import ConfigurationLimit, VelocityLimit  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - exercised only in a missing optional-dependency env
    pin = None  # type: ignore[assignment]
    Configuration = FrameTask = PostureTask = None
    SelfCollisionBarrier = ConfigurationLimit = VelocityLimit = None
    solve_ik = None


FloatArray = NDArray[np.float64]


class _ConfigurationBox:
    """Fixed per-sample bounds for scalar joints; Pink solves for increments."""

    def __init__(self, lower: FloatArray, upper: FloatArray) -> None:
        self.lower = lower
        self.upper = upper
        eye = np.eye(len(lower))
        self.matrix = np.vstack((eye, -eye))

    def compute_qp_inequalities(self, configuration: Any, dt: float) -> tuple:
        return self.matrix, np.hstack((self.upper - configuration.q, configuration.q - self.lower))


class PinkBackend:
    """Solve one profile group by repeatedly integrating Pink velocities."""

    name = "pink"

    def __init__(self, profile: RobotProfile | None = None) -> None:
        if pin is None or solve_ik is None:
            raise RuntimeError("Pinocchio and Pink are required for PinkBackend")
        self.pinocchio_backend = PinocchioBackend()
        self.profile: RobotProfile | None = None
        self.model: Any | None = None
        self.collision_model: PinocchioCollisionModel | None = None
        self.version = "unknown"
        try:
            import pink

            self.version = str(getattr(pink, "__version__", "unknown"))
        except ImportError:  # pragma: no cover - guarded above
            pass
        if profile is not None:
            self.load(profile)

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            batch_targets=False,
            world_collision=False,
            self_collision_barrier=self.collision_model is not None,
            multi_group_joint_solve=False,
        )

    def load(self, profile: RobotProfile) -> None:
        self.pinocchio_backend.load(profile)
        self.profile = profile
        self.model = self.pinocchio_backend.model
        self.collision_model = (
            PinocchioCollisionModel(profile) if profile.collision is not None else None
        )

    def _require_loaded(self) -> tuple[Any, RobotProfile]:
        if self.model is None or self.profile is None:
            raise RuntimeError("PinkBackend.load(profile) must be called first")
        return self.model, self.profile

    @staticmethod
    def _target_transform(target: Pose, profile: RobotProfile) -> Any:
        if target.frame != profile.root_frame:
            raise ValueError(
                f"target frame {target.frame!r} does not match robot root {profile.root_frame!r}"
            )
        return pin.SE3(
            pose_to_se3(target.position_m, target.quaternion_wxyz)[:3, :3],
            np.asarray(target.position_m, dtype=float),
        )

    @staticmethod
    def _metrics(configuration: Any, frame: str, target: Any) -> tuple[float, float]:
        current = configuration.get_transform_frame_to_world(frame)
        position_error = float(
            np.linalg.norm(np.asarray(current.translation) - np.asarray(target.translation))
        )
        current_quaternion = matrix_to_quaternion_wxyz(np.asarray(current.rotation))
        target_quaternion = matrix_to_quaternion_wxyz(np.asarray(target.rotation))
        orientation_error = quaternion_geodesic_angle_rad(current_quaternion, target_quaternion)
        return position_error, orientation_error

    @staticmethod
    def _classify_exception(exc: Exception) -> IKStatus:
        name = type(exc).__name__.lower()
        message = str(exc).lower()
        if "limit" in name or "limit" in message:
            return IKStatus.LIMIT_VIOLATION
        if any(token in name or token in message for token in ("nan", "finite", "numeric")):
            return IKStatus.NUMERICAL_FAILURE
        if any(token in name or token in message for token in ("qp", "solution", "osqp")):
            return IKStatus.QP_FAILED
        return IKStatus.QP_FAILED

    def _result(
        self,
        configuration: Any,
        frame: str,
        target: Any,
        status: IKStatus,
        iterations: int,
        reason: str,
        opts: SolveOptions,
    ) -> IKResult:
        position_error, orientation_error = self._metrics(configuration, frame, target)
        if status is not IKStatus.CONVERGED:
            if (
                position_error <= opts.position_tolerance_m
                and orientation_error <= opts.orientation_tolerance_rad
            ):
                status = IKStatus.CONVERGED
                reason = "pose_tolerance_after_termination"
        collision_free: bool | None = None
        if self.collision_model is not None:
            collision_free = self.collision_model.report(configuration.q).collision_free
        return IKResult(
            status=status,
            q=tuple(float(value) for value in configuration.q),
            iterations=iterations,
            position_error_m=position_error,
            orientation_error_rad=orientation_error,
            termination_reason=reason,
            solver=opts.qp_solver,
            collision_free=collision_free,
        )

    def solve_frame(
        self,
        group: str,
        target: Pose,
        seed: Sequence[float] | NDArray[np.floating],
        opts: SolveOptions,
    ) -> IKResult:
        """Run Pink's velocity/integrate/recompute loop for one target frame."""

        if (
            opts.qp_solver != "osqp"
            or opts.self_collision_recovery_margin_m
            or opts.self_collision_refinement_steps
        ):
            raise ValueError(
                "DAQP and native collision refinement options are registered only for Mink"
            )
        model, profile = self._require_loaded()
        if self.profile is None:
            raise RuntimeError("PinkBackend profile is not loaded")
        target_transform = self._target_transform(target, profile)
        frame_profile = next((item for item in profile.groups if item.name == group), None)
        if frame_profile is None:
            raise KeyError(f"unknown kinematic group: {group}")
        q = np.asarray(seed, dtype=float)
        if q.shape != (model.nq,):
            raise ValueError(f"seed must have shape ({model.nq},)")
        if not np.all(np.isfinite(q)):
            raise ValueError("seed must contain only finite values")
        q = np.clip(q, model.lowerPositionLimit, model.upperPositionLimit)
        barrier_geometry = (
            self.collision_model.barrier_geometry(opts.collision_barrier_pair_budget)
            if self.collision_model is not None
            else None
        )
        configuration = Configuration(
            model,
            model.createData(),
            q,
            collision_model=barrier_geometry if opts.enable_self_collision_barrier else None,
        )
        task = FrameTask(
            frame_profile.end_effector_frame,
            opts.position_cost,
            opts.orientation_cost,
        )
        task.set_target(target_transform)
        limits = [ConfigurationLimit(model), VelocityLimit(model)]
        barriers = (
            [
                SelfCollisionBarrier(
                    len(barrier_geometry.collisionPairs),
                    d_min=opts.self_collision_min_distance_m,
                )
            ]
            if barrier_geometry is not None and barrier_geometry.collisionPairs
            else []
        )
        best_score = float("inf")
        no_progress = 0
        status = IKStatus.MAX_ITER
        reason = "max_iterations"
        iterations = 0
        try:
            for iteration in range(1, opts.max_iterations + 1):
                iterations = iteration
                position_error, orientation_error = self._metrics(
                    configuration, frame_profile.end_effector_frame, target_transform
                )
                if (
                    position_error <= opts.position_tolerance_m
                    and orientation_error <= opts.orientation_tolerance_rad
                ):
                    status = IKStatus.CONVERGED
                    reason = "pose_tolerance"
                    break
                score = max(
                    position_error / opts.position_tolerance_m,
                    orientation_error / opts.orientation_tolerance_rad,
                )
                if score < best_score - opts.no_progress_min_delta:
                    best_score = score
                    no_progress = 0
                else:
                    no_progress += 1
                if no_progress >= opts.no_progress_window:
                    status = IKStatus.RESIDUAL_TOO_HIGH
                    reason = "no_progress_window"
                    break
                velocity = solve_ik(
                    configuration,
                    [task],
                    opts.integration_dt_s,
                    solver=opts.qp_solver,
                    damping=opts.damping,
                    limits=limits if opts.enforce_configuration_limits else None,
                    barriers=barriers if opts.enable_self_collision_barrier else None,
                    safety_break=False,
                    eps_abs=opts.qp_eps_abs,
                    eps_rel=opts.qp_eps_rel,
                    max_iter=opts.qp_max_iterations,
                    polish=opts.qp_polish,
                )
                if not np.all(np.isfinite(velocity)):
                    status = IKStatus.NUMERICAL_FAILURE
                    reason = "nonfinite_velocity"
                    break
                next_q = pin.integrate(model, configuration.q, velocity * opts.integration_dt_s)
                if not np.all(np.isfinite(next_q)):
                    status = IKStatus.NUMERICAL_FAILURE
                    reason = "nonfinite_configuration"
                    break
                configuration.update(
                    np.clip(next_q, model.lowerPositionLimit, model.upperPositionLimit)
                )
            else:
                status = IKStatus.MAX_ITER
                reason = "max_iterations"
        except Exception as exc:  # noqa: BLE001 - convert backend errors to observable status.
            status = self._classify_exception(exc)
            reason = type(exc).__name__
        return self._result(
            configuration,
            frame_profile.end_effector_frame,
            target_transform,
            status,
            iterations,
            reason,
            opts,
        )

    def solve_sequence(
        self,
        group: str,
        targets: Sequence[Pose],
        seed: Sequence[float] | NDArray[np.floating],
        opts: SolveOptions,
    ) -> list[IKResult]:
        """Solve a sequence with the previous result as the next warm start."""

        results: list[IKResult] = []
        current_seed = np.asarray(seed, dtype=float)
        for target in targets:
            result = self.solve_frame(group, target, current_seed, opts)
            results.append(result)
            current_seed = np.asarray(result.q, dtype=float)
        return results

    def solve_targets_frame(
        self,
        targets: Mapping[str, Pose],
        seed: Sequence[float] | NDArray[np.floating],
        opts: SolveOptions,
        *,
        previous_q: Sequence[float] | NDArray[np.floating] | None = None,
        sample_dt_s: float | None = None,
        posture_cost: float = 0.005,
    ) -> IKResult:
        """Solve simultaneous groups of ONE stream with a per-sample speed box.

        Scalar bounded joints only. Non-group joints stay at the seed. The
        previous frame defines immutable bounds for the entire iterative solve;
        integration_dt_s is not used as a substitute for the data interval.
        This is not a joint optimization of observation and action streams.
        """
        if (
            opts.qp_solver != "osqp"
            or opts.self_collision_recovery_margin_m
            or opts.self_collision_refinement_steps
        ):
            raise ValueError(
                "DAQP and native collision refinement options are registered only for Mink"
            )
        model, profile = self._require_loaded()
        if not targets:
            raise ValueError("at least one group target is required")
        if not opts.enforce_configuration_limits:
            raise ValueError("simultaneous sample solve requires configuration limits")
        if model.nq != model.nv or any(j.nq != 1 for j in list(model.joints)[1:]):
            raise ValueError("sample bounds require scalar bounded joints")
        if not np.isfinite(posture_cost) or posture_cost < 0:
            raise ValueError("posture_cost must be finite and nonnegative")
        q = np.asarray(seed, dtype=float).copy()
        if q.shape != (model.nq,) or not np.isfinite(q).all():
            raise ValueError(f"seed must be finite with shape ({model.nq},)")
        lower, upper = model.lowerPositionLimit.copy(), model.upperPositionLimit.copy()
        if not np.isfinite(lower).all() or not np.isfinite(upper).all():
            raise ValueError("sample bounds require finite joint limits")
        if (q < lower).any() or (q > upper).any():
            raise ValueError("seed is outside joint bounds")
        group_map = {group.name: group for group in profile.groups}
        active: set[int] = set()
        frame_targets = []
        tasks = []
        for name, target in targets.items():
            if name not in group_map:
                raise KeyError(f"unknown kinematic group: {name}")
            group = group_map[name]
            for joint_name in group.joint_names:
                joint_id = model.getJointId(joint_name)
                if not 0 < joint_id < model.njoints:
                    raise ValueError(f"group joint missing in model: {joint_name}")
                active.add(model.joints[joint_id].idx_q)
            transform = self._target_transform(target, profile)
            task = FrameTask(group.end_effector_frame, opts.position_cost, opts.orientation_cost)
            task.set_target(transform)
            tasks.append(task)
            frame_targets.append((group.end_effector_frame, transform))
        if (previous_q is None) != (sample_dt_s is None):
            raise ValueError("previous_q and sample_dt_s must be supplied together")
        reference = q.copy()
        if previous_q is not None:
            reference = np.asarray(previous_q, dtype=float)
            if reference.shape != q.shape or not np.isfinite(reference).all():
                raise ValueError("previous_q must match the finite model configuration")
            if not np.isfinite(sample_dt_s) or sample_dt_s <= 0:
                raise ValueError("sample_dt_s must be finite and positive")
            if (reference < lower).any() or (reference > upper).any():
                raise ValueError("previous_q is outside joint bounds")
            speed = model.velocityLimit
            if not np.isfinite(speed).all() or (speed < 0).any():
                raise ValueError("sample bounds require finite nonnegative velocity limits")
            lower = np.maximum(lower, reference - speed * sample_dt_s)
            upper = np.minimum(upper, reference + speed * sample_dt_s)
            if (q < lower - 1e-12).any() or (q > upper + 1e-12).any():
                raise ValueError("seed exceeds the previous-frame velocity box")
        inactive = sorted(set(range(model.nq)) - active)
        lower[inactive] = q[inactive]
        upper[inactive] = q[inactive]
        box = _ConfigurationBox(lower, upper)
        geometry = (
            self.collision_model.barrier_geometry(opts.collision_barrier_pair_budget)
            if self.collision_model is not None and opts.enable_self_collision_barrier
            else None
        )
        configuration = Configuration(model, model.createData(), q, collision_model=geometry)
        if posture_cost:
            posture = PostureTask(cost=posture_cost)
            posture.set_target(reference)
            tasks.append(posture)
        barriers = (
            [
                SelfCollisionBarrier(
                    len(geometry.collisionPairs), d_min=opts.self_collision_min_distance_m
                )
            ]
            if geometry is not None and geometry.collisionPairs
            else []
        )
        best_score, stale = float("inf"), 0
        status, reason, iterations = IKStatus.MAX_ITER, "max_iterations", 0
        try:
            for iteration in range(opts.max_iterations):
                errors = [
                    self._metrics(configuration, frame, target) for frame, target in frame_targets
                ]
                score = max(
                    max(p / opts.position_tolerance_m, r / opts.orientation_tolerance_rad)
                    for p, r in errors
                )
                if score <= 1:
                    status, reason = IKStatus.CONVERGED, "bilateral_pose_tolerance"
                    break
                if score < best_score - opts.no_progress_min_delta:
                    best_score, stale = score, 0
                else:
                    stale += 1
                if stale >= opts.no_progress_window:
                    status, reason = IKStatus.RESIDUAL_TOO_HIGH, "no_progress_window"
                    break
                velocity = solve_ik(
                    configuration,
                    tasks,
                    opts.integration_dt_s,
                    solver=opts.qp_solver,
                    damping=opts.damping,
                    limits=[box, VelocityLimit(model)],
                    barriers=barriers,
                    safety_break=False,
                    eps_abs=opts.qp_eps_abs,
                    eps_rel=opts.qp_eps_rel,
                    max_iter=opts.qp_max_iterations,
                    polish=opts.qp_polish,
                )
                if not np.isfinite(velocity).all():
                    status, reason = IKStatus.NUMERICAL_FAILURE, "nonfinite_velocity"
                    break
                next_q = pin.integrate(model, configuration.q, velocity * opts.integration_dt_s)
                # Enforce the declared box despite finite QP tolerance, then
                # recompute actual FK; clipping can never manufacture pose PASS.
                configuration.update(np.clip(next_q, lower, upper))
                iterations = iteration + 1
        except Exception as exc:  # noqa: BLE001 - retain observable backend failure.
            status, reason = self._classify_exception(exc), type(exc).__name__
        errors = [self._metrics(configuration, frame, target) for frame, target in frame_targets]
        position_error = max(p for p, _ in errors)
        orientation_error = max(r for _, r in errors)
        if (
            position_error <= opts.position_tolerance_m
            and orientation_error <= opts.orientation_tolerance_rad
        ):
            status, reason = IKStatus.CONVERGED, "bilateral_pose_tolerance"
        collision_free = (
            self.collision_model.report(configuration.q).collision_free
            if self.collision_model is not None
            else None
        )
        return IKResult(
            status=status,
            q=tuple(float(v) for v in configuration.q),
            iterations=iterations,
            position_error_m=position_error,
            orientation_error_rad=orientation_error,
            termination_reason=reason,
            solver=opts.qp_solver,
            collision_free=collision_free,
            joint_limit_violation=False,
        )
