"""Formal M0 solve options and observable IK result contracts."""

from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SolveOptions(BaseModel):
    """Solver parameters whose names and units are stable across backends."""

    model_config = ConfigDict(extra="forbid")

    qp_solver: str = Field(default="osqp", min_length=1)
    integration_dt_s: float = Field(default=0.01, gt=0.0)
    max_iterations: int = Field(default=300, gt=0)
    position_tolerance_m: float = Field(default=0.005, gt=0.0)
    orientation_tolerance_rad: float = Field(default=math.radians(2.0), gt=0.0)
    damping: float = Field(default=1e-12, ge=0.0)
    position_cost: float = Field(default=1.0, gt=0.0)
    orientation_cost: float = Field(default=1.0, gt=0.0)
    qp_eps_abs: float = Field(default=1e-5, gt=0.0)
    qp_eps_rel: float = Field(default=1e-5, gt=0.0)
    qp_max_iterations: int = Field(default=4000, gt=0)
    qp_polish: bool = True
    no_progress_window: int = Field(default=20, gt=0)
    no_progress_min_delta: float = Field(default=1e-6, gt=0.0)
    retry_seed_count: int = Field(default=3, ge=1)
    random_seed: int = 20260902
    enforce_configuration_limits: bool = True
    enable_self_collision_barrier: bool = True
    self_collision_min_distance_m: float = Field(default=0.001, gt=0.0)
    collision_barrier_pair_budget: int = Field(default=16, gt=0)

    @field_validator("qp_solver")
    @classmethod
    def only_supported_qp_solver(cls, value: str) -> str:
        if value != "osqp":
            raise ValueError("M0 currently supports only the registered osqp solver")
        return value


class IKStatus(StrEnum):
    """Observable solver outcomes; local IK is not a proof of infeasibility."""

    CONVERGED = "CONVERGED"
    MAX_ITER = "MAX_ITER"
    QP_FAILED = "QP_FAILED"
    LIMIT_VIOLATION = "LIMIT_VIOLATION"
    NUMERICAL_FAILURE = "NUMERICAL_FAILURE"
    RESIDUAL_TOO_HIGH = "RESIDUAL_TOO_HIGH"


class IKResult(BaseModel):
    """One backend result with enough data for read-only diagnosis."""

    model_config = ConfigDict(extra="forbid")

    status: IKStatus
    q: tuple[float, ...]
    iterations: int = Field(ge=0)
    position_error_m: float = Field(ge=0.0)
    orientation_error_rad: float = Field(ge=0.0)
    termination_reason: str = Field(min_length=1)
    solver: str = Field(min_length=1)
    collision_free: bool | None = None
    joint_limit_violation: bool = False
