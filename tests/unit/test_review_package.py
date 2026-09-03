import json

import pytest

from retargetlab.contracts import (
    ColumnRef,
    MappingReview,
    MappingSpec,
    ReviewEvidenceChecklist,
    ReviewPackagePreflightArtifact,
    StreamMapping,
    StructureComparison,
)
from retargetlab.io import inspect_review_package
from retargetlab.run import write_review_package_preflight
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes


def _candidate() -> MappingSpec:
    return MappingSpec(
        dataset_alias="fixture",
        source_revision="v1",
        coordinate_frame="UNRESOLVED",
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
                    )
                },
            ),
        ),
        metadata={"candidate_status": "REVIEW_REQUIRED"},
    )


def _review(*, approved: bool, accept_unverified_shape: bool = False) -> MappingReview:
    return MappingReview(
        dataset_alias="fixture",
        source_revision="v1",
        coordinate_frame="dataset_native",
        position_unit="m",
        timestamp_unit="s",
        orientation_quaternion_order="wxyz",
        slot_labels={"slot_0": "left", "slot_1": "right"},
        target_group_by_slot={"slot_0": "panda_2", "slot_1": "panda_1"},
        evidence=("synthetic-review",),
        reviewer="test",
        accept_unverified_shape=accept_unverified_shape,
        approved=approved,
        checklist=ReviewEvidenceChecklist(
            structure_evidence_reviewed=True,
            coordinate_frame_confirmed=True,
            position_unit_confirmed=True,
            timestamp_unit_confirmed=True,
            orientation_order_confirmed=True,
            slot_labels_confirmed=True,
            target_groups_confirmed=True,
            shape_acceptance="ACCEPTED" if accept_unverified_shape else "NOT_REQUIRED",
        ),
    )


def _comparison(*, compatible: bool = True) -> StructureComparison:
    return StructureComparison(
        compatible=compatible,
        fully_verified=False,
        alias_match=compatible,
        revision_match=compatible,
        row_count_match=compatible,
        declared_total_frames=2,
        observed_row_count=2,
        shape_unverified=("observation.state",),
    )


def test_review_package_inspection_keeps_pending_and_approved_states_explicit() -> None:
    candidate = _candidate()
    pending = inspect_review_package(candidate, _review(approved=False), _comparison())

    assert pending.status == "PENDING_REVIEW"
    assert pending.next_action == "REVIEW_SEMANTICS"
    assert pending.ready_for_semantic_review is True
    assert pending.can_apply_review is False
    assert pending.shape_decision_required is True

    approved = inspect_review_package(
        candidate,
        _review(approved=True, accept_unverified_shape=True),
        _comparison(),
    )
    assert approved.status == "REVIEW_APPROVED"
    assert approved.next_action == "APPLY_APPROVED_REVIEW"
    assert approved.can_apply_review is True
    assert approved.blocking_reasons == ()

    blocked = inspect_review_package(
        candidate,
        _review(approved=False),
        _comparison(compatible=False),
    )
    assert blocked.status == "BLOCKED"
    assert blocked.next_action == "REPAIR_EVIDENCE"
    assert blocked.ready_for_semantic_review is False
    assert "structure comparison is incompatible" in blocked.blocking_reasons


def test_review_package_cli_reports_pending_without_promoting_candidate(tmp_path, capsys) -> None:
    from retargetlab.cli.main import EXIT_OK, EXIT_SEMANTIC, app

    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(
        json.dumps({"mapping": _candidate().model_dump(mode="json")}),
        encoding="utf-8",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(_review(approved=False).model_dump_json(), encoding="utf-8")
    comparison_path = tmp_path / "comparison.json"
    comparison_path.write_text(_comparison().model_dump_json(), encoding="utf-8")
    output_path = tmp_path / "preflight.json"

    assert (
        app(
            [
                "inspect-review-package",
                "--candidate",
                str(candidate_path),
                "--review",
                str(review_path),
                "--comparison",
                str(comparison_path),
                "--output",
                str(output_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "PENDING_REVIEW"
    assert payload["next_action"] == "REVIEW_SEMANTICS"
    assert payload["can_apply_review"] is False
    assert payload["output"] == str(output_path)
    assert "position_m" not in output_path.read_text(encoding="utf-8")
    assert "poses" not in output_path.read_text(encoding="utf-8")

    assert (
        app(
            [
                "verify-review-package",
                "--preflight",
                str(output_path),
                "--candidate",
                str(candidate_path),
                "--review",
                str(review_path),
                "--comparison",
                str(comparison_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    verification_payload = json.loads(capsys.readouterr().out)
    assert verification_payload["status"] == "VERIFIED"
    assert verification_payload["inspection_status"] == "PENDING_REVIEW"
    assert verification_payload["can_apply_review"] is False

    tampered = _candidate().model_copy(update={"metadata": {"candidate_status": "TAMPERED"}})
    candidate_path.write_text(
        json.dumps({"mapping": tampered.model_dump(mode="json")}),
        encoding="utf-8",
    )
    assert (
        app(
            [
                "verify-review-package",
                "--preflight",
                str(output_path),
                "--candidate",
                str(candidate_path),
                "--review",
                str(review_path),
                "--comparison",
                str(comparison_path),
                "--json",
            ]
        )
        == EXIT_SEMANTIC
    )
    tamper_payload = json.loads(capsys.readouterr().out)
    assert tamper_payload["status"] == "INVALID_INPUT"
    assert "candidate hash" in tamper_payload["error"]


def test_review_package_preflight_writer_is_exclusive_and_value_free(tmp_path) -> None:
    path = tmp_path / "review-package-preflight.json"
    candidate = _candidate()
    review = _review(approved=False)
    comparison = _comparison()

    artifact = write_review_package_preflight(
        path,
        candidate=candidate,
        review=review,
        comparison=comparison,
    )

    assert isinstance(artifact, ReviewPackagePreflightArtifact)
    assert artifact.inspection.status == "PENDING_REVIEW"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["candidate_sha256"] == sha256_bytes(canonical_json_bytes(candidate))
    assert "position_m" not in path.read_text(encoding="utf-8")
    assert "poses" not in path.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_review_package_preflight(
            path,
            candidate=candidate,
            review=review,
            comparison=comparison,
        )
