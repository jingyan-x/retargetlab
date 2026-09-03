import pytest
from pydantic import ValidationError

from retargetlab.contracts import (
    ColumnRef,
    MappingSpec,
    StreamMapping,
    StructureField,
    StructureManifest,
)
from retargetlab.io import validate_mapping


def make_spec() -> MappingSpec:
    return MappingSpec(
        dataset_alias="synthetic-fixture",
        source_revision="v1",
        coordinate_frame="dataset_native",
        timestamp=ColumnRef(source="timestamp", expected_shape=()),
        streams=(
            StreamMapping(
                name="observation.state",
                role="robot_state",
                fields={
                    "eef": ColumnRef(
                        source="observation.state",
                        expected_shape=(8,),
                        indices=tuple(range(8)),
                        unit="mixed",
                        frame="dataset_native",
                    )
                },
            ),
        ),
    )


def make_manifest() -> StructureManifest:
    return StructureManifest(
        dataset_alias="synthetic-fixture",
        source_revision="v1",
        row_count=4,
        fields={
            "timestamp": StructureField(dtype="float64", shape=()),
            "observation.state": StructureField(dtype="float32", shape=(8,)),
        },
    )


def test_explicit_mapping_matches_value_free_manifest() -> None:
    result = validate_mapping(make_spec(), make_manifest())
    assert result.valid is True
    assert result.missing_sources == ()


def test_mapping_reports_revision_shape_and_index_errors() -> None:
    spec = make_spec().model_copy(
        update={
            "source_revision": "v2",
            "streams": (
                StreamMapping(
                    name="observation.state",
                    role="robot_state",
                    fields={
                        "eef": ColumnRef(
                            source="observation.state",
                            expected_shape=(7,),
                            indices=tuple(range(9)),
                        )
                    },
                ),
            ),
        }
    )
    result = validate_mapping(spec, make_manifest())
    assert result.valid is False
    assert result.revision_match is False
    assert result.shape_mismatches
    assert result.index_errors


def test_mapping_contract_rejects_duplicate_indices_and_streams() -> None:
    with pytest.raises(ValidationError, match="indices must be unique"):
        ColumnRef(source="field", indices=(0, 0))
    with pytest.raises(ValidationError, match="stream names must be unique"):
        MappingSpec(
            dataset_alias="fixture",
            source_revision="v1",
            coordinate_frame="dataset_native",
            timestamp=ColumnRef(source="timestamp"),
            streams=(
                StreamMapping(
                    name="state",
                    role="robot_state",
                    fields={"x": ColumnRef(source="x")},
                ),
                StreamMapping(
                    name="state",
                    role="command",
                    fields={"x": ColumnRef(source="x")},
                ),
            ),
        )
