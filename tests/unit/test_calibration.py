import pytest

from retargetlab.contracts import (
    ColumnRef,
    MappingSpec,
    StreamMapping,
    StructureComparison,
)
from retargetlab.io import run_bounded_calibration


def _spec() -> MappingSpec:
    frame = "dataset_native"
    return MappingSpec(
        dataset_alias="fixture",
        source_revision="v1",
        coordinate_frame=frame,
        timestamp=ColumnRef(source="timestamp", expected_shape=(), unit="s"),
        streams=(
            StreamMapping(
                name="left",
                role="robot_state",
                fields={
                    "position": ColumnRef(
                        source="state",
                        expected_shape=(7,),
                        indices=(0, 1, 2),
                        unit="m",
                        frame=frame,
                    ),
                    "orientation": ColumnRef(
                        source="state",
                        expected_shape=(7,),
                        indices=(3, 4, 5, 6),
                        frame=frame,
                        quaternion_order="wxyz",
                    ),
                },
            ),
        ),
        metadata={
            "candidate_status": "APPROVED",
            "accepted_unverified_shape": "false",
            "reviewer": "test",
            "review_evidence": "fixture",
            "target_group.slot_0": "panda_2",
            "target_group.slot_1": "panda_1",
        },
    )


def _comparison(*, compatible: bool = True) -> StructureComparison:
    return StructureComparison(
        compatible=compatible,
        fully_verified=compatible,
        alias_match=compatible,
        revision_match=compatible,
        row_count_match=compatible,
        declared_total_frames=2,
        observed_row_count=2,
    )


def _rows() -> list[dict[str, object]]:
    return [
        {"timestamp": 0.0, "state": [0.0, 0.1, 0.2, 1.0, 0.0, 0.0, 0.0]},
        {"timestamp": 0.1, "state": [0.2, 0.3, 0.4, 1.0, 0.0, 0.0, 0.0]},
    ]


def test_bounded_calibration_requires_approval_and_returns_value_free_report() -> None:
    trajectory, report = run_bounded_calibration(_rows(), _spec(), _comparison())

    assert trajectory.frame_count == 2
    assert trajectory.frames[1].poses["left"].position_m == (0.2, 0.3, 0.4)
    assert report.status == "COMPLETED"
    assert report.frame_count == 2
    assert report.structure_status == "FULLY_VERIFIED"


def test_bounded_calibration_rejects_unapproved_or_oversized_slices() -> None:
    unapproved = _spec().model_copy(update={"metadata": {"candidate_status": "REVIEW_REQUIRED"}})
    with pytest.raises(ValueError, match="approved mapping"):
        run_bounded_calibration(_rows(), unapproved, _comparison())

    with pytest.raises(ValueError, match="limit is 1"):
        run_bounded_calibration(_rows(), _spec(), _comparison(), max_frames=1)


def test_bounded_calibration_requires_matching_structure_comparison() -> None:
    with pytest.raises(ValueError, match="does not match"):
        run_bounded_calibration(_rows(), _spec(), _comparison(compatible=False))
