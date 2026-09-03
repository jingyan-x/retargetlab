import json

import pytest

from retargetlab.contracts import (
    DatasetReport,
    EpisodeReport,
    FrameDiagnostics,
    IKStatus,
    Recipe,
    SolveOptions,
    Threshold,
)
from retargetlab.run import (
    create_run_workspace,
    recipe_sha256,
    write_dataset_report,
)


def make_recipe(*, max_iterations: int = 300) -> Recipe:
    return Recipe(
        recipe_id="synthetic-run-v1",
        dataset_alias="synthetic-fixture",
        input_sha256="1" * 64,
        robot_id="fixture",
        robot_asset_sha256="2" * 64,
        backend_name="fixture",
        backend_version="0.1",
        solve_options=SolveOptions(max_iterations=max_iterations),
        random_seed=7,
        split_sha256="3" * 64,
        thresholds={
            "position": Threshold(
                warn=0.005,
                fail=0.005,
                unit="m",
                source="synthetic fixture",
                provenance="test only",
            )
        },
    )


def make_report() -> DatasetReport:
    frame = FrameDiagnostics(
        frame_index=0,
        solver_status=IKStatus.CONVERGED,
        position_error_m=0.001,
        orientation_error_rad=0.01,
        collision_free=True,
        nominal=True,
        relaxed=True,
    )
    episode = EpisodeReport(
        episode_index=0,
        frame_count=1,
        nominal_rate=1.0,
        relaxed_rate=1.0,
        collision_fraction=0.0,
        joint_limit_violation_fraction=0.0,
        delta_violation_fraction=0.0,
        status="PASS",
        frames=(frame,),
    )
    return DatasetReport(episode_count=1, episodes=(episode,), status="PASS")


def test_recipe_hash_is_stable_and_sensitive() -> None:
    first = make_recipe()
    equivalent = make_recipe()
    changed = make_recipe(max_iterations=301)
    assert recipe_sha256(first) == recipe_sha256(equivalent)
    assert recipe_sha256(first) != recipe_sha256(changed)


def test_run_workspace_and_report_are_non_overwriting(tmp_path) -> None:
    workspace = create_run_workspace(tmp_path / "project", "run-001", make_recipe())
    manifest = write_dataset_report(workspace, make_report())

    assert workspace.recipe_sha256 == manifest.recipe_sha256
    assert (workspace.path / "recipe.json").is_file()
    assert (workspace.result_dir / "report.json").is_file()
    assert (workspace.result_dir / "report.md").read_text(encoding="utf-8").startswith("# ")
    assert (
        (workspace.result_dir / "metrics.csv")
        .read_text(encoding="utf-8")
        .startswith("episode_index,")
    )
    metrics = (workspace.result_dir / "metrics.jsonl").read_text(encoding="utf-8")
    assert '"status":"PASS"' in metrics
    assert '"q"' not in metrics
    manifest_payload = json.loads(
        (workspace.path / "run-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest_payload["status"] == "COMPLETED"

    with pytest.raises(FileExistsError):
        create_run_workspace(tmp_path / "project", "run-001", make_recipe())
    with pytest.raises(FileExistsError):
        write_dataset_report(workspace, make_report())
