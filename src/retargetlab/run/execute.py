"""Recipe-bound solve execution that materializes a complete run."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from retargetlab.contracts import (
    CanonicalTrajectory,
    DatasetReport,
    IKResult,
    Recipe,
    RobotProfile,
    RunManifest,
)
from retargetlab.diagnose import diagnose_episode
from retargetlab.run.fingerprint import recipe_sha256
from retargetlab.run.report import write_dataset_report
from retargetlab.run.workspace import RunWorkspace, create_run_workspace


@dataclass(frozen=True)
class SolveRunResult:
    """Materialized solve evidence and its diagnostic result."""

    workspace: RunWorkspace
    solution_path: Path
    report: DatasetReport
    manifest: RunManifest
    results: tuple[IKResult, ...]


def solve_canonical_stream(
    trajectory: CanonicalTrajectory,
    profile: RobotProfile,
    recipe: Recipe,
    group: str,
    initial_q: Sequence[float],
) -> tuple[IKResult, ...]:
    """Solve one canonical stream after checking recipe/backend identity."""

    if recipe.robot_id != profile.robot_id:
        raise ValueError("recipe robot_id does not match the robot profile")
    if group not in trajectory.stream_names:
        raise ValueError(f"trajectory stream is not present: {group}")

    from retargetlab.kinematics.pink_backend import PinkBackend

    backend = PinkBackend(profile)
    if recipe.backend_name != backend.name:
        raise ValueError("recipe backend_name does not match the selected backend")
    if recipe.backend_version != backend.version:
        raise ValueError("recipe backend_version does not match the selected backend")
    return tuple(
        backend.solve_sequence(
            group,
            [frame.poses[group] for frame in trajectory.frames],
            initial_q,
            recipe.solve_options,
        )
    )


def _write_solutions(
    workspace: RunWorkspace,
    recipe: Recipe,
    group: str,
    results: Sequence[IKResult],
) -> Path:
    path = workspace.result_dir / "solutions.json"
    payload = {
        "schema_version": "0.1",
        "recipe_sha256": recipe_sha256(recipe),
        "group": group,
        "frame_count": len(results),
        "results": [result.model_dump(mode="json") for result in results],
    }
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def execute_solve_run(
    project_dir: Path,
    run_id: str,
    trajectory: CanonicalTrajectory,
    profile: RobotProfile,
    recipe: Recipe,
    group: str,
    initial_q: Sequence[float],
    *,
    input_sha256: str,
) -> SolveRunResult:
    """Create one immutable run and connect solve, diagnose, and report."""

    if recipe.input_sha256.lower() != input_sha256.lower():
        raise ValueError("recipe input_sha256 does not match the trajectory source")
    workspace = create_run_workspace(project_dir, run_id, recipe)
    results = solve_canonical_stream(trajectory, profile, recipe, group, initial_q)
    solution_path = _write_solutions(workspace, recipe, group, results)
    episode = diagnose_episode(results)
    report = DatasetReport(episode_count=1, episodes=(episode,), status=episode.status)
    manifest = write_dataset_report(
        workspace,
        report,
        extra_artifacts=(solution_path.relative_to(workspace.path).as_posix(),),
    )
    return SolveRunResult(
        workspace=workspace,
        solution_path=solution_path,
        report=report,
        manifest=manifest,
        results=results,
    )
