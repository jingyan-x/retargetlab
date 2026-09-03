import json
from pathlib import Path

import pytest

from retargetlab.cli.main import EXIT_SEMANTIC, app
from retargetlab.contracts import (
    AffineMap,
    ColumnRef,
    DataProfile,
    DatasetCoverage,
    DatasetRevision,
    ExportInputGate,
    ExportProfile,
    GripperProfile,
    MappingSpec,
    ProfileChannel,
    ReviewDecisionArtifact,
    StreamMapping,
    TargetReplayArtifactVerification,
    TargetVectorLayout,
    TimingEvidence,
)
from retargetlab.run import build_export_input_gate, write_export_input_gate
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes


def _mapping() -> MappingSpec:
    return MappingSpec(
        dataset_alias="fixture",
        source_revision="v1",
        coordinate_frame="dataset_native",
        timestamp=ColumnRef(source="timestamp", expected_shape=(), unit="s"),
        streams=(
            StreamMapping(
                name="observation.state.slot_0",
                role="robot_state",
                fields={
                    "position": ColumnRef(
                        source="observation.state",
                        expected_shape=(16,),
                        indices=(5, 6, 7),
                        unit="m",
                        frame="dataset_native",
                    ),
                    "orientation": ColumnRef(
                        source="observation.state",
                        expected_shape=(16,),
                        indices=(1, 2, 3, 4),
                        frame="dataset_native",
                        quaternion_order="wxyz",
                    ),
                },
            ),
        ),
        metadata={"candidate_status": "APPROVED"},
    )


def _gripper(slot: str) -> GripperProfile:
    offset = 0 if slot == "slot_0" else 8
    reference_offset = 7 if slot == "slot_0" else 15
    return GripperProfile(
        slot=slot,
        observation_state=ProfileChannel(
            stream="observation.state",
            index=offset,
            semantics="joint_angle",
            unit="rad",
        ),
        action=ProfileChannel(
            stream="action",
            index=offset,
            semantics="normalized_open",
            unit="unitless",
        ),
        reference_observation_state=ProfileChannel(
            stream="observation.state.position",
            index=reference_offset,
            semantics="joint_angle",
            unit="rad",
        ),
        reference_action=ProfileChannel(
            stream="action.position",
            index=reference_offset,
            semantics="normalized_open",
            unit="unitless",
        ),
        observation_to_aperture=AffineMap(scale=0.2, offset=0.6),
        action_to_aperture=AffineMap(scale=1.0, offset=0.0),
    )


def _revision() -> DatasetRevision:
    return DatasetRevision(
        info_sha256="a" * 64,
        data_sha256="b" * 64,
        episodes_sha256="c" * 64,
        tasks_sha256="d" * 64,
        stats_sha256="e" * 64,
    )


def _coverage(revision: DatasetRevision, *, fully_verified: bool = True) -> DatasetCoverage:
    return DatasetCoverage(
        status="COMPLETE",
        dataset_alias="fixture",
        source_revision="v1",
        reader_version="lerobot==0.6.1",
        revision=revision,
        declared_total_episodes=1,
        declared_total_frames=2,
        declared_total_tasks=1,
        declared_total_chunks=1,
        observed_episode_count=1,
        observed_frame_count=2,
        data_row_count=2,
        observed_task_count=1,
        episode_ranges=(
            {
                "episode_index": 0,
                "start_row": 0,
                "end_row_exclusive": 2,
                "length": 2,
            },
        ),
        data_fields=("timestamp", "observation.state"),
        episode_fields=("episode_index",),
        task_fields=("task_index",),
        declared_features=("observation.state",),
        stats_features=("observation.state",),
        structure_compatible=True,
        structure_fully_verified=fully_verified,
        shape_unverified=() if fully_verified else ("observation.state",),
        coverage_complete=True,
        validation_scope="synthetic fixture",
    )


def _write_inputs(
    tmp_path: Path,
    *,
    profile_status: str = "CERTIFIED",
    fully_verified: bool = True,
) -> dict[str, Path]:
    revision = _revision()
    coverage = _coverage(revision, fully_verified=fully_verified)
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(coverage.model_dump_json(), encoding="utf-8")
    coverage_sha256 = sha256_bytes(canonical_json_bytes(coverage))
    mapping = _mapping()
    decision = ReviewDecisionArtifact(
        dataset_alias="fixture",
        source_revision="v1",
        candidate_sha256="f" * 64,
        review_sha256="0" * 64,
        checklist_sha256="1" * 64,
        comparison_sha256="2" * 64,
        approved_mapping_sha256=sha256_bytes(canonical_json_bytes(mapping)),
        reviewer="fixture-reviewer",
        review_evidence=("synthetic evidence",),
        coordinate_frame="dataset_native",
        shape_acceptance="ACCEPTED",
        target_group_by_slot={"slot_0": "left", "slot_1": "right"},
    )
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(decision.model_dump_json(), encoding="utf-8")
    data_profile = DataProfile(
        profile_id="fixture-profile",
        status=profile_status,
        dataset_alias="fixture",
        source_revision="v1",
        reader_version="lerobot==0.6.1",
        revision=revision,
        mapping=mapping,
        grippers=(_gripper("slot_0"), _gripper("slot_1")),
        timing=(
            TimingEvidence(
                group="arm",
                report_sha256="3" * 64,
                data_sha256=revision.data_sha256,
                joint_indices=(0, 1),
                action_scales=(1.0, 1.0),
                action_offsets=(0.0, 0.0),
                expected_shift_min=4,
                expected_shift_max=5,
                observed_best_shift=4,
                status="SUPPORTED",
            ),
        ),
        validation_scope="synthetic fixture",
        evidence_scope=("synthetic evidence",),
        coverage_sha256=coverage_sha256,
        review_decision_sha256=(
            sha256_bytes(canonical_json_bytes(decision)) if profile_status == "CERTIFIED" else None
        ),
    )
    profile_path = tmp_path / "data-profile.json"
    profile_path.write_text(data_profile.model_dump_json(), encoding="utf-8")
    export_profile = ExportProfile(
        robot_id="fixture-robot",
        robot_profile_sha256="4" * 64,
        target_layout=TargetVectorLayout(
            group_names=("arm",),
            names=("joint1",),
            units=("rad",),
        ),
        normalization_exclude=("valid.retarget",),
    )
    export_profile_path = tmp_path / "export-profile.json"
    export_profile_path.write_text(export_profile.model_dump_json(), encoding="utf-8")
    target_replay_path = tmp_path / "target-replay.json"
    target_replay_path.write_text("{}", encoding="utf-8")
    return {
        "profile": profile_path,
        "decision": decision_path,
        "coverage": coverage_path,
        "target_replay": target_replay_path,
        "export_profile": export_profile_path,
    }


def test_export_input_gate_binds_certified_source_and_target_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    paths = _write_inputs(tmp_path)
    export_profile = ExportProfile.model_validate_json(
        paths["export_profile"].read_text(encoding="utf-8")
    )
    export_profile_hash = sha256_bytes(canonical_json_bytes(export_profile))
    monkeypatch.setattr(
        "retargetlab.run.export_gate.verify_target_replay_trajectory",
        lambda path: TargetReplayArtifactVerification(
            replay_id="fixture-replay",
            robot_id="fixture-robot",
            frame_count=2,
            artifact_sha256="5" * 64,
            replay_manifest_sha256="6" * 64,
            export_profile_sha256=export_profile_hash,
        ),
    )

    gate = build_export_input_gate(
        data_profile_path=paths["profile"],
        decision_path=paths["decision"],
        coverage_path=paths["coverage"],
        target_replay_path=paths["target_replay"],
        export_profile_path=paths["export_profile"],
        training_episode_allowlist=(0,),
    )
    output = tmp_path / "export-input-gate.json"
    write_export_input_gate(output, gate)

    assert gate.status == "READY"
    assert gate.dataset_alias == "fixture"
    assert gate.training_episode_allowlist == (0,)
    assert gate.normalization_exclude == ("valid.retarget",)
    assert json.loads(output.read_text(encoding="utf-8"))["artifact_type"] == ("export_input_gate")
    assert ExportInputGate.model_validate_json(output.read_text(encoding="utf-8")) == gate


def test_export_input_gate_blocks_pending_profile_before_source_use(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, profile_status="REVIEW_REQUIRED")

    with pytest.raises(ValueError, match="decision file supplied|CERTIFIED"):
        build_export_input_gate(
            data_profile_path=paths["profile"],
            decision_path=paths["decision"],
            coverage_path=paths["coverage"],
            target_replay_path=paths["target_replay"],
            export_profile_path=paths["export_profile"],
            training_episode_allowlist=(0,),
        )


def test_export_input_gate_blocks_unverified_source_shape(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, fully_verified=False)

    with pytest.raises(ValueError, match="fully verified source structure"):
        build_export_input_gate(
            data_profile_path=paths["profile"],
            decision_path=paths["decision"],
            coverage_path=paths["coverage"],
            target_replay_path=paths["target_replay"],
            export_profile_path=paths["export_profile"],
            training_episode_allowlist=(0,),
        )


def test_verify_export_inputs_cli_reports_pending_profile(tmp_path: Path, capsys) -> None:
    paths = _write_inputs(tmp_path, profile_status="REVIEW_REQUIRED")
    output = tmp_path / "export-input-gate.json"

    assert (
        app(
            [
                "verify-export-inputs",
                "--data-profile",
                str(paths["profile"]),
                "--decision",
                str(paths["decision"]),
                "--coverage",
                str(paths["coverage"]),
                "--target-replay",
                str(paths["target_replay"]),
                "--export-profile",
                str(paths["export_profile"]),
                "--episode-indices",
                "0",
                "--output",
                str(output),
                "--json",
            ]
        )
        == EXIT_SEMANTIC
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "INVALID_INPUT"
    assert not output.exists()
