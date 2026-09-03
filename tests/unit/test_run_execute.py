from retargetlab.contracts import (
    DatasetReport,
    EpisodeReport,
    FrameDiagnostics,
    IKStatus,
    Recipe,
    SolveOptions,
    Threshold,
)
from retargetlab.run import create_run_workspace, write_dataset_report


def make_recipe() -> Recipe:
    return Recipe(
        recipe_id="execute-fixture",
        dataset_alias="synthetic-fixture",
        input_sha256="1" * 64,
        robot_id="fixture",
        robot_asset_sha256="2" * 64,
        backend_name="fixture",
        backend_version="0.1",
        solve_options=SolveOptions(),
        random_seed=1,
        split_sha256="3" * 64,
        thresholds={
            "position": Threshold(
                warn=0.005,
                fail=0.005,
                unit="m",
                source="fixture",
                provenance="test",
            )
        },
    )


def test_report_extra_artifact_is_recorded(tmp_path) -> None:
    workspace = create_run_workspace(tmp_path, "run-001", make_recipe())
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
    manifest = write_dataset_report(
        workspace,
        DatasetReport(episode_count=1, episodes=(episode,), status="PASS"),
        extra_artifacts=("result/solutions.json",),
    )
    assert "result/solutions.json" in manifest.artifacts
