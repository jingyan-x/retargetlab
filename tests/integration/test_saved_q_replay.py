"""Saved-q replay preserves frame identity and refuses changed evidence."""

import hashlib

import pytest

pytest.importorskip("mujoco")

from retargetlab.contracts import KinematicGroup, RobotProfile
from retargetlab.replay.bundle import build, digest, quality_index, read, write
from retargetlab.replay.server import Replay
from retargetlab.robot.mujoco_model import build_mujoco_model
from retargetlab.run.process import ProcessingConfig, select_rows

pq = pytest.importorskip("pyarrow.parquet")
pa = pytest.importorskip("pyarrow")


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    from retargetlab.kinematics.mink_backend import MinkBackend
    from retargetlab.kinematics.pink_backend import PinkBackend

    def forbidden(*args, **kwargs):
        raise AssertionError("replay called IK")

    monkeypatch.setattr(PinkBackend, "solve_targets_frame", forbidden)
    monkeypatch.setattr(MinkBackend, "solve_targets_frame", forbidden)
    source = tmp_path / "assets"
    source.mkdir()
    inertia = (
        '<inertial><mass value="1"/>'
        '<inertia ixx="1" iyy="1" izz="1" ixy="0" ixz="0" iyz="0"/></inertial>'
    )
    visual = '<visual><geometry><box size="0.1 0.1 0.1"/></geometry></visual>'
    urdf = '<robot name="dual"><link name="base"/>'
    for side, y in (("left", 0.2), ("right", -0.2)):
        urdf += f'''<link name="{side}_tcp">{inertia}{visual}</link>
        <joint name="{side}_slide" type="prismatic"><parent link="base"/>
        <child link="{side}_tcp"/><origin xyz="0 {y} 0"/><axis xyz="1 0 0"/>
        <limit lower="-1" upper="1" effort="10" velocity="1"/></joint>'''
    urdf += "</robot>"
    path = source / "robot.urdf"
    path.write_text(urdf)
    profile = RobotProfile(
        robot_id="replay_fixture",
        asset_dir=str(source),
        urdf_path=path.name,
        urdf_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        root_frame="base",
        groups=tuple(
            KinematicGroup(name=s, joint_names=(f"{s}_slide",), end_effector_frame=f"{s}_tcp")
            for s in ("left", "right")
        ),
    )
    model = tmp_path / "model"
    build_mujoco_model(profile, model)
    dataset = tmp_path / "source"
    (dataset / "data").mkdir(parents=True)
    write(dataset / "manifest.json", {"fixture": True})
    rows, records = [], []
    for i in range(3):
        x = i * 0.02
        offset = 0.1 if i == 1 else 0
        eef = [x + offset, 0.2, 0, 1, 0, 0, 0, 0, -x, -0.2, 0, 1, 0, 0, 0, 0]
        rows.append(
            dict(
                episode_index=7,
                frame_index=i + 10,
                timestamp=i * 0.1,
                **{"observation.eef": eef, "action.eef": eef},
            )
        )
        for stream in ("observation.state", "action"):
            records.append(
                dict(
                    episode_index=7,
                    frame_index=i + 10,
                    timestamp=i * 0.1,
                    stream=stream,
                    joint_positions=[-x, x],
                    position_error_m=[offset, 0],
                    orientation_error_rad=[0, 0],
                    max_velocity_ratio=None if i == 0 else 0.2,
                    pose_ok=i != 1,
                    limits_ok=True,
                    kinematics_valid=i != 1,
                    collision_free=i != 2,
                    solver_status="CONVERGED",
                )
            )
    pq.write_table(pa.Table.from_pylist(rows), dataset / "data/eef.parquet")
    config = ProcessingConfig(
        dataset_alias="fixture",
        source_format="openarm_eef_sidecar",
        dataset=dataset,
        robot_asset=source,
        episode_indices=[7],
    )
    _, _, binding = select_rows(config)
    process = tmp_path / "process"
    process.mkdir()
    write(process / "processing-config.json", config.model_dump(mode="json"))
    write(process / "robot-profile.json", profile.model_dump(mode="json"))
    write(process / "input-binding.json", binding)
    write(process / "report.json", {"joint_names": ["right_slide", "left_slide"]})
    pq.write_table(pa.Table.from_pylist(records), process / "trajectories.parquet")
    write(process / "manifest.json", {"files": {p.name: digest(p) for p in process.iterdir()}})
    catalog = tmp_path / "config.json"
    write(catalog, [{"id": "test-pink", "processing_run": str(process), "model": str(model)}])
    return catalog, process, dataset, model


def test_real_fk_replay_preserves_order_identity_and_saved_flags(inputs, tmp_path):
    config, _, _, _ = inputs
    out = tmp_path / "bundle"
    result = build(config, out)
    assert result["stream_frames"] == 6
    replay = Replay(out)
    frames = replay.episode("test-pink", 7)["streams"]["observation.state"]["frames"]
    assert [r["frame_index"] for r in frames] == [10, 11, 12]
    assert frames[1]["q"] == [-0.02, 0.02]
    assert frames[1]["actuals"][0][:3] == pytest.approx([0.02, 0.2, 0])
    assert frames[1]["position_error_mm"] == [100, 0]
    assert frames[1]["kinematics_valid"] is False
    assert frames[2]["collision_free"] is False
    assert frames[2]["eligible"] is None
    with pytest.raises(ValueError, match="index out of range"):
        replay.frame("test-pink", 7, "observation.state", -1)
    with pytest.raises(ValueError, match="not in this replay"):
        replay.episode("test-pink", 8)
    with pytest.raises(ValueError, match="invalid camera"):
        replay.frame("test-pink", 7, "action", 0, zoom=float("nan"))
    path = out / "test-pink-7.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="fingerprint changed"):
        Replay(out)


def test_source_eef_change_is_rejected(inputs, tmp_path):
    config, _, source, _ = inputs
    path = source / "data/eef.parquet"
    rows = pq.read_table(path).to_pylist()
    rows[0]["observation.eef"][0] += 0.01
    pq.write_table(pa.Table.from_pylist(rows), path)
    with pytest.raises(ValueError, match="source binding changed"):
        build(config, tmp_path / "bundle")


def test_wrong_quality_processing_binding_is_rejected(inputs, tmp_path):
    _, process, _, _ = inputs
    quality = tmp_path / "quality"
    (quality / "retarget").mkdir(parents=True)
    write(quality / "retarget/plan.json", {"processing_manifest_sha256": "0" * 64})
    with pytest.raises(ValueError, match="another processing run"):
        quality_index(quality, process)


def test_changed_processing_diagnostic_is_rejected(inputs, tmp_path):
    config, process, _, _ = inputs
    report = process / "report.json"
    write(report, {"joint_names": ["left_slide", "right_slide"]})
    with pytest.raises(ValueError, match="fingerprint changed"):
        build(config, tmp_path / "bundle")


def test_wrong_saved_error_is_rejected_even_with_updated_manifest(inputs, tmp_path):
    config, process, _, _ = inputs
    path = process / "trajectories.parquet"
    rows = pq.read_table(path).to_pylist()
    rows[0]["position_error_m"] = [0.1, 0]
    pq.write_table(pa.Table.from_pylist(rows), path)
    manifest = read(process / "manifest.json")
    manifest["files"][path.name] = digest(path)
    write(process / "manifest.json", manifest)
    with pytest.raises(ValueError, match="FK mismatch"):
        build(config, tmp_path / "bundle")


def test_browser_motion_preserves_named_joint_order_and_world_geom_poses(
    inputs, tmp_path, monkeypatch
):
    import base64

    import mujoco
    import numpy as np

    def forbidden(*args, **kwargs):
        raise AssertionError("browser display attempted physical stepping")

    config, _, _, _ = inputs
    out = tmp_path / "browser-bundle"
    build(config, out)
    monkeypatch.setattr(mujoco, "mj_step", forbidden)
    monkeypatch.setattr(mujoco, "mj_forward", forbidden)
    replay = Replay(out)
    scene = replay.scene("test-pink")
    motion = replay.motion("test-pink", 7, "action")
    assert motion["model_sha256"] == scene["model_sha256"]
    poses = np.frombuffer(base64.b64decode(motion["poses"]), dtype="<f8").reshape(
        motion["frame_count"], motion["body_count"], 7
    )
    assert len(poses) == 3
    engine = replay.engines[replay.runs["test-pink"]["model"]]
    for index in range(3):
        for geom in scene["geoms"]:
            name = geom["name"]
            sign = 1 if "left" in name else -1
            p = poses[index, geom["body"], :3]
            assert p == pytest.approx([sign * index * 0.02, sign * 0.2, 0])
            assert engine.model.geom_group[geom["id"]] != 0
    with pytest.raises(ValueError, match="not in this replay"):
        replay.motion("test-pink", 123, "action")
    with pytest.raises(KeyError):
        replay.motion("test-pink", 7, "not-a-stream")
    replay.close()


def test_replay_config_paths_resolve_from_config_directory(inputs, tmp_path, monkeypatch):
    import os

    config, _, _, _ = inputs
    entries = read(config)
    for entry in entries:
        for key in ("processing_run", "model"):
            entry[key] = os.path.relpath(entry[key], config.parent)
    write(config, entries)
    unrelated = tmp_path / "another-cwd"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    result = build(config, tmp_path / "relative-bundle")
    assert result["stream_frames"] == 6
