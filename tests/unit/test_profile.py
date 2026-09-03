import json

import pytest

from retargetlab.cli.main import EXIT_OK, app
from retargetlab.contracts import (
    AffineMap,
    ColumnRef,
    DataProfile,
    DatasetRevision,
    GripperProfile,
    MappingSpec,
    ProfileChannel,
    ReviewDecisionArtifact,
    StreamMapping,
    TimingEvidence,
)
from retargetlab.run import canonical_json_bytes, verify_data_profile, write_data_profile
from retargetlab.run.fingerprint import sha256_bytes


def _mapping(*, approved: bool = False) -> MappingSpec:
    frame = "dataset_native" if approved else "UNRESOLVED"
    return MappingSpec(
        dataset_alias="fixture",
        source_revision="v1",
        coordinate_frame=frame,
        timestamp=ColumnRef(source="timestamp", expected_shape=()),
        streams=(
            StreamMapping(
                name="observation.state.slot_0",
                role="robot_state",
                fields={
                    "position": ColumnRef(
                        source="observation.state",
                        expected_shape=(16,),
                        indices=(5, 6, 7),
                        unit="m" if approved else None,
                        frame=frame if approved else None,
                    ),
                    "orientation": ColumnRef(
                        source="observation.state",
                        expected_shape=(16,),
                        indices=(1, 2, 3, 4),
                        quaternion_order="wxyz",
                        frame=frame if approved else None,
                    ),
                },
            ),
        ),
        metadata={"candidate_status": "APPROVED" if approved else "REVIEW_REQUIRED"},
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


def _timing(group: str, data_sha256: str) -> TimingEvidence:
    return TimingEvidence(
        group=group,
        report_sha256="b" * 64,
        data_sha256=data_sha256,
        joint_indices=(0, 1),
        action_scales=(1.0, 1.0),
        action_offsets=(0.0, 0.0),
        expected_shift_min=4,
        expected_shift_max=5,
        observed_best_shift=4,
        status="SUPPORTED",
    )


def _profile(
    *,
    status: str = "REVIEW_REQUIRED",
    review_decision_sha256: str | None = None,
) -> DataProfile:
    data_sha256 = "c" * 64
    mapping = _mapping(approved=status == "CERTIFIED")
    return DataProfile(
        profile_id="fixture-profile",
        status=status,
        dataset_alias="fixture",
        source_revision="v1",
        reader_version="lerobot==0.6.1",
        revision=DatasetRevision(
            info_sha256="a" * 64,
            data_sha256=data_sha256,
            episodes_sha256="d" * 64,
            tasks_sha256="e" * 64,
            stats_sha256="f" * 64,
        ),
        mapping=mapping,
        grippers=(_gripper("slot_0"), _gripper("slot_1")),
        timing=(_timing("arm", data_sha256),),
        validation_scope="synthetic fixture",
        evidence_scope=("synthetic timing report",),
        limitations=("frame semantics pending",),
        review_decision_sha256=review_decision_sha256,
    )


def test_data_profile_binds_revision_and_source_semantics(tmp_path) -> None:
    path = tmp_path / "data-profile.json"
    profile = _profile()

    written = write_data_profile(path, profile)

    assert written == profile
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "REVIEW_REQUIRED"
    assert payload["grippers"][0]["observation_to_aperture"] == {
        "scale": 0.2,
        "offset": 0.6,
    }
    assert payload["timing"][0]["shift_policy"] == "none"
    with pytest.raises(FileExistsError):
        write_data_profile(path, profile)


def test_data_profile_does_not_allow_unreviewed_certification() -> None:
    with pytest.raises(ValueError, match="review decision hash"):
        _profile(status="CERTIFIED")

    data_sha256 = "c" * 64
    with pytest.raises(ValueError, match="timing evidence data hash"):
        DataProfile(
            profile_id="fixture-profile",
            dataset_alias="fixture",
            source_revision="v1",
            reader_version="lerobot==0.6.1",
            revision=DatasetRevision(
                info_sha256="a" * 64,
                data_sha256=data_sha256,
                episodes_sha256="d" * 64,
                tasks_sha256="e" * 64,
                stats_sha256="f" * 64,
            ),
            mapping=_mapping(),
            grippers=(_gripper("slot_0"), _gripper("slot_1")),
            timing=(_timing("arm", "0" * 64),),
            validation_scope="synthetic fixture",
            evidence_scope=("synthetic timing report",),
        )


def test_data_profile_verifier_cross_checks_approved_decision(tmp_path) -> None:
    approved_mapping = _mapping(approved=True)
    decision = ReviewDecisionArtifact(
        dataset_alias="fixture",
        source_revision="v1",
        candidate_sha256="a" * 64,
        review_sha256="b" * 64,
        checklist_sha256="c" * 64,
        comparison_sha256="d" * 64,
        approved_mapping_sha256=sha256_bytes(canonical_json_bytes(approved_mapping)),
        reviewer="fixture-reviewer",
        review_evidence=("synthetic evidence",),
        coordinate_frame="dataset_native",
        shape_acceptance="ACCEPTED",
        target_group_by_slot={"slot_0": "left", "slot_1": "right"},
    )
    decision_digest = sha256_bytes(canonical_json_bytes(decision))
    profile = _profile(status="CERTIFIED", review_decision_sha256=decision_digest)
    profile_path = tmp_path / "data-profile.json"
    decision_path = tmp_path / "decision.json"
    write_data_profile(profile_path, profile)
    decision_path.write_text(decision.model_dump_json(indent=2), encoding="utf-8")

    verification = verify_data_profile(profile_path, decision_path=decision_path)

    assert verification.profile_status == "CERTIFIED"
    assert verification.decision_verified is True
    assert verification.decision_sha256 == decision_digest


def test_verify_profile_cli_reports_pending_profile(tmp_path, capsys) -> None:
    profile_path = tmp_path / "data-profile.json"
    write_data_profile(profile_path, _profile())

    assert app(["verify-profile", "--profile", str(profile_path), "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)

    assert payload["command"] == "verify-profile"
    assert payload["profile_status"] == "REVIEW_REQUIRED"
    assert payload["decision_verified"] is False
