"""Collision bounds must use Δq units, complete pairs and final native distances."""

import hashlib
import os
from pathlib import Path

import numpy as np
import pytest

from retargetlab.contracts import KinematicGroup, Pose, RobotProfile, SolveOptions
from retargetlab.kinematics.mink_backend import MinkBackend
from retargetlab.robot.mujoco_model import build_mujoco_model
from retargetlab.robot.native_collision import NativeCollisionGeometry, make_collision_limit

mink = pytest.importorskip("mink")
mujoco = pytest.importorskip("mujoco")


@pytest.fixture
def backend(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    inertial = (
        '<inertial><mass value="1"/>'
        '<inertia ixx="1" iyy="1" izz="1" ixy="0" ixz="0" iyz="0"/></inertial>'
    )
    sphere = '<collision><geometry><sphere radius="0.05"/></geometry></collision>'
    text = f"""<robot name="spheres"><link name="base"/>
    <link name="left">{inertial}{sphere}</link><link name="right">{inertial}{sphere}</link>
    <joint name="left_slide" type="prismatic"><parent link="base"/><child link="left"/>
    <axis xyz="1 0 0"/><limit lower="-1" upper="1" effort="10" velocity="10"/></joint>
    <joint name="right_slide" type="prismatic"><parent link="base"/><child link="right"/>
    <origin xyz=".3 0 0"/><axis xyz="1 0 0"/>
    <limit lower="-1" upper="1" effort="10" velocity="10"/></joint></robot>"""
    path = source / "spheres.urdf"
    path.write_text(text)
    profile = RobotProfile(
        robot_id="spheres",
        asset_dir=str(source),
        urdf_path=path.name,
        urdf_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        root_frame="base",
        groups=tuple(
            KinematicGroup(name=s, joint_names=(f"{s}_slide",), end_effector_frame=s)
            for s in ("left", "right")
        ),
    )
    model = tmp_path / "model"
    build_mujoco_model(profile, model)
    return MinkBackend(profile, model_dir=model, joint_names=("right_slide", "left_slide"))


def options(**changes):
    return SolveOptions(
        enable_self_collision_barrier=True,
        self_collision_min_distance_m=0.01,
        max_iterations=80,
        no_progress_window=8,
        qp_eps_abs=1e-9,
        qp_eps_rel=1e-9,
        **changes,
    )


def pose(x):
    return Pose(position_m=(x, 0, 0), quaternion_wxyz=(1, 0, 0, 0), frame="base")


def test_pinned_mink_upper_bound_is_normalized_to_displacement(backend):
    geometry = NativeCollisionGeometry(backend.engine, backend.profile)
    config = backend._configuration([0, 0])
    native = mink.CollisionAvoidanceLimit(
        backend.model,
        [([a], [b]) for a, b in geometry.pairs],
        minimum_distance_from_collisions=0.01,
        collision_detection_distance=0.5,
    )
    adapter = make_collision_limit(geometry, 0.01, 0.5)
    for dt in (0.01, 0.1):
        raw = native.compute_qp_inequalities(config, dt)
        fixed = adapter.compute_qp_inequalities(config, dt)
        np.testing.assert_allclose(raw.h, [0.85 * (0.2 - 0.01) / dt])
        np.testing.assert_allclose(fixed.h, [0.85 * (0.2 - 0.01)])
        np.testing.assert_allclose(fixed.G, raw.G)


def test_unreachable_target_stops_at_clearance_without_moving_inactive_arm(backend):
    result = backend.solve_targets_frame(
        {"left": pose(0.28)}, [0, 0], options(), previous_q=[0, 0], sample_dt_s=0.1, posture_cost=0
    )
    assert result.collision_clearance_ok
    assert result.collision_free
    assert result.minimum_distance_m >= 0.01 - 1e-8
    assert result.q[0] == 0
    assert result.q[1] <= 0.19 + 1e-8
    assert result.position_error_m > 0.08
    assert result.status.value != "CONVERGED"


def test_clear_pose_is_solved_and_all_interval_bounds_stay_in_force(backend):
    result = backend.solve_targets_frame(
        {"left": pose(0.05)},
        [0, 0],
        options(),
        previous_q=[0, 0],
        sample_dt_s=0.001,
        posture_cost=0,
    )
    assert max(np.abs(result.q)) <= 0.01 + 1e-12
    assert result.collision_clearance_ok
    assert result.position_error_m > 0.039
    close = backend.solve_targets_frame(
        {"left": pose(0.005)},
        [0, 0],
        options(),
        previous_q=[0, 0],
        sample_dt_s=0.01,
        posture_cost=0,
    )
    assert close.status.value == "CONVERGED"
    assert close.collision_clearance_ok


def test_initial_penetration_cannot_be_reported_as_converged_pose(backend):
    result = backend.solve_targets_frame({"left": pose(0.25)}, [0, 0.25], options(), posture_cost=0)
    assert result.position_error_m < 1e-8
    assert result.status.value == "COLLISION_VIOLATION"
    assert result.collision_free is False
    assert result.collision_clearance_ok is False
    assert result.minimum_distance_m >= -0.05 - 1e-8


def test_parent_child_pair_is_retained_when_srdf_does_not_exclude_it(tmp_path):
    xml = """<mujoco><worldbody><body name="base"><geom name="base_geom" type="sphere" size=".05"/>
    <body name="child" pos=".3 0 0"><joint name="j" type="slide" axis="1 0 0"/>
    <geom name="child_geom" type="sphere" size=".05"/></body></body></worldbody></mujoco>"""
    from types import SimpleNamespace

    model = mujoco.MjModel.from_xml_string(xml)
    engine = SimpleNamespace(
        model=model,
        metadata={
            "geometry_mapping": [
                {
                    "name": "base_geom",
                    "link": "base",
                    "kind": "collision",
                    "source_geometry_name": "base_0",
                },
                {
                    "name": "child_geom",
                    "link": "child",
                    "kind": "collision",
                    "source_geometry_name": "child_0",
                },
            ],
            "srdf_exclusions": [],
        },
    )
    geometry = NativeCollisionGeometry(engine, SimpleNamespace(collision=None))
    assert len(geometry.pairs) == 1
    native = mink.CollisionAvoidanceLimit(model, [(["base_geom"], ["child_geom"])])
    assert native.geom_id_pairs == []
    adapter = make_collision_limit(geometry, 0.001, 0.02)
    assert adapter.geom_id_pairs == list(geometry.pairs)


@pytest.mark.parametrize(
    "robot,env",
    [("openarm", "RETARGETLAB_MUJOCO_OPENARM_MODEL"), ("mq03", "RETARGETLAB_MUJOCO_MOQI_MODEL")],
)
def test_real_complete_pair_policy_matches_coal_reference(robot, env):
    value = os.environ.get(env)
    if not value:
        pytest.skip("actual derived model not configured")
    from retargetlab.robot.collision import PinocchioCollisionModel, canonical_pair, geometry_base
    from retargetlab.robot.mujoco_model import MujocoKinematics

    folder = Path(value)
    profile = RobotProfile.model_validate_json((folder / "source-profile.json").read_text())
    engine = MujocoKinematics(folder)
    native = NativeCollisionGeometry(engine, profile)
    coal = PinocchioCollisionModel(profile)
    expected = set()
    for pair in coal.geometry.collisionPairs:
        names = canonical_pair(
            coal.geometry.geometryObjects[pair.first].name,
            coal.geometry.geometryObjects[pair.second].name,
        )
        if canonical_pair(*(geometry_base(n) for n in names)) not in coal.allowed_contact_pairs:
            expected.add(names)
    assert set(native.source_pairs) == expected
    assert len(native.pairs) == (232 if robot == "openarm" else 296)
    assert set(make_collision_limit(native, 0.001, 0.02).geom_id_pairs) == set(native.pairs)
    backend = MinkBackend(profile, model_dir=folder)
    with pytest.raises(ValueError, match="budget must cover every"):
        backend.solve_targets_frame(
            {
                profile.groups[0].name: Pose(
                    position_m=(0, 0, 0), quaternion_wxyz=(1, 0, 0, 0), frame=profile.root_frame
                )
            },
            np.clip(np.zeros(backend.model.nq), backend.lower, backend.upper),
            options(),
        )


def test_refined_daqp_respects_inactive_joint_and_sample_interval(backend):
    result = backend.solve_targets_frame(
        {"left": pose(0.05)},
        [0, 0],
        options(
            qp_solver="daqp",
            self_collision_recovery_margin_m=1e-5,
            self_collision_refinement_steps=3,
        ),
        previous_q=[0, 0],
        sample_dt_s=0.001,
        posture_cost=0,
    )
    assert result.solver == "daqp"
    assert result.q[0] == 0
    assert result.q[1] <= 0.01 + 1e-10
    assert result.position_error_m > 0.039
    assert result.collision_clearance_ok


def test_recovery_restores_clearance_from_positive_margin_violation(backend):
    result = backend.solve_targets_frame(
        {"left": pose(0.190005)},
        [0, 0.190005],
        options(
            qp_solver="daqp",
            self_collision_recovery_margin_m=1e-5,
            self_collision_refinement_steps=3,
        ),
        posture_cost=0,
    )
    assert result.status.value == "CONVERGED"
    assert result.minimum_distance_m >= 0.01 - 1e-8
    assert result.q[1] < 0.190005
    assert result.q[0] == 0


def test_refinement_does_not_certify_existing_penetration(backend):
    result = backend.solve_targets_frame(
        {"left": pose(0.25)},
        [0, 0.25],
        options(
            qp_solver="daqp",
            self_collision_recovery_margin_m=1e-5,
            self_collision_refinement_steps=3,
        ),
        posture_cost=0,
    )
    assert result.status.value == "COLLISION_VIOLATION"
    assert result.collision_free is False
    assert result.collision_clearance_ok is False
    assert result.minimum_distance_m >= -0.05 - 1e-8


@pytest.mark.parametrize(
    "changes",
    [
        {"qp_solver": "daqp"},
        {"self_collision_recovery_margin_m": 1e-5},
        {"self_collision_refinement_steps": 3},
    ],
)
def test_pink_rejects_mink_only_options(changes):
    from retargetlab.kinematics.pink_backend import PinkBackend

    with pytest.raises(ValueError, match="registered only for Mink"):
        PinkBackend().solve_targets_frame({"left": pose(0)}, [0], options(**changes))


def test_real_rejected_contact_direction_can_be_refined_without_relaxing_velocity():
    value = os.environ.get("RETARGETLAB_NATIVE_COLLISION_BASELINE")
    if not value:
        pytest.skip("registered private failure baseline not configured")
    import json

    import pyarrow.parquet as pq

    from retargetlab.run.process import canonical_frame, load_config, select_rows

    folder = Path(value)
    config = load_config(folder / "processing-config.json")
    rows, fields, binding = select_rows(config)
    assert binding["held_out_read"] is False and binding["source_joint_columns_read"] is False
    assert (
        binding["selected_rows_sha256"]
        == json.loads((folder / "input-binding.json").read_text())["selected_rows_sha256"]
    )
    profile = RobotProfile.model_validate_json((folder / "robot-profile.json").read_text())
    names = json.loads((folder / "report.json").read_text())["joint_names"]
    saved = pq.read_table(folder / "trajectories.parquet").to_pylist()
    previous = next(
        r
        for r in saved
        if r["episode_index"] == 6 and r["stream"] == "action" and r["frame_index"] == 859
    )
    source = next(r for r in rows if r["episode_index"] == 6 and r["frame_index"] == 860)
    frame, _ = canonical_frame(config, profile, source, fields["action"])
    dt = frame.timestamp_s - previous["timestamp"]
    opts = config.solve_options.model_copy(
        update=dict(
            qp_solver="daqp",
            qp_eps_abs=1e-9,
            qp_max_iterations=20000,
            self_collision_recovery_margin_m=1e-5,
            self_collision_refinement_steps=0,
        )
    )
    b = MinkBackend(profile, model_dir=config.mujoco_model, joint_names=names)
    baseline = b.solve_targets_frame(
        frame.poses,
        previous["joint_positions"],
        opts,
        previous_q=previous["joint_positions"],
        sample_dt_s=dt,
    )
    refined = b.solve_targets_frame(
        frame.poses,
        previous["joint_positions"],
        opts.model_copy(update={"self_collision_refinement_steps": 3}),
        previous_q=previous["joint_positions"],
        sample_dt_s=dt,
    )
    assert baseline.position_error_m > 0.1
    assert refined.status.value == "CONVERGED"
    assert refined.position_error_m <= opts.position_tolerance_m
    assert refined.orientation_error_rad <= opts.orientation_tolerance_rad
    assert refined.collision_clearance_ok
    assert refined.minimum_distance_m >= opts.self_collision_min_distance_m - 1e-8
    ratio = np.max(np.abs(np.array(refined.q) - previous["joint_positions"]) / (dt * b.speed))
    assert ratio <= 1 + 1e-8


def test_export_clearance_checks_float32_values_and_bound_model(backend):
    from retargetlab.run.training_native_clearance import NativeExportClearance

    path = backend.engine.asset_dir
    digest = hashlib.sha256((path / "manifest.json").read_bytes()).hexdigest()
    spec = {"minimum_distance_m": 0.001, "numeric_epsilon_m": 0, "model_manifest_sha256": digest}
    config = {"mujoco_model": str(path)}
    binding = {"mujoco_model_manifest_sha256": digest}
    gate = NativeExportClearance(
        spec, config, binding, backend.profile, ["right_slide", "left_slide"]
    )
    q = np.array([0, 0.1989999999])
    assert gate.assess(q)["native_clearance_ok"]
    rounded = q.astype(np.float32).astype(float)
    assert not gate.assess(rounded)["native_clearance_ok"]
    assert gate.assess([0, 0])["native_clearance_ok"]
    with pytest.raises(ValueError, match="differs from policy or processing"):
        NativeExportClearance(
            spec,
            config,
            {"mujoco_model_manifest_sha256": "0" * 64},
            backend.profile,
            ["right_slide", "left_slide"],
        )


@pytest.mark.parametrize(
    "change",
    [
        {"minimum_distance_m": float("nan")},
        {"minimum_distance_m": -0.001},
        {"numeric_epsilon_m": 0.001},
        {"distance_clip_m": 0.0005},
    ],
)
def test_export_clearance_rejects_invalid_policy(change):
    from retargetlab.run.training_native_clearance import NativeClearancePolicy

    with pytest.raises(ValueError):
        NativeClearancePolicy.model_validate(
            {"minimum_distance_m": 0.001, "model_manifest_sha256": "a" * 64, **change}
        )
