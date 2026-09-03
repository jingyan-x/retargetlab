import json
from pathlib import Path

import pytest

from retargetlab.cli.main import EXIT_OK, EXIT_SEMANTIC, app
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
    verify_target_replay_manifest,
    write_robot_profile,
    write_target_gripper_trajectory,
    write_target_replay_manifest,
)
from retargetlab.run.fingerprint import recipe_sha256, sha256_bytes

SINGLE_FIXTURE_URDF = """<?xml version="1.0"?>
<robot name="fixture">
  <link name="world"/>
  <link name="tool"/>
  <link name="finger_link1"/>
  <joint name="joint1" type="revolute">
    <parent link="world"/>
    <child link="tool"/>
    <limit lower="-1.0" upper="1.0" effort="1.0" velocity="1.0"/>
  </joint>
  <joint name="finger_joint1" type="prismatic">
    <parent link="tool"/>
    <child link="finger_link1"/>
    <limit lower="0.0" upper="0.044" effort="1.0" velocity="1.0"/>
  </joint>
</robot>
"""

DUAL_FIXTURE_URDF = """<?xml version="1.0"?>
<robot name="dual-fixture">
  <link name="world"/>
  <link name="left_tool"/>
  <link name="left_finger_link1"/>
  <link name="right_tool"/>
  <link name="right_finger_link1"/>
  <joint name="left_joint1" type="revolute">
    <parent link="world"/>
    <child link="left_tool"/>
    <limit lower="-1.0" upper="1.0" effort="1.0" velocity="1.0"/>
  </joint>
  <joint name="left_finger_joint1" type="prismatic">
    <parent link="left_tool"/>
    <child link="left_finger_link1"/>
    <limit lower="0.0" upper="0.044" effort="1.0" velocity="1.0"/>
  </joint>
  <joint name="right_joint1" type="revolute">
    <parent link="world"/>
    <child link="right_tool"/>
    <limit lower="-1.0" upper="1.0" effort="1.0" velocity="1.0"/>
  </joint>
  <joint name="right_finger_joint1" type="prismatic">
    <parent link="right_tool"/>
    <child link="right_finger_link1"/>
    <limit lower="0.0" upper="0.044" effort="1.0" velocity="1.0"/>
  </joint>
</robot>
"""


def _write_fixture_urdf(asset_dir: Path, contents: str) -> None:
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "fixture.urdf").write_text(contents, encoding="utf-8")


def _profile(asset_dir: Path) -> RobotProfile:
    gripper = TargetGripperProfile(
        name="fixture_gripper",
        driver_joint_name="finger_joint1",
        driver_lower_m=0.0,
        driver_upper_m=0.044,
    )
    return RobotProfile(
        robot_id="fixture",
        asset_dir=str(asset_dir),
        urdf_path="fixture.urdf",
        urdf_sha256=sha256_bytes((asset_dir / "fixture.urdf").read_bytes()),
        root_frame="world",
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
    asset_dir = tmp_path / "assets" / "fixture"
    _write_fixture_urdf(asset_dir, SINGLE_FIXTURE_URDF)
    profile = _profile(asset_dir)
    profile_path = tmp_path / "profile.json"
    write_robot_profile(profile_path, profile)
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
        profile,
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


def _dual_profile(asset_dir: Path) -> RobotProfile:
    groups = []
    for side in ("left", "right"):
        gripper = TargetGripperProfile(
            name=f"{side}_gripper",
            driver_joint_name=f"{side}_finger_joint1",
            driver_lower_m=0.0,
            driver_upper_m=0.044,
        )
        groups.append(
            KinematicGroup(
                name=side,
                joint_names=(f"{side}_joint1",),
                end_effector_frame=f"{side}_tool",
                gripper_joint_names=gripper.joint_names,
                gripper=gripper,
            )
        )
    return RobotProfile(
        robot_id="dual-fixture",
        asset_dir=str(asset_dir),
        urdf_path="fixture.urdf",
        urdf_sha256=sha256_bytes((asset_dir / "fixture.urdf").read_bytes()),
        root_frame="world",
        groups=tuple(groups),
    )


def _write_dual_inputs(
    tmp_path: Path,
) -> tuple[Path, Path, Path, tuple[Path, Path], Path]:
    asset_dir = tmp_path / "assets" / "dual-fixture"
    _write_fixture_urdf(asset_dir, DUAL_FIXTURE_URDF)
    profile = _dual_profile(asset_dir)
    profile_path = tmp_path / "dual-profile.json"
    write_robot_profile(profile_path, profile)
    pose = Pose(
        position_m=(0.0, 0.0, 0.0),
        quaternion_wxyz=(1.0, 0.0, 0.0, 0.0),
    )
    trajectory = CanonicalTrajectory(
        frames=[
            CanonicalFrame(
                timestamp_s=0.0,
                poses={"left": pose, "right": pose},
                grippers={"left": 0.0, "right": 1.0},
            ),
            CanonicalFrame(
                timestamp_s=0.1,
                poses={"left": pose, "right": pose},
                grippers={"left": 0.5, "right": 0.25},
            ),
        ]
    )
    trajectory_path = tmp_path / "dual-trajectory.json"
    trajectory_path.write_text(trajectory.model_dump_json(), encoding="utf-8")
    recipe = Recipe(
        recipe_id="dual-fixture-replay",
        dataset_alias="dual-fixture",
        input_sha256=sha256_bytes(trajectory_path.read_bytes()),
        robot_id="dual-fixture",
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
    recipe_path = tmp_path / "dual-recipe.json"
    recipe_path.write_text(recipe.model_dump_json(), encoding="utf-8")
    target = map_target_grippers(trajectory, profile, {"left": "left", "right": "right"})
    target_path = tmp_path / "dual-target-grippers.json"
    write_target_gripper_trajectory(target_path, target)
    solve_paths: list[Path] = []
    for group in ("left", "right"):
        solve_path = tmp_path / f"dual-solve-{group}.json"
        solve_path.write_text(
            json.dumps(
                {
                    "schema_version": "0.1",
                    "robot_id": "dual-fixture",
                    "recipe_sha256": recipe_sha256(recipe),
                    "backend_name": "pink",
                    "backend_version": "4.3.0",
                    "group": group,
                    "frame_count": 2,
                    "results": [{"status": "CONVERGED"}, {"status": "CONVERGED"}],
                }
            ),
            encoding="utf-8",
        )
        solve_paths.append(solve_path)
    return trajectory_path, profile_path, recipe_path, (solve_paths[0], solve_paths[1]), target_path


def test_replay_manifest_cross_checks_all_inputs_and_is_value_free(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)

    manifest = build_target_replay_manifest(
        replay_id="fixture-replay",
        trajectory_path=paths[0],
        profile_path=paths[1],
        recipe_path=paths[2],
        arm_solve_paths=(paths[3],),
        target_grippers_path=paths[4],
        coupling="independent",
    )
    output = tmp_path / "replay-manifest.json"
    write_target_replay_manifest(output, manifest)
    text = output.read_text(encoding="utf-8")

    assert manifest.status == "READY"
    assert manifest.frame_count == 2
    assert manifest.arm_groups == ("arm",)
    assert len(manifest.artifacts) == 5  # the manifest carries paths and hashes only
    assert "poses" not in text
    assert "results" not in text
    verification = verify_target_replay_manifest(output)
    assert verification.status == "VERIFIED"
    assert verification.frame_count == 2
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

    assert (
        app(
            [
                "verify-replay-manifest",
                "--manifest",
                str(output),
                "--json",
            ]
        )
        == EXIT_OK
    )
    verification_payload = json.loads(capsys.readouterr().out)
    assert verification_payload["status"] == "VERIFIED"

    paths[3].write_text(
        paths[3].read_text(encoding="utf-8").replace('"frame_count": 2', '"frame_count": 1'),
        encoding="utf-8",
    )
    assert (
        app(
            [
                "verify-replay-manifest",
                "--manifest",
                str(output),
                "--json",
            ]
        )
        == EXIT_SEMANTIC
    )
    tamper_payload = json.loads(capsys.readouterr().out)
    assert tamper_payload["status"] == "INVALID_INPUT"


def test_replay_manifest_requires_and_binds_every_bimanual_arm_solve(
    tmp_path: Path, capsys
) -> None:
    paths = _write_dual_inputs(tmp_path)

    output = tmp_path / "dual-replay-manifest.json"
    assert (
        app(
            [
                "build-replay-manifest",
                "--replay-id",
                "dual-fixture-replay",
                "--trajectory",
                str(paths[0]),
                "--profile",
                str(paths[1]),
                "--recipe",
                str(paths[2]),
                "--arm-solve",
                str(paths[3][0]),
                "--arm-solve",
                str(paths[3][1]),
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
    assert payload["arm_groups"] == ["left", "right"]

    manifest = build_target_replay_manifest(
        replay_id="dual-fixture-replay",
        trajectory_path=paths[0],
        profile_path=paths[1],
        recipe_path=paths[2],
        arm_solve_paths=paths[3],
        target_grippers_path=paths[4],
        coupling="independent",
    )

    assert manifest.arm_groups == ("left", "right")
    assert len(manifest.arm_solve_sha256s) == 2
    assert [artifact.role for artifact in manifest.artifacts].count("arm_solve") == 2
    with pytest.raises(ValueError, match="cover every target robot group"):
        build_target_replay_manifest(
            replay_id="dual-fixture-replay",
            trajectory_path=paths[0],
            profile_path=paths[1],
            recipe_path=paths[2],
            arm_solve_paths=(paths[3][0],),
            target_grippers_path=paths[4],
            coupling="independent",
        )
