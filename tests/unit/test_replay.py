import json
from pathlib import Path

import pytest

from retargetlab.cli.main import EXIT_OK, app
from retargetlab.contracts import (
    CanonicalFrame,
    CanonicalTrajectory,
    KinematicGroup,
    Pose,
    Recipe,
    RobotProfile,
    SolveOptions,
    TargetGripperProfile,
    Threshold,
)
from retargetlab.run import (
    build_target_replay_manifest,
    map_target_grippers,
    write_robot_profile,
    write_target_gripper_trajectory,
    write_target_replay_manifest,
)
from retargetlab.run.fingerprint import recipe_sha256, sha256_bytes


def _profile() -> RobotProfile:
    gripper = TargetGripperProfile(
        name="fixture_gripper",
        driver_joint_name="finger_joint1",
        driver_lower_m=0.0,
        driver_upper_m=0.044,
    )
    return RobotProfile(
        robot_id="fixture",
        asset_dir="assets/fixture",
        urdf_path="fixture.urdf",
        urdf_sha256="0" * 64,
        groups=(
            KinematicGroup(
                name="arm",
                joint_names=("joint1",),
                end_effector_frame="tool",
                gripper_joint_names=gripper.joint_names,
                gripper=gripper,
            ),
        ),
    )


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    profile_path = tmp_path / "profile.json"
    write_robot_profile(profile_path, _profile())
    pose = Pose(
        position_m=(0.0, 0.0, 0.0),
        quaternion_wxyz=(1.0, 0.0, 0.0, 0.0),
    )
    trajectory = CanonicalTrajectory(
        frames=[
            CanonicalFrame(
                timestamp_s=0.0,
                poses={"arm": pose},
                grippers={"arm": 0.0},
            ),
            CanonicalFrame(
                timestamp_s=0.1,
                poses={"arm": pose},
                grippers={"arm": 1.0},
            ),
        ]
    )
    trajectory_path = tmp_path / "trajectory.json"
    trajectory_path.write_text(trajectory.model_dump_json(), encoding="utf-8")
    recipe = Recipe(
        recipe_id="fixture-replay",
        dataset_alias="fixture",
        input_sha256=sha256_bytes(trajectory_path.read_bytes()),
        robot_id="fixture",
        robot_asset_sha256="1" * 64,
        backend_name="pink",
        backend_version="4.3.0",
        solve_options=SolveOptions(max_iterations=20),
        random_seed=7,
        split_sha256="2" * 64,
        thresholds={
            "position": Threshold(
                warn=0.005,
                fail=0.01,
                unit="m",
                source="fixture",
                provenance="fixture",
            )
        },
    )
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(recipe.model_dump_json(), encoding="utf-8")
    target = map_target_grippers(
        trajectory,
        _profile(),
        {"arm": "arm"},
    )
    target_path = tmp_path / "target-grippers.json"
    write_target_gripper_trajectory(target_path, target)
    solve_path = tmp_path / "solve.json"
    solve_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "robot_id": "fixture",
                "recipe_sha256": recipe_sha256(recipe),
                "backend_name": "pink",
                "backend_version": "4.3.0",
                "group": "arm",
                "frame_count": 2,
                "results": [{"status": "CONVERGED"}, {"status": "CONVERGED"}],
            }
        ),
        encoding="utf-8",
    )
    return trajectory_path, profile_path, recipe_path, solve_path, target_path


def test_replay_manifest_cross_checks_all_inputs_and_is_value_free(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)

    manifest = build_target_replay_manifest(
        replay_id="fixture-replay",
        trajectory_path=paths[0],
        profile_path=paths[1],
        recipe_path=paths[2],
        arm_solve_path=paths[3],
        target_grippers_path=paths[4],
        coupling="independent",
    )
    output = tmp_path / "replay-manifest.json"
    write_target_replay_manifest(output, manifest)
    text = output.read_text(encoding="utf-8")

    assert manifest.status == "READY"
    assert manifest.frame_count == 2
    assert len(manifest.artifacts) == 5  # the manifest carries paths and hashes only
    assert "poses" not in text
    assert "results" not in text
    with pytest.raises(FileExistsError):
        write_target_replay_manifest(output, manifest)


def test_replay_manifest_cli_writes_bound_artifact(tmp_path: Path, capsys) -> None:
    paths = _write_inputs(tmp_path)
    output = tmp_path / "replay-manifest.json"

    assert (
        app(
            [
                "build-replay-manifest",
                "--replay-id",
                "fixture-replay",
                "--trajectory",
                str(paths[0]),
                "--profile",
                str(paths[1]),
                "--recipe",
                str(paths[2]),
                "--arm-solve",
                str(paths[3]),
                "--target-grippers",
                str(paths[4]),
                "--coupling",
                "independent",
                "--output",
                str(output),
                "--json",
            ]
        )
        == EXIT_OK
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "READY"
    assert payload["frame_count"] == 2
    assert payload["artifact_roles"] == [
        "canonical_trajectory",
        "robot_profile",
        "recipe",
        "arm_solve",
        "target_grippers",
    ]
