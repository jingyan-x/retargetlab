import pytest

from retargetlab.contracts import (
    AffineMap,
    ColumnRef,
    GripperProfile,
    MappingSpec,
    ProfileChannel,
    StreamMapping,
)
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


def make_gripper() -> GripperProfile:
    return GripperProfile(
        slot="slot_0",
        observation_state=ProfileChannel(
            stream="observation.state",
            index=0,
            semantics="joint_angle",
            unit="rad",
        ),
        action=ProfileChannel(
            stream="action",
            index=0,
            semantics="normalized_open",
            unit="unitless",
        ),
        reference_observation_state=ProfileChannel(
            stream="observation.state.position",
            index=7,
            semantics="joint_angle",
            unit="rad",
        ),
        reference_action=ProfileChannel(
            stream="action.position",
            index=7,
            semantics="normalized_open",
            unit="unitless",
        ),
        observation_to_aperture=AffineMap(scale=0.2, offset=0.6),
        action_to_aperture=AffineMap(scale=1.0, offset=0.0),
    )


def make_eef_spec() -> MappingSpec:
    return MappingSpec(
        dataset_alias="synthetic-fixture",
        source_revision="v1",
        coordinate_frame="dataset_native",
        timestamp=ColumnRef(source="time", expected_shape=()),
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
            StreamMapping(
                name="action.slot_0",
                role="command",
                fields={
                    "position": ColumnRef(
                        source="action",
                        expected_shape=(16,),
                        indices=(5, 6, 7),
                        unit="m",
                        frame="dataset_native",
                    ),
                    "orientation": ColumnRef(
                        source="action",
                        expected_shape=(16,),
                        indices=(1, 2, 3, 4),
                        frame="dataset_native",
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


def test_normalize_rows_maps_profile_grippers_per_stream() -> None:
    state = [0.0] * 16
    state[0] = -0.5
    state[1] = 1.0
    state[5:8] = [0.0, 0.0, 0.2]
    action = [0.0] * 16
    action[0] = 0.75
    action[1] = 1.0
    action[5:8] = [0.1, 0.0, 0.2]

    trajectory = normalize_rows(
        [{"time": 0.0, "observation.state": state, "action": action}],
        make_eef_spec(),
        grippers=(make_gripper(),),
    )

    assert trajectory.frames[0].grippers == {
        "observation.state.slot_0": pytest.approx(0.5),
        "action.slot_0": pytest.approx(0.75),
    }
    assert trajectory.metadata["normalizer"].endswith("pose_and_gripper.v0.1")


def test_normalize_rows_rejects_profile_gripper_out_of_range() -> None:
    state = [0.0] * 16
    state[1] = 1.0
    state[5:8] = [0.0, 0.0, 0.2]
    action = [0.0] * 16
    action[0] = 1.1
    action[1] = 1.0
    action[5:8] = [0.1, 0.0, 0.2]

    with pytest.raises(NormalizationError, match=r"outside \[0, 1\]"):
        normalize_rows(
            [{"time": 0.0, "observation.state": state, "action": action}],
            make_eef_spec(),
            grippers=(make_gripper(),),
        )
