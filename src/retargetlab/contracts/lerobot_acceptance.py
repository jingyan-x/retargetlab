"""Contracts for the optional LeRobot export acceptance run."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Hash = str
AcceptanceStatus = Literal["PASSED", "BLOCKED", "ENVIRONMENT_UNAVAILABLE", "FAILED"]
AcceptanceCheckStatus = Literal["PASSED", "BLOCKED", "SKIPPED", "FAILED"]


class LeRobotAcceptanceCheck(BaseModel):
    """One value-free result in the five-step acceptance sequence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal[
        "config_contract",
        "episode_allowlist",
        "time_window",
        "normalization_batch",
        "fk_semantic_recheck",
    ]
    status: AcceptanceCheckStatus
    detail: str = Field(min_length=1)


class LeRobotAcceptanceReport(BaseModel):
    """Archived result of the optional, loader-backed export acceptance run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["lerobot_acceptance_report"] = "lerobot_acceptance_report"
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    status: AcceptanceStatus
    runtime_dependency: Literal["lerobot==0.6.1"] = "lerobot==0.6.1"
    dataset_alias: str = Field(min_length=1)
    repo_id: str = Field(min_length=1)
    root: str = Field(min_length=1)
    episodes: tuple[int, ...] = ()
    config_path: str = Field(min_length=1)
    config_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    checks: tuple[LeRobotAcceptanceCheck, ...] = Field(min_length=5)
    blocking_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_report(self) -> LeRobotAcceptanceReport:
        expected_names = {
            "config_contract",
            "episode_allowlist",
            "time_window",
            "normalization_batch",
            "fk_semantic_recheck",
        }
        names = tuple(check.name for check in self.checks)
        if set(names) != expected_names or len(names) != len(expected_names):
            raise ValueError("acceptance report must contain exactly five named checks")
        if len(set(self.episodes)) != len(self.episodes):
            raise ValueError("acceptance report episodes must be unique")
        if any(index < 0 for index in self.episodes):
            raise ValueError("acceptance report episodes must be non-negative")
        if len(set(self.blocking_reasons)) != len(self.blocking_reasons):
            raise ValueError("acceptance report blocking reasons must be unique")
        if any(not reason.strip() for reason in self.blocking_reasons):
            raise ValueError("acceptance report blocking reasons must be non-empty")
        if len(set(self.warnings)) != len(self.warnings):
            raise ValueError("acceptance report warnings must be unique")
        if any(not warning.strip() for warning in self.warnings):
            raise ValueError("acceptance report warnings must be non-empty")
        if self.status == "PASSED" and any(
            check.status != "PASSED" for check in self.checks
        ):
            raise ValueError("passed acceptance report must pass every check")
        if self.status != "PASSED" and not self.blocking_reasons:
            raise ValueError("non-passed acceptance report must explain its block")
        return self


class LeRobotAcceptanceReportVerification(BaseModel):
    """Value-free result of rechecking an archived acceptance report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    artifact_type: Literal["lerobot_acceptance_report_verification"] = (
        "lerobot_acceptance_report_verification"
    )
    source_scope: Literal["synthetic_public_only"] = "synthetic_public_only"
    status: Literal["VERIFIED"] = "VERIFIED"
    dataset_alias: str = Field(min_length=1)
    config_path: str = Field(min_length=1)
    config_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    report_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    acceptance_status: AcceptanceStatus
    check_count: int = Field(gt=0)
