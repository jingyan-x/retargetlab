import json

import pytest

from retargetlab.contracts import (
    CalibrationRecipe,
    CalibrationReport,
    CalibrationSelection,
    ColumnRef,
    EpisodeRange,
    MappingSpec,
    ReviewRunArtifact,
    StreamMapping,
    StructureComparison,
)
from retargetlab.run import (
    canonical_json_bytes,
    write_calibration_run,
    write_review_run_artifact,
)
from retargetlab.run.fingerprint import sha256_bytes


def _mapping() -> MappingSpec:
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
            "reviewer": "test",
            "review_evidence": "fixture",
            "target_group.slot_0": "panda_2",
            "target_group.slot_1": "panda_1",
        },
    )


def _selection() -> CalibrationSelection:
    return CalibrationSelection(
        dataset_alias="fixture",
        source_revision="v1",
        data_sha256="a" * 64,
        episodes_sha256="b" * 64,
        frames_per_episode=2,
        episode_ranges=(EpisodeRange(episode_index=0, start_row=0, end_row_exclusive=2, length=2),),
        selected_row_indices=(0, 1),
        selected_frame_count=2,
    )


def _comparison() -> StructureComparison:
    return StructureComparison(
        compatible=True,
        fully_verified=True,
        alias_match=True,
        revision_match=True,
        row_count_match=True,
        declared_total_frames=2,
        observed_row_count=2,
    )


def test_review_artifact_is_exclusive_and_contains_no_trajectory_arrays(tmp_path) -> None:
    path = tmp_path / "review" / "artifact.json"
    report = CalibrationReport(
        frame_count=2,
        max_frames=60,
        stream_names=("left",),
        structure_status="FULLY_VERIFIED",
    )

    artifact = write_review_run_artifact(
        path,
        mapping=_mapping(),
        comparison=_comparison(),
        review_sha256="c" * 64,
        selection=_selection(),
        calibration=report,
    )

    assert isinstance(artifact, ReviewRunArtifact)
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert payload["calibration"]["frame_count"] == 2
    assert "position_m" not in text
    assert "quaternion_wxyz" not in text
    assert "poses" not in text
    with pytest.raises(FileExistsError):
        write_review_run_artifact(
            path,
            mapping=_mapping(),
            comparison=_comparison(),
            review_sha256="c" * 64,
            selection=_selection(),
            calibration=report,
        )


def test_calibration_run_writes_recipe_and_manifest_without_source_rows(tmp_path) -> None:
    output_path = tmp_path / "run" / "calibration-audit.json"
    mapping = _mapping()
    comparison = _comparison()
    selection = _selection()
    report = CalibrationReport(
        frame_count=2,
        max_frames=2,
        stream_names=("left",),
        structure_status="FULLY_VERIFIED",
    )
    review_sha256 = "c" * 64
    recipe = CalibrationRecipe(
        recipe_id="calibration-fixture",
        dataset_alias="fixture",
        source_revision="v1",
        data_sha256=selection.data_sha256,
        episodes_sha256=selection.episodes_sha256,
        mapping_sha256=sha256_bytes(canonical_json_bytes(mapping)),
        comparison_sha256=sha256_bytes(canonical_json_bytes(comparison)),
        review_sha256=review_sha256,
        episode_indices=(0,),
        frames_per_episode=2,
        max_frames=2,
        columns=("episode_index", "frame_index", "index"),
    )

    manifest = write_calibration_run(
        output_path,
        recipe=recipe,
        mapping=mapping,
        comparison=comparison,
        review_sha256=review_sha256,
        selection=selection,
        calibration=report,
    )

    recipe_path = output_path.with_name("calibration-recipe.json")
    digest_path = output_path.with_name("calibration-recipe.sha256")
    manifest_path = output_path.with_name("calibration-run-manifest.json")
    assert manifest.recipe_sha256 == digest_path.read_text(encoding="utf-8").strip()
    assert manifest_path.is_file()
    assert set(manifest.artifacts) == {
        output_path.name,
        recipe_path.name,
        digest_path.name,
        manifest_path.name,
    }
    for path in (output_path, recipe_path, manifest_path):
        assert "position_m" not in path.read_text(encoding="utf-8")
        assert "poses" not in path.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_calibration_run(
            output_path,
            recipe=recipe,
            mapping=mapping,
            comparison=comparison,
            review_sha256=review_sha256,
            selection=selection,
            calibration=report,
        )
