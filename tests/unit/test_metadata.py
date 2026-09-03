import json

from retargetlab.contracts import FeatureDeclaration, StructureField, StructureManifest
from retargetlab.io import compare_info_to_structure, probe_lerobot_info


def _write_info(path) -> None:
    path.write_text(
        json.dumps(
            {
                "dataset_name": "synthetic",
                "total_episodes": 1,
                "total_frames": 2,
                "total_tasks": 1,
                "total_chunks": 1,
                "fps": 30.0,
                "features": {
                    "state": {
                        "dtype": "float32",
                        "shape": [2],
                        "names": ["x", "y"],
                    },
                    "camera": {
                        "dtype": "video",
                        "shape": [4, 5, 3],
                        "names": ["height", "width", "channels"],
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def test_lerobot_info_probe_is_value_free(tmp_path) -> None:
    path = tmp_path / "info.json"
    _write_info(path)

    manifest = probe_lerobot_info(
        path,
        dataset_alias="fixture",
        source_revision="v1",
    )

    assert manifest.total_frames == 2
    assert manifest.features["state"].shape == (2,)
    assert manifest.features["camera"].storage == "external"
    assert manifest.source_sha256 is not None
    assert "values" not in repr(manifest)


def test_metadata_comparison_distinguishes_unknown_shape_from_conflict(tmp_path) -> None:
    info_path = tmp_path / "info.json"
    _write_info(info_path)
    info = probe_lerobot_info(
        info_path,
        dataset_alias="fixture",
        source_revision="v1",
    )
    structure = StructureManifest(
        dataset_alias="fixture",
        source_revision="v1",
        row_count=2,
        fields={
            "state": StructureField(dtype="float", shape=None),
            "timestamp": StructureField(dtype="float", shape=()),
        },
    )

    comparison = compare_info_to_structure(info, structure)

    assert comparison.compatible is True
    assert comparison.fully_verified is False
    assert comparison.shape_unverified == ("state",)
    assert comparison.extra_fields == ("timestamp",)

    scalar_info = info.model_copy(
        update={
            "features": {
                "scalar": FeatureDeclaration(dtype="float32", shape=(1,)),
            }
        }
    )
    scalar_structure = StructureManifest(
        dataset_alias="fixture",
        source_revision="v1",
        row_count=2,
        fields={"scalar": StructureField(dtype="float", shape=())},
    )
    scalar_comparison = compare_info_to_structure(scalar_info, scalar_structure)
    assert scalar_comparison.compatible is True
    assert scalar_comparison.fully_verified is False
    assert scalar_comparison.shape_normalized == ("scalar",)

    contradictory = structure.model_copy(
        update={"fields": {"state": StructureField(dtype="float", shape=(3,))}}
    )
    conflict = compare_info_to_structure(info, contradictory)
    assert conflict.compatible is False
    assert conflict.shape_mismatches == ("state: declared (2,), got (3,)",)
