import json
from pathlib import Path

import pytest
from test_export_table import _write_bundle, _write_source_table

from retargetlab.cli.main import EXIT_OK, EXIT_SEMANTIC, app
from retargetlab.contracts import (
    ExportInputGate,
    FeatureDeclaration,
    LeRobotEpisodeMetadata,
    LeRobotTaskMetadata,
)
from retargetlab.export import (
    verify_synthetic_target_table,
    write_synthetic_target_table,
)
from retargetlab.run import (
    build_lerobot_metadata_plan,
    build_lerobot_replay_binding_manifest,
    build_synthetic_table_write_report,
    verify_lerobot_metadata_plan,
    verify_lerobot_metadata_skeleton,
    verify_lerobot_partial_dataset,
    verify_lerobot_replay_binding_manifest,
    verify_target_replay_bundle,
    write_lerobot_metadata_plan,
    write_lerobot_metadata_skeleton,
    write_lerobot_partial_dataset,
    write_lerobot_partial_dataset_report,
    write_lerobot_replay_binding_manifest,
    write_synthetic_table_write_report,
)


def _write_gate(tmp_path: Path, bundle_path: Path, *, source_frame_count: int = 2) -> Path:
    bundle_verification = verify_target_replay_bundle(bundle_path)
    gate = ExportInputGate(
        dataset_alias="fixture",
        source_revision="v1",
        data_profile_sha256="a" * 64,
        coverage_sha256="b" * 64,
        target_replay_bundle_sha256=bundle_verification.bundle_sha256,
        export_profile_sha256=bundle_verification.export_profile_sha256,
        robot_id="fixture",
        source_frame_count=source_frame_count,
        target_replay_frame_count=2,
        training_episode_allowlist=(3,),
    )
    path = tmp_path / "export-input-gate.json"
    path.write_text(gate.model_dump_json(), encoding="utf-8")
    return path


def _features() -> dict[str, FeatureDeclaration]:
    return {
        "timestamp": FeatureDeclaration(dtype="float32", shape=()),
        "frame_index": FeatureDeclaration(dtype="int64", shape=()),
        "episode_index": FeatureDeclaration(dtype="int64", shape=()),
        "index": FeatureDeclaration(dtype="int64", shape=()),
        "task_index": FeatureDeclaration(dtype="int64", shape=()),
        "observation.state": FeatureDeclaration(
            dtype="float32",
            shape=(2,),
            names=("joint1", "finger_joint1"),
        ),
        "action": FeatureDeclaration(
            dtype="float32",
            shape=(2,),
            names=("joint1", "finger_joint1"),
        ),
        "valid.retarget": FeatureDeclaration(dtype="bool", shape=()),
    }


def _tasks() -> tuple[LeRobotTaskMetadata, ...]:
    return (LeRobotTaskMetadata(task_index=0, task="fixture task"),)


def _episodes() -> tuple[LeRobotEpisodeMetadata, ...]:
    return (
        LeRobotEpisodeMetadata(
            episode_index=3,
            length=2,
            dataset_from_index=0,
            dataset_to_index=2,
            task_indices=(0,),
            data_chunk_index=0,
            data_file_index=0,
        ),
    )


def _write_target_table_report(tmp_path: Path, bundle_path: Path) -> Path:
    source_path = tmp_path / "synthetic-source.parquet"
    target_path = tmp_path / "synthetic-target.parquet"
    report_path = tmp_path / "synthetic-write-report.json"
    _write_source_table(source_path)
    write_result = write_synthetic_target_table(
        source_path=source_path,
        target_replay_bundle_path=bundle_path,
        output_path=target_path,
    )
    verification = verify_synthetic_target_table(
        source_path=source_path,
        target_replay_bundle_path=bundle_path,
        output_path=target_path,
    )
    write_synthetic_table_write_report(
        report_path,
        build_synthetic_table_write_report(write=write_result, verification=verification),
    )
    return report_path


def test_lerobot_metadata_plan_binds_gate_profile_and_ranges(tmp_path: Path) -> None:
    bundle_path = _write_bundle(tmp_path)
    gate_path = _write_gate(tmp_path, bundle_path)
    export_profile_path = tmp_path / "export-profile.json"

    plan = build_lerobot_metadata_plan(
        export_input_gate_path=gate_path,
        export_profile_path=export_profile_path,
        fps=30.0,
        features=_features(),
        tasks=_tasks(),
        episodes=_episodes(),
    )
    path = tmp_path / "metadata-plan.json"
    write_lerobot_metadata_plan(path, plan)
    verification = verify_lerobot_metadata_plan(path)

    assert plan.codebase_version == "v3.0"
    assert plan.total_episodes == 1
    assert plan.total_frames == 2
    assert plan.training_episode_allowlist == (3,)
    assert plan.data_path_template.startswith("data/chunk-")
    assert plan.video_keys == ()
    assert verification.status == "VERIFIED"


def test_lerobot_metadata_plan_rejects_target_shape_mismatch(tmp_path: Path) -> None:
    bundle_path = _write_bundle(tmp_path)
    gate_path = _write_gate(tmp_path, bundle_path)
    features = _features()
    features["action"] = FeatureDeclaration(dtype="float32", shape=(3,))

    with pytest.raises(ValueError, match="target feature does not match"):
        build_lerobot_metadata_plan(
            export_input_gate_path=gate_path,
            export_profile_path=tmp_path / "export-profile.json",
            fps=30.0,
            features=features,
            tasks=_tasks(),
            episodes=_episodes(),
        )


def test_lerobot_metadata_plan_rejects_range_gap(tmp_path: Path) -> None:
    bundle_path = _write_bundle(tmp_path)
    gate_path = _write_gate(tmp_path, bundle_path)
    episode = LeRobotEpisodeMetadata(
        episode_index=3,
        length=2,
        dataset_from_index=1,
        dataset_to_index=3,
        task_indices=(0,),
        data_chunk_index=0,
        data_file_index=0,
    )

    with pytest.raises(ValueError, match="contiguous from zero"):
        build_lerobot_metadata_plan(
            export_input_gate_path=gate_path,
            export_profile_path=tmp_path / "export-profile.json",
            fps=30.0,
            features=_features(),
            tasks=_tasks(),
            episodes=(episode,),
        )


def test_lerobot_metadata_plan_rejects_missing_required_feature(tmp_path: Path) -> None:
    bundle_path = _write_bundle(tmp_path)
    gate_path = _write_gate(tmp_path, bundle_path)
    features = _features()
    del features["index"]

    with pytest.raises(ValueError, match="missing required features"):
        build_lerobot_metadata_plan(
            export_input_gate_path=gate_path,
            export_profile_path=tmp_path / "export-profile.json",
            fps=30.0,
            features=features,
            tasks=_tasks(),
            episodes=_episodes(),
        )


def test_lerobot_metadata_plan_rejects_unknown_episode_task(tmp_path: Path) -> None:
    bundle_path = _write_bundle(tmp_path)
    gate_path = _write_gate(tmp_path, bundle_path)
    episode = LeRobotEpisodeMetadata(
        episode_index=3,
        length=2,
        dataset_from_index=0,
        dataset_to_index=2,
        task_indices=(1,),
        data_chunk_index=0,
        data_file_index=0,
    )

    with pytest.raises(ValueError, match="unknown task index"):
        build_lerobot_metadata_plan(
            export_input_gate_path=gate_path,
            export_profile_path=tmp_path / "export-profile.json",
            fps=30.0,
            features=_features(),
            tasks=_tasks(),
            episodes=(episode,),
        )


def test_lerobot_metadata_plan_rejects_allowlist_drift(tmp_path: Path) -> None:
    bundle_path = _write_bundle(tmp_path)
    gate_path = _write_gate(tmp_path, bundle_path)
    episode = LeRobotEpisodeMetadata(
        episode_index=4,
        length=2,
        dataset_from_index=0,
        dataset_to_index=2,
        task_indices=(0,),
        data_chunk_index=0,
        data_file_index=0,
    )

    with pytest.raises(ValueError, match="must match the export gate episode allowlist"):
        build_lerobot_metadata_plan(
            export_input_gate_path=gate_path,
            export_profile_path=tmp_path / "export-profile.json",
            fps=30.0,
            features=_features(),
            tasks=_tasks(),
            episodes=(episode,),
        )


def test_lerobot_metadata_plan_cli_round_trip(tmp_path: Path, capsys) -> None:
    bundle_path = _write_bundle(tmp_path)
    gate_path = _write_gate(tmp_path, bundle_path)
    features_path = tmp_path / "features.json"
    tasks_path = tmp_path / "tasks.json"
    episodes_path = tmp_path / "episodes.json"
    plan_path = tmp_path / "metadata-plan.json"
    features_path.write_text(
        json.dumps({name: value.model_dump(mode="json") for name, value in _features().items()}),
        encoding="utf-8",
    )
    tasks_path.write_text(
        json.dumps([task.model_dump(mode="json") for task in _tasks()]),
        encoding="utf-8",
    )
    episodes_path.write_text(
        json.dumps([episode.model_dump(mode="json") for episode in _episodes()]),
        encoding="utf-8",
    )

    assert (
        app(
            [
                "build-lerobot-metadata-plan",
                "--export-input-gate",
                str(gate_path),
                "--export-profile",
                str(tmp_path / "export-profile.json"),
                "--fps",
                "30",
                "--features",
                str(features_path),
                "--tasks",
                str(tasks_path),
                "--episodes",
                str(episodes_path),
                "--output",
                str(plan_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["artifact_type"] == "lerobot_metadata_plan"

    assert (
        app(
            [
                "verify-lerobot-metadata-plan",
                "--plan",
                str(plan_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    assert json.loads(capsys.readouterr().out)["status"] == "VERIFIED"

    plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_payload["total_frames"] = 3
    plan_path.write_text(json.dumps(plan_payload), encoding="utf-8")
    assert (
        app(
            [
                "verify-lerobot-metadata-plan",
                "--plan",
                str(plan_path),
                "--json",
            ]
        )
        == EXIT_SEMANTIC
    )
    assert json.loads(capsys.readouterr().out)["status"] == "INVALID_INPUT"


def test_lerobot_replay_binding_manifest_binds_each_plan_episode(tmp_path: Path, capsys) -> None:
    bundle_path = _write_bundle(tmp_path)
    gate_path = _write_gate(tmp_path, bundle_path)
    plan = build_lerobot_metadata_plan(
        export_input_gate_path=gate_path,
        export_profile_path=tmp_path / "export-profile.json",
        fps=30.0,
        features=_features(),
        tasks=_tasks(),
        episodes=_episodes(),
    )
    plan_path = tmp_path / "metadata-plan.json"
    write_lerobot_metadata_plan(plan_path, plan)

    manifest = build_lerobot_replay_binding_manifest(
        plan_path=plan_path,
        target_replay_bundle_paths={3: bundle_path},
    )
    manifest_path = tmp_path / "replay-bindings.json"
    write_lerobot_replay_binding_manifest(manifest_path, manifest)
    verification = verify_lerobot_replay_binding_manifest(manifest_path)

    assert manifest.status == "READY"
    assert manifest.total_frames == 2
    assert manifest.bindings[0].episode_index == 3
    assert manifest.bindings[0].dataset_from_index == 0
    assert manifest.bindings[0].dataset_to_index == 2
    assert manifest.bindings[0].target_replay_bundle_path == bundle_path.resolve().as_posix()
    assert verification.status == "VERIFIED"
    assert verification.binding_count == 1
    with pytest.raises(ValueError, match="episode allowlist"):
        build_lerobot_replay_binding_manifest(
            plan_path=plan_path,
            target_replay_bundle_paths={4: bundle_path},
        )

    bundles_path = tmp_path / "bundles.json"
    cli_manifest_path = tmp_path / "cli-replay-bindings.json"
    bundles_path.write_text(json.dumps({"3": str(bundle_path)}), encoding="utf-8")
    assert (
        app(
            [
                "build-lerobot-replay-bindings",
                "--plan",
                str(plan_path),
                "--bundles",
                str(bundles_path),
                "--output",
                str(cli_manifest_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    assert json.loads(capsys.readouterr().out)["artifact_type"] == (
        "lerobot_replay_binding_manifest"
    )
    assert (
        app(
            [
                "verify-lerobot-replay-bindings",
                "--manifest",
                str(cli_manifest_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    assert json.loads(capsys.readouterr().out)["status"] == "VERIFIED"


def test_lerobot_metadata_skeleton_writes_only_verified_metadata(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    import pyarrow.parquet as parquet

    bundle_path = _write_bundle(tmp_path)
    gate_path = _write_gate(tmp_path, bundle_path)
    plan = build_lerobot_metadata_plan(
        export_input_gate_path=gate_path,
        export_profile_path=tmp_path / "export-profile.json",
        fps=30.0,
        features=_features(),
        tasks=_tasks(),
        episodes=_episodes(),
    )
    plan_path = tmp_path / "metadata-plan.json"
    write_lerobot_metadata_plan(plan_path, plan)
    output_root = tmp_path / "skeleton"

    manifest = write_lerobot_metadata_skeleton(
        plan_path=plan_path,
        output_root=output_root,
    )

    assert manifest.status == "PARTIAL"
    assert manifest.source_scope == "synthetic_public_only"
    assert manifest.written_files == (
        "meta/episodes/chunk-000/file-000.parquet",
        "meta/info.json",
        "meta/tasks.parquet",
    )
    assert manifest.omitted_components == (
        "data_shards",
        "video_shards",
        "meta/stats.json",
    )
    info = json.loads((output_root / "meta" / "info.json").read_text(encoding="utf-8"))
    assert info["dataset_name"] == "fixture"
    assert info["total_episodes"] == 1
    assert info["total_frames"] == 2
    assert info["total_videos"] == 0
    assert info["splits"] == {"train": "3:4"}
    assert info["retargetlab"]["status"] == "PARTIAL"
    assert info["retargetlab"]["training_episode_allowlist"] == [3]
    assert not (output_root / "data").exists()
    assert not (output_root / "videos").exists()
    assert not (output_root / "meta" / "stats.json").exists()

    task_table = parquet.read_table(output_root / "meta" / "tasks.parquet")
    assert task_table.column_names == ["task", "task_index"]
    assert task_table.to_pylist() == [{"task": "fixture task", "task_index": 0}]
    episode_table = parquet.read_table(
        output_root / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    )
    assert episode_table.to_pylist() == [
        {
            "episode_index": 3,
            "tasks": ["fixture task"],
            "length": 2,
            "dataset_from_index": 0,
            "dataset_to_index": 2,
            "data/chunk_index": 0,
            "data/file_index": 0,
        }
    ]

    verification = verify_lerobot_metadata_skeleton(
        plan_path=plan_path,
        output_root=output_root,
    )
    assert verification.status == "VERIFIED"
    assert verification.written_files == manifest.written_files
    assert verification.omitted_components == manifest.omitted_components


def test_lerobot_metadata_skeleton_cli_round_trip_and_tamper_detection(
    tmp_path: Path,
    capsys,
) -> None:
    pytest.importorskip("pyarrow")

    bundle_path = _write_bundle(tmp_path)
    gate_path = _write_gate(tmp_path, bundle_path)
    plan = build_lerobot_metadata_plan(
        export_input_gate_path=gate_path,
        export_profile_path=tmp_path / "export-profile.json",
        fps=30.0,
        features=_features(),
        tasks=_tasks(),
        episodes=_episodes(),
    )
    plan_path = tmp_path / "metadata-plan.json"
    write_lerobot_metadata_plan(plan_path, plan)
    output_root = tmp_path / "skeleton"
    report_path = tmp_path / "skeleton-report.json"

    assert (
        app(
            [
                "write-lerobot-metadata-skeleton",
                "--plan",
                str(plan_path),
                "--output-root",
                str(output_root),
                "--report",
                str(report_path),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["artifact_type"] == "lerobot_metadata_skeleton_write"
    assert payload["status"] == "PARTIAL"
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "PARTIAL"

    assert (
        app(
            [
                "verify-lerobot-metadata-skeleton",
                "--plan",
                str(plan_path),
                "--output-root",
                str(output_root),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "VERIFIED"

    info_path = output_root / "meta" / "info.json"
    info = json.loads(info_path.read_text(encoding="utf-8"))
    info["total_frames"] = 999
    info_path.write_text(json.dumps(info), encoding="utf-8")
    assert (
        app(
            [
                "verify-lerobot-metadata-skeleton",
                "--plan",
                str(plan_path),
                "--output-root",
                str(output_root),
                "--json",
            ]
        )
        == EXIT_SEMANTIC
    )
    assert json.loads(capsys.readouterr().out)["status"] == "INVALID_INPUT"


def test_lerobot_partial_dataset_binds_verified_target_table_to_data_shard(
    tmp_path: Path,
) -> None:
    pytest.importorskip("pyarrow")
    import pyarrow as pa
    import pyarrow.parquet as parquet

    bundle_path = _write_bundle(tmp_path)
    gate_path = _write_gate(tmp_path, bundle_path)
    plan = build_lerobot_metadata_plan(
        export_input_gate_path=gate_path,
        export_profile_path=tmp_path / "export-profile.json",
        fps=30.0,
        features=_features(),
        tasks=_tasks(),
        episodes=_episodes(),
    )
    plan_path = tmp_path / "metadata-plan.json"
    write_lerobot_metadata_plan(plan_path, plan)
    output_root = tmp_path / "dataset"
    write_lerobot_metadata_skeleton(plan_path=plan_path, output_root=output_root)
    target_report_path = _write_target_table_report(tmp_path, bundle_path)
    manifest_path = tmp_path / "partial-dataset-write.json"

    manifest = write_lerobot_partial_dataset(
        plan_path=plan_path,
        output_root=output_root,
        target_table_report_path=target_report_path,
    )
    write_lerobot_partial_dataset_report(manifest_path, manifest)

    assert manifest.status == "PARTIAL"
    assert manifest.target_table_report_path == target_report_path.resolve().as_posix()
    assert manifest.written_files == (
        "data/chunk-000/file-000.parquet",
        "meta/episodes/chunk-000/file-000.parquet",
        "meta/info.json",
        "meta/tasks.parquet",
    )
    assert manifest.omitted_components == ("video_shards", "meta/stats.json")
    info = json.loads((output_root / "meta" / "info.json").read_text(encoding="utf-8"))
    assert info["retargetlab"]["written_components"] == ["metadata", "data_shards"]
    assert info["retargetlab"]["omitted_components"] == ["video_shards", "meta/stats.json"]
    data_path = output_root / "data" / "chunk-000" / "file-000.parquet"
    data = parquet.read_table(data_path)
    assert data.num_rows == 2
    assert data.schema.field("timestamp").type == pa.float32()
    assert data.schema.field("action").type == pa.list_(pa.float32(), 2)
    assert data["episode_index"].to_pylist() == [3, 3]
    assert data["frame_index"].to_pylist() == [0, 1]
    assert data["valid.retarget"].to_pylist() == [True, True]
    assert not (output_root / "videos").exists()
    assert not (output_root / "meta" / "stats.json").exists()

    verification = verify_lerobot_partial_dataset(
        plan_path=plan_path,
        output_root=output_root,
        target_table_report_path=target_report_path,
    )
    assert verification.status == "VERIFIED"
    assert verification.written_files == manifest.written_files
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["status"] == "PARTIAL"


def test_lerobot_partial_dataset_cli_rejects_data_tamper(tmp_path: Path, capsys) -> None:
    pytest.importorskip("pyarrow")
    import pyarrow as pa
    import pyarrow.parquet as parquet

    bundle_path = _write_bundle(tmp_path)
    gate_path = _write_gate(tmp_path, bundle_path)
    plan = build_lerobot_metadata_plan(
        export_input_gate_path=gate_path,
        export_profile_path=tmp_path / "export-profile.json",
        fps=30.0,
        features=_features(),
        tasks=_tasks(),
        episodes=_episodes(),
    )
    plan_path = tmp_path / "metadata-plan.json"
    write_lerobot_metadata_plan(plan_path, plan)
    output_root = tmp_path / "dataset"
    write_lerobot_metadata_skeleton(plan_path=plan_path, output_root=output_root)
    target_report_path = _write_target_table_report(tmp_path, bundle_path)
    report_path = tmp_path / "partial-write-report.json"

    assert (
        app(
            [
                "write-lerobot-partial-dataset",
                "--plan",
                str(plan_path),
                "--output-root",
                str(output_root),
                "--target-table-report",
                str(target_report_path),
                "--report",
                str(report_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    assert json.loads(capsys.readouterr().out)["status"] == "PARTIAL"

    data_path = output_root / "data" / "chunk-000" / "file-000.parquet"
    data = parquet.read_table(data_path)
    tampered = data.set_column(
        data.column_names.index("action"),
        "action",
        pa.array([[9.0, 9.0], [9.0, 9.0]], type=pa.list_(pa.float32(), 2)),
    )
    parquet.write_table(tampered, data_path)
    assert (
        app(
            [
                "verify-lerobot-partial-dataset",
                "--plan",
                str(plan_path),
                "--output-root",
                str(output_root),
                "--target-table-report",
                str(target_report_path),
                "--json",
            ]
        )
        == EXIT_SEMANTIC
    )
    assert json.loads(capsys.readouterr().out)["status"] == "INVALID_INPUT"
