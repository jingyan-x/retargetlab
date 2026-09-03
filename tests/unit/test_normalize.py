import pytest

from retargetlab.contracts import ColumnRef, MappingSpec, StreamMapping
from retargetlab.io import NormalizationError, normalize_rows


def make_spec(*, frame: str = "dataset_native") -> MappingSpec:
    return MappingSpec(
        dataset_alias="synthetic-fixture",
        source_revision="v1",
        coordinate_frame=frame,
        timestamp=ColumnRef(source="time", expected_shape=()),
        streams=(
            StreamMapping(
                name="state",
                role="robot_state",
                fields={
                    "position": ColumnRef(
                        source="state_position",
                        expected_shape=(3,),
                        unit="m",
                        frame=frame,
                    ),
                    "orientation": ColumnRef(
                        source="state_orientation",
                        expected_shape=(4,),
                        unit="unitless",
                        frame=frame,
                        quaternion_order="wxyz",
                    ),
                },
            ),
        ),
    )


def test_normalize_rows_is_explicit_and_sign_continuous() -> None:
    trajectory = normalize_rows(
        [
            {
                "time": 0.0,
                "state_position": [0.0, 0.0, 0.2],
                "state_orientation": [1.0, 0.0, 0.0, 0.0],
            },
            {
                "time": 0.01,
                "state_position": [0.1, 0.0, 0.2],
                "state_orientation": [-1.0, 0.0, 0.0, 0.0],
            },
        ],
        make_spec(),
    )
    assert trajectory.frame_count == 2
    assert trajectory.frames[1].poses["state"].quaternion_wxyz == (
        1.0,
        0.0,
        0.0,
        0.0,
    )
    assert trajectory.metadata["normalizer"].endswith("v0.1")


def test_normalize_rows_rejects_implicit_or_unsupported_semantics() -> None:
    rows = [{"time": 0.0, "state_position": [0.0, 0.0, 0.0], "state_orientation": [1, 0, 0, 0]}]
    bad_frame = make_spec(frame="other")
    bad_frame = bad_frame.model_copy(
        update={
            "streams": (
                StreamMapping(
                    name="state",
                    role="robot_state",
                    fields={
                        "position": ColumnRef(
                            source="state_position",
                            expected_shape=(3,),
                            unit="m",
                            frame="wrong",
                        ),
                        "orientation": ColumnRef(
                            source="state_orientation",
                            expected_shape=(4,),
                            frame="other",
                            quaternion_order="wxyz",
                        ),
                    },
                ),
            )
        }
    )
    with pytest.raises(NormalizationError, match="coordinate frame"):
        normalize_rows(rows, bad_frame)

    with pytest.raises(NormalizationError, match="missing from row"):
        normalize_rows([{"time": 0.0}], make_spec())


def test_normalize_rows_rejects_nonmonotonic_timestamps() -> None:
    rows = [
        {"time": 0.1, "state_position": [0.0, 0.0, 0.0], "state_orientation": [1, 0, 0, 0]},
        {"time": 0.0, "state_position": [0.0, 0.0, 0.0], "state_orientation": [1, 0, 0, 0]},
    ]
    with pytest.raises(ValueError, match="strictly increasing"):
        normalize_rows(rows, make_spec())
