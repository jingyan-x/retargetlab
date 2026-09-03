"""Immutable run-input contracts and provenance references."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from retargetlab.contracts.solve import SolveOptions
from retargetlab.contracts.threshold import Threshold

Hash = str


class Recipe(BaseModel):
    """All input facts that define one reproducible computation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    recipe_id: str = Field(min_length=1)
    dataset_alias: str = Field(min_length=1)
    input_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    robot_id: str = Field(min_length=1)
    robot_asset_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    backend_name: str = Field(min_length=1)
    backend_version: str = Field(min_length=1)
    solve_coupling: str = Field(default="independent", min_length=1)
    solve_options: SolveOptions
    random_seed: int
    split_name: str = Field(default="synthetic", min_length=1)
    split_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    thresholds: dict[str, Threshold] = Field(min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)


class RunManifest(BaseModel):
    """Completion record for a run directory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    run_id: str = Field(min_length=1)
    status: Literal["COMPLETED"] = "COMPLETED"
    recipe_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    report_sha256: Hash = Field(pattern=r"^[0-9a-fA-F]{64}$")
    artifacts: tuple[str, ...] = Field(min_length=1)
    completed_at_utc: str = Field(min_length=1)
