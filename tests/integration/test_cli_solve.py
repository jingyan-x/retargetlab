import json

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
    Threshold,
)
from retargetlab.run import recipe_sha256
from retargetlab.run.fingerprint import sha256_bytes

FIXTURE_URDF = """<?xml version="1.0"?>
<robot name="fixture">
  <link name="base"/>
  <link name="link1"/>
  <link name="tool"/>
  <joint name="joint1" type="revolute">
    <parent link="base"/>
    <child link="link1"/>
    <axis xyz="0 0 1"/>
    <limit lower="-3.14" upper="3.14" effort="10" velocity="10"/>
  </joint>
  <joint name="joint2" type="revolute">
    <parent link="link1"/>
    <child link="tool"/>
    <origin xyz="1 0 0"/>
    <axis xyz="0 0 1"/>
    <limit lower="-3.14" upper="3.14" effort="10" velocity="10"/>
  </joint>
</robot>
"""


def test_solve_cli_binds_recipe_hash_and_writes_results(tmp_path, capsys) -> None:
    pytest.importorskip("pinocchio")
    pytest.importorskip("pink")
    asset_dir = tmp_path / "asset"
    asset_dir.mkdir()
    (asset_dir / "fixture.urdf").write_text(FIXTURE_URDF, encoding="utf-8")
    profile = RobotProfile(
        robot_id="cli-fixture",
        asset_dir=str(asset_dir),
        urdf_path="fixture.urdf",
        urdf_sha256="0" * 64,
        groups=(
            KinematicGroup(
                name="arm",
                joint_names=("joint1", "joint2"),
                end_effector_frame="tool",
            ),
        ),
    )
    trajectory = CanonicalTrajectory(
        coordinate_frame="base",
        frames=[
            CanonicalFrame(
                timestamp_s=0.0,
                poses={
                    "arm": Pose(
                        position_m=(1.0, 0.0, 0.0),
                        quaternion_wxyz=(1.0, 0.0, 0.0, 0.0),
                        frame="base",
                    )
                },
            )
        ],
    )
    trajectory_path = tmp_path / "trajectory.json"
    trajectory_path.write_text(trajectory.model_dump_json(), encoding="utf-8")
    recipe = Recipe(
        recipe_id="cli-solve-fixture",
        dataset_alias="synthetic-fixture",
        input_sha256=sha256_bytes(trajectory_path.read_bytes()),
        robot_id=profile.robot_id,
        robot_asset_sha256="1" * 64,
        backend_name="pink",
        backend_version="4.3.0",
        solve_options=SolveOptions(max_iterations=20),
        random_seed=7,
        split_sha256="2" * 64,
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
    profile_path = tmp_path / "profile.json"
    recipe_path = tmp_path / "recipe.json"
    output_path = tmp_path / "solutions.json"
    profile_path.write_text(profile.model_dump_json(), encoding="utf-8")
    recipe_path.write_text(recipe.model_dump_json(), encoding="utf-8")

    assert (
        app(
            [
                "solve",
                "--trajectory",
                str(trajectory_path),
                "--profile",
                str(profile_path),
                "--recipe",
                str(recipe_path),
                "--group",
                "arm",
                "--initial-q",
                "0.0",
                "0.0",
                "--output",
                str(output_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    summary = json.loads(capsys.readouterr().out)
    assert summary["converged_count"] == 1
    assert summary["recipe_sha256"] == recipe_sha256(recipe)
    result_payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert result_payload["results"][0]["status"] == "CONVERGED"
    assert len(result_payload["results"][0]["q"]) == 2

    trajectory_path.write_text(trajectory.model_dump_json(indent=2), encoding="utf-8")
    assert (
        app(
            [
                "solve",
                "--trajectory",
                str(trajectory_path),
                "--profile",
                str(profile_path),
                "--recipe",
                str(recipe_path),
                "--group",
                "arm",
                "--initial-q",
                "0.0",
                "0.0",
                "--output",
                str(tmp_path / "rejected.json"),
                "--json",
            ]
        )
        == EXIT_SEMANTIC
    )
    error = json.loads(capsys.readouterr().out)
    assert error["status"] == "INVALID_INPUT"
