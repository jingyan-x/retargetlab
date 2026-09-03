"""Pinocchio FK and Jacobian backend for the M0 Panda foundation."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from retargetlab.contracts import IKResult, Pose, RobotProfile, SolveOptions
from retargetlab.kinematics.base import Capabilities
from retargetlab.kinematics.transforms import matrix_to_quaternion_wxyz

try:
    import pinocchio as pin  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - exercised only in a missing-optional-dependency env
    pin = None  # type: ignore[assignment]


FloatArray = NDArray[np.float64]


class PinocchioBackend:
    """Load one explicit robot profile and expose deterministic FK/Jacobians."""

    name = "pinocchio"

    def __init__(self, profile: RobotProfile | None = None) -> None:
        if pin is None:
            raise RuntimeError("Pinocchio is required for PinocchioBackend")
        self.profile: RobotProfile | None = None
        self.model: Any | None = None
        self.data: Any | None = None
        self.version = str(getattr(pin, "__version__", "unknown"))
        if profile is not None:
            self.load(profile)

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            batch_targets=True,
            world_collision=False,
            self_collision_barrier=False,
            multi_group_joint_solve=False,
        )

    def load(self, profile: RobotProfile) -> None:
        """Load the profile's URDF and keep all path resolution explicit."""

        urdf_path = self._resolve_path(profile.asset_dir, profile.urdf_path)
        if not urdf_path.is_file():
            raise FileNotFoundError(f"robot URDF does not exist: {urdf_path}")
        self.model = pin.buildModelFromUrdf(str(urdf_path))
        self.data = self.model.createData()
        self.profile = profile

    @staticmethod
    def _resolve_path(asset_dir: str, relative_or_absolute: str) -> Path:
        candidate = Path(relative_or_absolute)
        if candidate.is_absolute():
            return candidate
        return Path(asset_dir) / candidate

    def _require_loaded(self) -> tuple[Any, Any, RobotProfile]:
        if self.model is None or self.data is None or self.profile is None:
            raise RuntimeError("PinocchioBackend.load(profile) must be called first")
        return self.model, self.data, self.profile

    @staticmethod
    def _validate_q(model: Any, q: Sequence[float] | NDArray[np.floating]) -> FloatArray:
        values = np.asarray(q, dtype=float)
        if values.ndim not in (1, 2) or values.shape[-1] != model.nq:
            raise ValueError(f"q must have shape ({model.nq},) or (M, {model.nq})")
        if values.ndim == 2 and values.shape[0] == 0:
            raise ValueError("q batch must contain at least one configuration")
        if not np.all(np.isfinite(values)):
            raise ValueError("q must contain only finite values")
        return values

    @staticmethod
    def _group_frame_id(model: Any, profile: RobotProfile, group: str) -> int:
        try:
            group_profile = next(item for item in profile.groups if item.name == group)
        except StopIteration as exc:
            raise KeyError(f"unknown kinematic group: {group}") from exc
        frame_id = int(model.getFrameId(group_profile.end_effector_frame))
        if frame_id >= int(model.nframes):
            raise KeyError(
                f"end-effector frame is not present in the loaded model: "
                f"{group_profile.end_effector_frame}"
            )
        return frame_id

    def _fk_one(self, frame_id: int, q: FloatArray) -> tuple[FloatArray, FloatArray]:
        model, data, _ = self._require_loaded()
        pin.forwardKinematics(model, data, q)
        pin.updateFramePlacements(model, data)
        placement = data.oMf[frame_id]
        position = np.asarray(placement.translation, dtype=float).copy()
        quaternion = matrix_to_quaternion_wxyz(np.asarray(placement.rotation, dtype=float))
        return position, quaternion

    def fk(
        self,
        group: str,
        q: Sequence[float] | NDArray[np.floating],
    ) -> tuple[FloatArray, FloatArray]:
        """Return one pose or a batch of poses, always using wxyz output order."""

        model, _, profile = self._require_loaded()
        values = self._validate_q(model, q)
        frame_id = self._group_frame_id(model, profile, group)
        if values.ndim == 1:
            return self._fk_one(frame_id, values)
        poses = [self._fk_one(frame_id, row) for row in values]
        return np.vstack([pose[0] for pose in poses]), np.vstack([pose[1] for pose in poses])

    def _jacobian_one(self, frame_id: int, q: FloatArray) -> FloatArray:
        model, data, _ = self._require_loaded()
        pin.computeJointJacobians(model, data, q)
        pin.updateFramePlacements(model, data)
        jacobian = pin.computeFrameJacobian(
            model,
            data,
            q,
            frame_id,
            pin.ReferenceFrame.LOCAL_WORLD_ALIGNED,
        )
        return np.asarray(jacobian, dtype=float).copy()

    def jacobian(
        self,
        group: str,
        q: Sequence[float] | NDArray[np.floating],
    ) -> FloatArray:
        """Return a 6xnv LOCAL_WORLD_ALIGNED Jacobian or a batch thereof."""

        model, _, profile = self._require_loaded()
        values = self._validate_q(model, q)
        frame_id = self._group_frame_id(model, profile, group)
        if values.ndim == 1:
            return self._jacobian_one(frame_id, values)
        return np.stack([self._jacobian_one(frame_id, row) for row in values])

    def solve_frame(
        self,
        group: str,
        target: Pose,
        seed: Sequence[float] | NDArray[np.floating],
        opts: SolveOptions,
    ) -> IKResult:
        raise NotImplementedError("M0.10 supplies IK; PinocchioBackend is FK/Jacobian only")

    def solve_sequence(
        self,
        group: str,
        targets: Sequence[Pose],
        seed: Sequence[float] | NDArray[np.floating],
        opts: SolveOptions,
    ) -> Sequence[IKResult]:
        raise NotImplementedError("M0.10 supplies IK; PinocchioBackend is FK/Jacobian only")

    def min_distance(self, q: Sequence[float] | NDArray[np.floating]) -> dict[str, float] | None:
        """Collision is a separate M0.5 component, so this backend returns None."""

        return None
