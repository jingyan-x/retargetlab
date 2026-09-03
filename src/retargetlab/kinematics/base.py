"""Backend protocol designed around the weakest supported capabilities."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict

from retargetlab.contracts import IKResult, Pose, RobotProfile, SolveOptions


class Capabilities(BaseModel):
    """Feature declaration consumed by orchestration layers."""

    model_config = ConfigDict(extra="forbid")

    batch_targets: bool = False
    world_collision: bool = False
    self_collision_barrier: bool = False
    multi_group_joint_solve: bool = False


class KinematicsBackend(Protocol):
    """Minimal common interface for FK/Jacobian/IK backends."""

    name: str
    version: str

    @property
    def capabilities(self) -> Capabilities: ...

    def load(self, profile: RobotProfile) -> None: ...

    def fk(
        self,
        group: str,
        q: Sequence[float] | NDArray[np.floating],
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Return positions (M, 3) and wxyz quaternions (M, 4)."""
        ...

    def jacobian(
        self,
        group: str,
        q: Sequence[float] | NDArray[np.floating],
    ) -> NDArray[np.float64]: ...

    def solve_frame(
        self,
        group: str,
        target: Pose,
        seed: Sequence[float] | NDArray[np.floating],
        opts: SolveOptions,
    ) -> IKResult: ...

    def solve_sequence(
        self,
        group: str,
        targets: Sequence[Pose],
        seed: Sequence[float] | NDArray[np.floating],
        opts: SolveOptions,
    ) -> Sequence[IKResult]: ...

    def min_distance(
        self,
        q: Sequence[float] | NDArray[np.floating],
    ) -> dict[str, float] | None:
        """Return a distance report or None when the backend has no collision support."""
