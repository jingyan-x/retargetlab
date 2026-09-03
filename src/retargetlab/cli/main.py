"""Small, structured CLI surface for the M0 contracts."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, TextIO

from pydantic import ValidationError

from retargetlab import __version__
from retargetlab.contracts import (
    CalibrationRecipe,
    CanonicalTrajectory,
    DatasetReport,
    FeatureDeclaration,
    LeRobotEpisodeMetadata,
    LeRobotTaskMetadata,
    MappingReview,
    MappingSpec,
    Recipe,
    RobotProfile,
    StructureComparison,
    StructureManifest,
)
from retargetlab.export import (
    build_export_profile,
    verify_synthetic_target_table,
    write_synthetic_target_table,
)
from retargetlab.io import (
    DEFAULT_CALIBRATION_COLUMNS,
    analyze_command_timing,
    apply_mapping_review,
    build_pose_mapping_candidate,
    compare_info_to_structure,
    inspect_review_package,
    normalize_rows,
    probe_lerobot_info,
    probe_parquet,
    run_parquet_calibration,
    scan_lerobot_coverage,
    validate_mapping,
)
from retargetlab.robot.assets import sha256_file
from retargetlab.robot.openarm import load_openarm_bimanual_profile
from retargetlab.run import (
    build_export_input_gate,
    build_lerobot_metadata_plan,
    build_synthetic_table_write_preflight,
    build_synthetic_table_write_report,
    build_target_replay_bundle,
    build_target_replay_manifest,
    build_target_replay_trajectory,
    canonical_json_bytes,
    execute_solve_run,
    load_executable_data_profile,
    map_target_grippers,
    recipe_sha256,
    verify_calibration_run,
    verify_data_profile,
    verify_lerobot_metadata_plan,
    verify_lerobot_metadata_skeleton,
    verify_lerobot_partial_dataset,
    verify_review_decision_artifact,
    verify_review_package_preflight,
    verify_synthetic_table_write_preflight,
    verify_synthetic_table_write_report,
    verify_target_replay_bundle,
    verify_target_replay_manifest,
    verify_target_replay_trajectory,
    write_calibration_run,
    write_dataset_coverage,
    write_export_input_gate,
    write_export_profile,
    write_lerobot_metadata_plan,
    write_lerobot_metadata_skeleton,
    write_lerobot_metadata_skeleton_report,
    write_lerobot_partial_dataset,
    write_lerobot_partial_dataset_report,
    write_review_decision_artifact,
    write_review_package_preflight,
    write_robot_profile,
    write_synthetic_table_write_preflight,
    write_synthetic_table_write_report,
    write_target_gripper_trajectory,
    write_target_replay_bundle,
    write_target_replay_manifest,
    write_target_replay_trajectory,
)
from retargetlab.run.fingerprint import sha256_bytes

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_SEMANTIC = 3
EXIT_QUALITY = 4
EXIT_ENVIRONMENT = 5
EXIT_ERROR = 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="retargetlab")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="check the local runtime")
    doctor.add_argument("--json", action="store_true", help="emit JSON to stdout")

    build_robot_profile = subparsers.add_parser(
        "build-robot-profile", help="build a versioned target robot profile artifact"
    )
    build_robot_profile.add_argument("--robot", required=True, choices=("openarm_bimanual",))
    build_robot_profile.add_argument("--asset-dir", required=True, type=Path)
    build_robot_profile.add_argument("--output", required=True, type=Path)
    build_robot_profile.add_argument("--json", action="store_true", help="emit JSON to stdout")

    build_export = subparsers.add_parser(
        "build-export-profile", help="build an explicit target vector export profile"
    )
    build_export.add_argument("--profile", required=True, type=Path)
    build_export.add_argument("--output", required=True, type=Path)
    build_export.add_argument("--json", action="store_true", help="emit JSON to stdout")

    map_grippers = subparsers.add_parser(
        "map-grippers", help="map canonical aperture streams to target gripper joints"
    )
    map_grippers.add_argument("--trajectory", required=True, type=Path)
    map_grippers.add_argument("--profile", required=True, type=Path)
    map_grippers.add_argument(
        "--binding",
        required=True,
        action="append",
        metavar="STREAM=GROUP",
        help="bind one canonical gripper stream to one target robot group",
    )
    map_grippers.add_argument("--output", required=True, type=Path)
    map_grippers.add_argument("--json", action="store_true", help="emit JSON to stdout")

    build_replay = subparsers.add_parser(
        "build-replay-manifest", help="bind canonical-to-target replay provenance"
    )
    build_replay.add_argument("--replay-id", required=True)
    build_replay.add_argument("--trajectory", required=True, type=Path)
    build_replay.add_argument("--profile", required=True, type=Path)
    build_replay.add_argument("--recipe", required=True, type=Path)
    build_replay.add_argument(
        "--arm-solve",
        required=True,
        action="append",
        type=Path,
        help="one arm solve artifact; repeat once per target robot group",
    )
    build_replay.add_argument("--target-grippers", required=True, type=Path)
    build_replay.add_argument("--coupling", required=True)
    build_replay.add_argument("--output", required=True, type=Path)
    build_replay.add_argument("--json", action="store_true", help="emit JSON to stdout")

    verify_replay = subparsers.add_parser(
        "verify-replay-manifest", help="verify replay input hashes and lineage"
    )
    verify_replay.add_argument("--manifest", required=True, type=Path)
    verify_replay.add_argument("--json", action="store_true", help="emit JSON to stdout")

    materialize_replay = subparsers.add_parser(
        "materialize-replay", help="materialize verified target command values"
    )
    materialize_replay.add_argument("--manifest", required=True, type=Path)
    materialize_replay.add_argument("--export-profile", required=True, type=Path)
    materialize_replay.add_argument(
        "--stream",
        choices=("observation.state", "action"),
        default="action",
        help="target output stream represented by this artifact",
    )
    materialize_replay.add_argument("--output", required=True, type=Path)
    materialize_replay.add_argument("--json", action="store_true", help="emit JSON to stdout")

    verify_target_replay = subparsers.add_parser(
        "verify-target-replay", help="verify a materialized target command artifact"
    )
    verify_target_replay.add_argument("--artifact", required=True, type=Path)
    verify_target_replay.add_argument("--json", action="store_true", help="emit JSON to stdout")

    build_replay_bundle = subparsers.add_parser(
        "build-replay-bundle", help="bind distinct target state and action replay artifacts"
    )
    build_replay_bundle.add_argument("--observation-state", required=True, type=Path)
    build_replay_bundle.add_argument("--action", required=True, type=Path)
    build_replay_bundle.add_argument("--output", required=True, type=Path)
    build_replay_bundle.add_argument("--json", action="store_true", help="emit JSON to stdout")

    verify_replay_bundle = subparsers.add_parser(
        "verify-replay-bundle", help="verify a target state/action replay bundle"
    )
    verify_replay_bundle.add_argument("--bundle", required=True, type=Path)
    verify_replay_bundle.add_argument("--json", action="store_true", help="emit JSON to stdout")

    verify_export_inputs = subparsers.add_parser(
        "verify-export-inputs", help="verify value-free prerequisites for dataset export"
    )
    verify_export_inputs.add_argument("--data-profile", required=True, type=Path)
    verify_export_inputs.add_argument("--decision", required=True, type=Path)
    verify_export_inputs.add_argument("--coverage", required=True, type=Path)
    verify_export_inputs.add_argument("--target-replay-bundle", required=True, type=Path)
    verify_export_inputs.add_argument("--export-profile", required=True, type=Path)
    verify_export_inputs.add_argument("--episode-indices", required=True, nargs="+", type=int)
    verify_export_inputs.add_argument("--output", required=True, type=Path)
    verify_export_inputs.add_argument("--json", action="store_true", help="emit JSON to stdout")

    write_synthetic_table = subparsers.add_parser(
        "write-synthetic-table",
        help="write one synthetic/public target Parquet table from a verified replay bundle",
    )
    write_synthetic_table.add_argument("--source", required=True, type=Path)
    write_synthetic_table.add_argument("--target-replay-bundle", required=True, type=Path)
    write_synthetic_table.add_argument("--output", required=True, type=Path)
    write_synthetic_table.add_argument(
        "--preflight",
        type=Path,
        help="optional verified synthetic table preflight bound to an export input gate",
    )
    write_synthetic_table.add_argument(
        "--report",
        type=Path,
        help="optional value-free write/verify report path",
    )
    write_synthetic_table.add_argument("--json", action="store_true", help="emit JSON to stdout")

    verify_synthetic_table = subparsers.add_parser(
        "verify-synthetic-table",
        help="verify synthetic target vectors, preserved columns, and lineage",
    )
    verify_synthetic_table.add_argument("--source", required=True, type=Path)
    verify_synthetic_table.add_argument("--target-replay-bundle", required=True, type=Path)
    verify_synthetic_table.add_argument("--output", required=True, type=Path)
    verify_synthetic_table.add_argument("--preflight", type=Path)
    verify_synthetic_table.add_argument("--report", type=Path)
    verify_synthetic_table.add_argument(
        "--json", action="store_true", help="emit JSON to stdout"
    )

    build_synthetic_preflight = subparsers.add_parser(
        "build-synthetic-table-preflight",
        help="bind a synthetic table rewrite to a verified export input gate",
    )
    build_synthetic_preflight.add_argument("--export-input-gate", required=True, type=Path)
    build_synthetic_preflight.add_argument("--source", required=True, type=Path)
    build_synthetic_preflight.add_argument("--target-replay-bundle", required=True, type=Path)
    build_synthetic_preflight.add_argument("--output-table", required=True, type=Path)
    build_synthetic_preflight.add_argument("--output", required=True, type=Path)
    build_synthetic_preflight.add_argument(
        "--json", action="store_true", help="emit JSON to stdout"
    )

    verify_synthetic_preflight = subparsers.add_parser(
        "verify-synthetic-table-preflight",
        help="verify a synthetic table rewrite preflight",
    )
    verify_synthetic_preflight.add_argument("--preflight", required=True, type=Path)
    verify_synthetic_preflight.add_argument(
        "--json", action="store_true", help="emit JSON to stdout"
    )

    build_lerobot_plan = subparsers.add_parser(
        "build-lerobot-metadata-plan",
        help="build a metadata-only LeRobot v3 export plan",
    )
    build_lerobot_plan.add_argument("--export-input-gate", required=True, type=Path)
    build_lerobot_plan.add_argument("--export-profile", required=True, type=Path)
    build_lerobot_plan.add_argument("--fps", required=True, type=float)
    build_lerobot_plan.add_argument(
        "--features",
        required=True,
        type=Path,
        help="JSON object mapping feature names to dtype/shape declarations",
    )
    build_lerobot_plan.add_argument(
        "--tasks",
        required=True,
        type=Path,
        help="JSON array of task metadata records",
    )
    build_lerobot_plan.add_argument(
        "--episodes",
        required=True,
        type=Path,
        help="JSON array of episode metadata records",
    )
    build_lerobot_plan.add_argument("--output", required=True, type=Path)
    build_lerobot_plan.add_argument(
        "--json", action="store_true", help="emit JSON to stdout"
    )

    verify_lerobot_plan = subparsers.add_parser(
        "verify-lerobot-metadata-plan",
        help="verify a metadata-only LeRobot v3 export plan",
    )
    verify_lerobot_plan.add_argument("--plan", required=True, type=Path)
    verify_lerobot_plan.add_argument(
        "--json", action="store_true", help="emit JSON to stdout"
    )

    write_lerobot_skeleton = subparsers.add_parser(
        "write-lerobot-metadata-skeleton",
        help="write a verified, metadata-only LeRobot v3 skeleton",
    )
    write_lerobot_skeleton.add_argument("--plan", required=True, type=Path)
    write_lerobot_skeleton.add_argument("--output-root", required=True, type=Path)
    write_lerobot_skeleton.add_argument(
        "--report",
        type=Path,
        help="optional write manifest; keep it outside --output-root",
    )
    write_lerobot_skeleton.add_argument(
        "--json", action="store_true", help="emit JSON to stdout"
    )

    verify_lerobot_skeleton = subparsers.add_parser(
        "verify-lerobot-metadata-skeleton",
        help="verify a metadata-only LeRobot v3 skeleton",
    )
    verify_lerobot_skeleton.add_argument("--plan", required=True, type=Path)
    verify_lerobot_skeleton.add_argument("--output-root", required=True, type=Path)
    verify_lerobot_skeleton.add_argument(
        "--json", action="store_true", help="emit JSON to stdout"
    )

    write_lerobot_partial = subparsers.add_parser(
        "write-lerobot-partial-dataset",
        help="bind one verified synthetic target table to a LeRobot data shard",
    )
    write_lerobot_partial.add_argument("--plan", required=True, type=Path)
    write_lerobot_partial.add_argument("--output-root", required=True, type=Path)
    write_lerobot_partial.add_argument("--target-table-report", required=True, type=Path)
    write_lerobot_partial.add_argument(
        "--report",
        type=Path,
        help="optional write manifest; keep it outside --output-root",
    )
    write_lerobot_partial.add_argument(
        "--json", action="store_true", help="emit JSON to stdout"
    )

    verify_lerobot_partial = subparsers.add_parser(
        "verify-lerobot-partial-dataset",
        help="verify metadata and one synthetic LeRobot data shard",
    )
    verify_lerobot_partial.add_argument("--plan", required=True, type=Path)
    verify_lerobot_partial.add_argument("--output-root", required=True, type=Path)
    verify_lerobot_partial.add_argument("--target-table-report", required=True, type=Path)
    verify_lerobot_partial.add_argument(
        "--json", action="store_true", help="emit JSON to stdout"
    )

    inspect = subparsers.add_parser(
        "inspect", help="inspect a canonical JSON trajectory or source structure"
    )
    inspect.add_argument("path", type=Path)
    inspect.add_argument("--dataset-alias")
    inspect.add_argument("--source-revision")
    inspect.add_argument("--metadata", type=Path, help="LeRobot info.json for Parquet comparison")
    inspect.add_argument("--json", action="store_true", help="emit JSON to stdout")

    coverage = subparsers.add_parser(
        "scan-coverage", help="scan a value-free LeRobot dataset coverage manifest"
    )
    coverage.add_argument("--info", required=True, type=Path)
    coverage.add_argument("--data", required=True, type=Path)
    coverage.add_argument("--episodes", required=True, type=Path)
    coverage.add_argument("--tasks", required=True, type=Path)
    coverage.add_argument("--stats", required=True, type=Path)
    coverage.add_argument("--dataset-alias", required=True)
    coverage.add_argument("--source-revision", required=True)
    coverage.add_argument("--validation-scope", required=True)
    coverage.add_argument("--output", required=True, type=Path)
    coverage.add_argument("--json", action="store_true", help="emit JSON to stdout")

    candidate = subparsers.add_parser(
        "candidate", help="build a review-only pose mapping from info.json"
    )
    candidate.add_argument("metadata", type=Path)
    candidate.add_argument("--dataset-alias", required=True)
    candidate.add_argument("--source-revision", required=True)
    candidate.add_argument("--json", action="store_true", help="emit JSON to stdout")

    review_mapping = subparsers.add_parser(
        "review-mapping", help="apply an explicit semantic review to a mapping candidate"
    )
    review_mapping.add_argument("candidate", type=Path)
    review_mapping.add_argument("--review", required=True, type=Path)
    review_mapping.add_argument("--comparison", required=True, type=Path)
    review_mapping.add_argument("--output", type=Path)
    review_mapping.add_argument("--json", action="store_true", help="emit JSON to stdout")

    inspect_review = subparsers.add_parser(
        "inspect-review-package",
        help="inspect review readiness without promoting a mapping",
    )
    inspect_review.add_argument("--candidate", required=True, type=Path)
    inspect_review.add_argument("--review", required=True, type=Path)
    inspect_review.add_argument("--comparison", required=True, type=Path)
    inspect_review.add_argument("--output", type=Path)
    inspect_review.add_argument("--json", action="store_true", help="emit JSON to stdout")

    verify_review = subparsers.add_parser(
        "verify-review-package",
        help="verify a saved review-package preflight",
    )
    verify_review.add_argument("--preflight", required=True, type=Path)
    verify_review.add_argument("--candidate", required=True, type=Path)
    verify_review.add_argument("--review", required=True, type=Path)
    verify_review.add_argument("--comparison", required=True, type=Path)
    verify_review.add_argument("--json", action="store_true", help="emit JSON to stdout")

    calibrate = subparsers.add_parser(
        "calibrate", help="run a bounded approved calibration and write an audit artifact"
    )
    calibrate.add_argument("--data", required=True, type=Path)
    calibrate.add_argument("--episodes", required=True, type=Path)
    calibrate.add_argument("--candidate", required=True, type=Path)
    calibrate.add_argument("--review", required=True, type=Path)
    calibrate.add_argument("--comparison", required=True, type=Path)
    calibrate.add_argument(
        "--decision",
        type=Path,
        help="optional approved semantic decision artifact to verify before reading data",
    )
    calibrate.add_argument(
        "--profile",
        type=Path,
        help="optional certified DataProfile to bind before reading data",
    )
    calibrate.add_argument("--episode-indices", required=True, nargs="+", type=int)
    calibrate.add_argument("--frames-per-episode", required=True, type=int)
    calibrate.add_argument("--max-frames", default=60, type=int)
    calibrate.add_argument("--output", required=True, type=Path)
    calibrate.add_argument("--json", action="store_true", help="emit JSON to stdout")

    timing = subparsers.add_parser(
        "analyze-timing",
        help="rank action.position[t] against observation.state.position[t+k]",
    )
    timing.add_argument("--data", required=True, type=Path)
    timing.add_argument("--dataset-alias", required=True)
    timing.add_argument("--source-revision", required=True)
    timing.add_argument("--episode-indices", required=True, nargs="+", type=int)
    timing.add_argument("--joint-indices", required=True, nargs="+", type=int)
    timing.add_argument("--action-scales", nargs="+", type=float)
    timing.add_argument("--action-offsets", nargs="+", type=float)
    timing.add_argument("--max-shift", default=8, type=int)
    timing.add_argument(
        "--expected-shifts",
        default=(4, 5),
        nargs=2,
        type=int,
        metavar=("MIN", "MAX"),
    )
    timing.add_argument("--output", required=True, type=Path)
    timing.add_argument("--json", action="store_true", help="emit JSON to stdout")

    verify_calibration = subparsers.add_parser(
        "verify-calibration", help="verify a bounded calibration artifact set"
    )
    verify_calibration.add_argument("--run", required=True, type=Path)
    verify_calibration.add_argument(
        "--decision",
        type=Path,
        help="optionally verify the archived decision file against the run recipe",
    )
    verify_calibration.add_argument("--json", action="store_true", help="emit JSON to stdout")

    verify_profile = subparsers.add_parser(
        "verify-profile", help="verify a value-free dataset profile and optional review decision"
    )
    verify_profile.add_argument("--profile", required=True, type=Path)
    verify_profile.add_argument(
        "--decision",
        type=Path,
        help="optionally verify the exact semantic decision bound to the profile",
    )
    verify_profile.add_argument("--json", action="store_true", help="emit JSON to stdout")

    diagnose = subparsers.add_parser("diagnose", help="inspect a completed run report")
    diagnose.add_argument("--run", required=True, type=Path)
    diagnose.add_argument("--json", action="store_true", help="emit JSON to stdout")

    validate_input = subparsers.add_parser(
        "validate-input", help="validate a mapping against a structure manifest"
    )
    validate_input.add_argument("manifest", type=Path)
    validate_input.add_argument("--spec", required=True, type=Path)
    validate_input.add_argument("--json", action="store_true", help="emit JSON to stdout")

    normalize = subparsers.add_parser(
        "normalize", help="normalize explicitly mapped pose rows into canonical JSON"
    )
    normalize.add_argument("rows", type=Path)
    normalize_source = normalize.add_mutually_exclusive_group(required=True)
    normalize_source.add_argument("--spec", type=Path)
    normalize_source.add_argument(
        "--profile",
        type=Path,
        help="use a certified DataProfile as the executable mapping source",
    )
    normalize.add_argument(
        "--decision",
        type=Path,
        help="semantic decision bound to --profile",
    )
    normalize.add_argument("--output", required=True, type=Path)
    normalize.add_argument("--json", action="store_true", help="emit JSON to stdout")

    solve = subparsers.add_parser("solve", help="solve one canonical stream with Pink")
    solve.add_argument("--trajectory", required=True, type=Path)
    solve.add_argument("--profile", required=True, type=Path)
    solve.add_argument("--recipe", required=True, type=Path)
    solve.add_argument("--group", required=True)
    solve.add_argument("--initial-q", required=True, nargs="+", type=float)
    output_or_project = solve.add_mutually_exclusive_group(required=True)
    output_or_project.add_argument("--output", type=Path)
    output_or_project.add_argument("--project", type=Path)
    solve.add_argument("--run-id")
    solve.add_argument("--json", action="store_true", help="emit JSON to stdout")
    return parser


def _dependency(name: str, distribution: str) -> dict[str, str]:
    present = importlib.util.find_spec(name) is not None
    result = {"status": "available" if present else "missing"}
    if present:
        try:
            result["version"] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            result["version"] = "unknown"
    return result


def _doctor_payload() -> tuple[dict[str, Any], int]:
    dependencies = {
        name: _dependency(name, distribution)
        for name, distribution in (
            ("numpy", "numpy"),
            ("pydantic", "pydantic"),
            ("pinocchio", "pin"),
            ("pink", "pin-pink"),
            ("qpsolvers", "qpsolvers"),
            ("osqp", "osqp"),
            ("pyarrow", "pyarrow"),
        )
    }
    required = ("numpy", "pydantic", "pinocchio", "pink", "qpsolvers", "osqp")
    missing = [name for name in required if dependencies[name]["status"] == "missing"]
    payload = {
        "command": "doctor",
        "retargetlab_version": __version__,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "dependencies": dependencies,
        "status": "READY" if not missing else "MISSING_DEPENDENCIES",
        "missing": missing,
    }
    return payload, EXIT_OK if not missing else EXIT_ENVIRONMENT


def _inspect_payload(
    path: Path,
    dataset_alias: str | None = None,
    source_revision: str | None = None,
    metadata_path: Path | None = None,
) -> dict[str, Any]:
    if path.suffix.lower() == ".parquet":
        if not dataset_alias or not source_revision:
            raise ValueError("Parquet inspect requires --dataset-alias and --source-revision")
        manifest = probe_parquet(
            path,
            dataset_alias=dataset_alias,
            source_revision=source_revision,
        )
        payload: dict[str, Any] = {
            "command": "inspect",
            "kind": "parquet",
            "dataset_alias": manifest.dataset_alias,
            "source_revision": manifest.source_revision,
            "source_sha256": manifest.source_sha256,
            "row_count": manifest.row_count,
            "fields": {
                name: field.model_dump(mode="json")
                for name, field in sorted(manifest.fields.items())
            },
        }
        if metadata_path is not None:
            info = probe_lerobot_info(
                metadata_path,
                dataset_alias=dataset_alias,
                source_revision=source_revision,
            )
            comparison = compare_info_to_structure(info, manifest)
            payload["metadata"] = {
                "source_sha256": info.source_sha256,
                "dataset_name": info.dataset_name,
                "total_episodes": info.total_episodes,
                "total_frames": info.total_frames,
                "total_tasks": info.total_tasks,
                "total_chunks": info.total_chunks,
                "fps": info.fps,
                "features": {
                    name: feature.model_dump(mode="json")
                    for name, feature in sorted(info.features.items())
                },
            }
            payload["comparison"] = comparison.model_dump(mode="json")
        return payload
    if metadata_path is not None:
        raise ValueError("--metadata is only supported when inspecting a Parquet file")
    if path.name.lower() == "info.json":
        if not dataset_alias or not source_revision:
            raise ValueError("info.json inspect requires --dataset-alias and --source-revision")
        info = probe_lerobot_info(
            path,
            dataset_alias=dataset_alias,
            source_revision=source_revision,
        )
        return {
            "command": "inspect",
            "kind": "lerobot-info",
            "dataset_alias": info.dataset_alias,
            "source_revision": info.source_revision,
            "source_sha256": info.source_sha256,
            "dataset_name": info.dataset_name,
            "total_episodes": info.total_episodes,
            "total_frames": info.total_frames,
            "total_tasks": info.total_tasks,
            "total_chunks": info.total_chunks,
            "fps": info.fps,
            "features": {
                name: feature.model_dump(mode="json")
                for name, feature in sorted(info.features.items())
            },
        }
    trajectory = CanonicalTrajectory.model_validate_json(path.read_text(encoding="utf-8"))
    return {
        "command": "inspect",
        "schema_version": trajectory.schema_version,
        "coordinate_frame": trajectory.coordinate_frame,
        "frame_count": trajectory.frame_count,
        "stream_names": list(trajectory.stream_names),
        "metadata_keys": sorted(trajectory.metadata),
    }


def _coverage_payload(
    *,
    info_path: Path,
    data_path: Path,
    episodes_path: Path,
    tasks_path: Path,
    stats_path: Path,
    dataset_alias: str,
    source_revision: str,
    validation_scope: str,
    output_path: Path,
) -> tuple[dict[str, Any], int]:
    coverage = scan_lerobot_coverage(
        info_path=info_path,
        data_path=data_path,
        episodes_path=episodes_path,
        tasks_path=tasks_path,
        stats_path=stats_path,
        dataset_alias=dataset_alias,
        source_revision=source_revision,
        validation_scope=validation_scope,
    )
    write_dataset_coverage(output_path, coverage)
    return (
        {
            "command": "scan-coverage",
            **coverage.model_dump(mode="json"),
            "output": str(output_path),
        },
        EXIT_OK if coverage.status == "COMPLETE" else EXIT_QUALITY,
    )


def _robot_profile_payload(
    *,
    robot_id: str,
    asset_dir: Path,
    output_path: Path,
) -> dict[str, Any]:
    if robot_id != "openarm_bimanual":
        raise ValueError(f"unsupported robot profile: {robot_id}")
    profile = load_openarm_bimanual_profile(asset_dir)
    write_robot_profile(output_path, profile)
    return {
        "command": "build-robot-profile",
        "status": "WRITTEN",
        "robot_id": profile.robot_id,
        "root_frame": profile.root_frame,
        "group_names": [group.name for group in profile.groups],
        "profile_sha256": sha256_bytes(canonical_json_bytes(profile)),
        "output": str(output_path),
    }


def _export_profile_payload(
    *,
    profile_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    profile = RobotProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    export_profile = build_export_profile(profile)
    write_export_profile(output_path, export_profile)
    layout = export_profile.target_layout
    return {
        "command": "build-export-profile",
        "status": "WRITTEN",
        "robot_id": export_profile.robot_id,
        "robot_profile_sha256": export_profile.robot_profile_sha256,
        "dtype": layout.dtype,
        "shape": list(layout.shape),
        "joint_names": list(layout.names),
        "joint_units": list(layout.units),
        "output": str(output_path),
    }


def _parse_gripper_bindings(raw_bindings: list[str]) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for raw in raw_bindings:
        stream, separator, group = raw.partition("=")
        if not separator or not stream.strip() or not group.strip():
            raise ValueError(f"invalid gripper binding, expected STREAM=GROUP: {raw}")
        if stream in bindings:
            raise ValueError(f"duplicate gripper binding for stream: {stream}")
        bindings[stream] = group
    return bindings


def _map_grippers_payload(
    *,
    trajectory_path: Path,
    profile_path: Path,
    raw_bindings: list[str],
    output_path: Path,
) -> dict[str, Any]:
    trajectory = CanonicalTrajectory.model_validate_json(
        trajectory_path.read_text(encoding="utf-8")
    )
    profile = RobotProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    mapped = map_target_grippers(
        trajectory,
        profile,
        _parse_gripper_bindings(raw_bindings),
    )
    write_target_gripper_trajectory(output_path, mapped)
    return {
        "command": "map-grippers",
        "status": "MAPPED",
        "robot_id": mapped.robot_id,
        "profile_sha256": mapped.profile_sha256,
        "group_names": list(mapped.group_names),
        "frame_count": len(mapped.frames),
        "joint_names": sorted(mapped.frames[0].joint_positions),
        "output": str(output_path),
    }


def _replay_manifest_payload(
    *,
    replay_id: str,
    trajectory_path: Path,
    profile_path: Path,
    recipe_path: Path,
    arm_solve_paths: list[Path],
    target_grippers_path: Path,
    coupling: str,
    output_path: Path,
) -> dict[str, Any]:
    manifest = build_target_replay_manifest(
        replay_id=replay_id,
        trajectory_path=trajectory_path,
        profile_path=profile_path,
        recipe_path=recipe_path,
        arm_solve_paths=arm_solve_paths,
        target_grippers_path=target_grippers_path,
        coupling=coupling,
    )
    write_target_replay_manifest(output_path, manifest)
    return {
        "command": "build-replay-manifest",
        "status": manifest.status,
        "replay_id": manifest.replay_id,
        "robot_id": manifest.robot_id,
        "frame_count": manifest.frame_count,
        "arm_groups": list(manifest.arm_groups),
        "profile_sha256": manifest.robot_profile_sha256,
        "artifact_roles": [artifact.role for artifact in manifest.artifacts],
        "output": str(output_path),
    }


def _verify_replay_payload(manifest_path: Path) -> dict[str, Any]:
    verification = verify_target_replay_manifest(manifest_path)
    return {
        "command": "verify-replay-manifest",
        **verification.model_dump(mode="json"),
    }


def _materialize_replay_payload(
    *,
    manifest_path: Path,
    export_profile_path: Path,
    stream_name: str,
    output_path: Path,
) -> dict[str, Any]:
    replay = build_target_replay_trajectory(
        manifest_path=manifest_path,
        export_profile_path=export_profile_path,
        stream_name=stream_name,  # type: ignore[arg-type]
    )
    write_target_replay_trajectory(output_path, replay)
    return {
        "command": "materialize-replay",
        "status": replay.status,
        "stream_name": replay.stream_name,
        "replay_id": replay.replay_id,
        "robot_id": replay.robot_id,
        "frame_count": replay.frame_count,
        "dtype": replay.layout.dtype,
        "shape": list(replay.layout.shape),
        "joint_names": list(replay.layout.names),
        "export_profile_sha256": replay.export_profile_sha256,
        "replay_manifest_sha256": replay.replay_manifest_sha256,
        "output": str(output_path),
    }


def _verify_target_replay_payload(artifact_path: Path) -> dict[str, Any]:
    verification = verify_target_replay_trajectory(artifact_path)
    return {
        "command": "verify-target-replay",
        **verification.model_dump(mode="json"),
    }


def _build_replay_bundle_payload(
    *,
    observation_state_path: Path,
    action_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    bundle = build_target_replay_bundle(
        observation_state_path=observation_state_path,
        action_path=action_path,
    )
    write_target_replay_bundle(output_path, bundle)
    return {
        "command": "build-replay-bundle",
        "status": bundle.status,
        "replay_id": bundle.replay_id,
        "robot_id": bundle.robot_id,
        "frame_count": bundle.frame_count,
        "shape": list(bundle.layout.shape),
        "joint_names": list(bundle.layout.names),
        "export_profile_sha256": bundle.export_profile_sha256,
        "output": str(output_path),
    }


def _verify_replay_bundle_payload(bundle_path: Path) -> dict[str, Any]:
    verification = verify_target_replay_bundle(bundle_path)
    return {
        "command": "verify-replay-bundle",
        **verification.model_dump(mode="json"),
    }


def _verify_export_inputs_payload(
    *,
    data_profile_path: Path,
    decision_path: Path,
    coverage_path: Path,
    target_replay_bundle_path: Path,
    export_profile_path: Path,
    episode_indices: list[int],
    output_path: Path,
) -> dict[str, Any]:
    gate = build_export_input_gate(
        data_profile_path=data_profile_path,
        decision_path=decision_path,
        coverage_path=coverage_path,
        target_replay_bundle_path=target_replay_bundle_path,
        export_profile_path=export_profile_path,
        training_episode_allowlist=episode_indices,
    )
    write_export_input_gate(output_path, gate)
    return {
        "command": "verify-export-inputs",
        **gate.model_dump(mode="json"),
        "output": str(output_path),
    }


def _write_synthetic_table_payload(
    *,
    source_path: Path,
    target_replay_bundle_path: Path,
    output_path: Path,
    preflight_path: Path | None,
    report_path: Path | None,
) -> dict[str, Any]:
    artifact = write_synthetic_target_table(
        source_path=source_path,
        target_replay_bundle_path=target_replay_bundle_path,
        output_path=output_path,
        preflight_path=preflight_path,
    )
    payload = {
        "command": "write-synthetic-table",
        **artifact.model_dump(mode="json"),
    }
    if report_path is not None:
        verification = verify_synthetic_target_table(
            source_path=source_path,
            target_replay_bundle_path=target_replay_bundle_path,
            output_path=output_path,
            preflight_path=preflight_path,
        )
        report = build_synthetic_table_write_report(
            write=artifact,
            verification=verification,
        )
        write_synthetic_table_write_report(report_path, report)
        payload["report_path"] = str(report_path)
    return payload


def _verify_synthetic_table_payload(
    *,
    source_path: Path,
    target_replay_bundle_path: Path,
    output_path: Path,
    preflight_path: Path | None,
    report_path: Path | None,
) -> dict[str, Any]:
    verification = verify_synthetic_target_table(
        source_path=source_path,
        target_replay_bundle_path=target_replay_bundle_path,
        output_path=output_path,
        preflight_path=preflight_path,
    )
    if report_path is not None:
        report_verification = verify_synthetic_table_write_report(report_path)
        if report_verification != verification:
            raise ValueError("synthetic table write report does not match CLI inputs")
    payload = {
        "command": "verify-synthetic-table",
        **verification.model_dump(mode="json"),
    }
    if report_path is not None:
        payload["report_path"] = str(report_path)
    return payload


def _build_synthetic_preflight_payload(
    *,
    export_input_gate_path: Path,
    source_path: Path,
    target_replay_bundle_path: Path,
    output_table_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    preflight = build_synthetic_table_write_preflight(
        export_input_gate_path=export_input_gate_path,
        source_table_path=source_path,
        target_replay_bundle_path=target_replay_bundle_path,
        output_table_path=output_table_path,
    )
    write_synthetic_table_write_preflight(output_path, preflight)
    return {
        "command": "build-synthetic-table-preflight",
        **preflight.model_dump(mode="json"),
        "output": str(output_path),
    }


def _verify_synthetic_preflight_payload(preflight_path: Path) -> dict[str, Any]:
    verification = verify_synthetic_table_write_preflight(preflight_path)
    return {
        "command": "verify-synthetic-table-preflight",
        **verification.model_dump(mode="json"),
    }


def _json_file(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be valid JSON: {path}") from exc


def _build_lerobot_plan_payload(
    *,
    export_input_gate_path: Path,
    export_profile_path: Path,
    fps: float,
    features_path: Path,
    tasks_path: Path,
    episodes_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    raw_features = _json_file(features_path, "feature declarations")
    raw_tasks = _json_file(tasks_path, "task metadata")
    raw_episodes = _json_file(episodes_path, "episode metadata")
    if not isinstance(raw_features, dict):
        raise ValueError("feature declarations must be a JSON object")
    if not isinstance(raw_tasks, list):
        raise ValueError("task metadata must be a JSON array")
    if not isinstance(raw_episodes, list):
        raise ValueError("episode metadata must be a JSON array")
    features = {
        name: FeatureDeclaration.model_validate(value)
        for name, value in raw_features.items()
    }
    tasks = tuple(LeRobotTaskMetadata.model_validate(value) for value in raw_tasks)
    episodes = tuple(LeRobotEpisodeMetadata.model_validate(value) for value in raw_episodes)
    plan = build_lerobot_metadata_plan(
        export_input_gate_path=export_input_gate_path,
        export_profile_path=export_profile_path,
        fps=fps,
        features=features,
        tasks=tasks,
        episodes=episodes,
    )
    write_lerobot_metadata_plan(output_path, plan)
    return {
        "command": "build-lerobot-metadata-plan",
        **plan.model_dump(mode="json"),
        "output": str(output_path),
    }


def _verify_lerobot_plan_payload(plan_path: Path) -> dict[str, Any]:
    verification = verify_lerobot_metadata_plan(plan_path)
    return {
        "command": "verify-lerobot-metadata-plan",
        **verification.model_dump(mode="json"),
    }


def _write_lerobot_skeleton_payload(
    *,
    plan_path: Path,
    output_root: Path,
    report_path: Path | None,
) -> dict[str, Any]:
    if report_path is not None:
        try:
            report_path.resolve().relative_to(output_root.resolve())
        except ValueError:
            pass
        else:
            raise ValueError("skeleton report must be outside the output root")
    manifest = write_lerobot_metadata_skeleton(
        plan_path=plan_path,
        output_root=output_root,
    )
    if report_path is not None:
        write_lerobot_metadata_skeleton_report(report_path, manifest)
    payload = {
        "command": "write-lerobot-metadata-skeleton",
        **manifest.model_dump(mode="json"),
    }
    if report_path is not None:
        payload["report"] = str(report_path)
    return payload


def _verify_lerobot_skeleton_payload(
    *,
    plan_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    verification = verify_lerobot_metadata_skeleton(
        plan_path=plan_path,
        output_root=output_root,
    )
    return {
        "command": "verify-lerobot-metadata-skeleton",
        **verification.model_dump(mode="json"),
    }


def _write_lerobot_partial_payload(
    *,
    plan_path: Path,
    output_root: Path,
    target_table_report_path: Path,
    report_path: Path | None,
) -> dict[str, Any]:
    if report_path is not None:
        try:
            report_path.resolve().relative_to(output_root.resolve())
        except ValueError:
            pass
        else:
            raise ValueError("partial dataset report must be outside the output root")
    manifest = write_lerobot_partial_dataset(
        plan_path=plan_path,
        output_root=output_root,
        target_table_report_path=target_table_report_path,
    )
    if report_path is not None:
        write_lerobot_partial_dataset_report(report_path, manifest)
    payload = {
        "command": "write-lerobot-partial-dataset",
        **manifest.model_dump(mode="json"),
    }
    if report_path is not None:
        payload["report"] = str(report_path)
    return payload


def _verify_lerobot_partial_payload(
    *,
    plan_path: Path,
    output_root: Path,
    target_table_report_path: Path,
) -> dict[str, Any]:
    verification = verify_lerobot_partial_dataset(
        plan_path=plan_path,
        output_root=output_root,
        target_table_report_path=target_table_report_path,
    )
    return {
        "command": "verify-lerobot-partial-dataset",
        **verification.model_dump(mode="json"),
    }


def _candidate_payload(
    metadata_path: Path,
    dataset_alias: str,
    source_revision: str,
) -> dict[str, Any]:
    info = probe_lerobot_info(
        metadata_path,
        dataset_alias=dataset_alias,
        source_revision=source_revision,
    )
    candidate = build_pose_mapping_candidate(info)
    return {
        "command": "candidate",
        "status": candidate.metadata["candidate_status"],
        "metadata_sha256": info.source_sha256,
        "mapping": candidate.model_dump(mode="json"),
    }


def _load_review_package(
    candidate_path: Path,
    review_path: Path,
    comparison_path: Path,
) -> tuple[MappingSpec, MappingReview, StructureComparison]:
    raw = json.loads(candidate_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("mapping candidate must contain a JSON object")
    candidate = MappingSpec.model_validate(raw.get("mapping", raw))
    review = MappingReview.model_validate_json(review_path.read_text(encoding="utf-8"))
    comparison_raw = json.loads(comparison_path.read_text(encoding="utf-8"))
    if not isinstance(comparison_raw, dict):
        raise ValueError("structure comparison must contain a JSON object")
    comparison = StructureComparison.model_validate(
        comparison_raw.get("comparison", comparison_raw)
    )
    return candidate, review, comparison


def _load_reviewed_mapping(
    candidate_path: Path,
    review_path: Path,
    comparison_path: Path,
) -> tuple[MappingSpec, StructureComparison]:
    candidate, review, comparison = _load_review_package(
        candidate_path,
        review_path,
        comparison_path,
    )
    approved = apply_mapping_review(candidate, review, comparison)
    return approved, comparison


def _review_mapping_payload(
    candidate_path: Path,
    review_path: Path,
    comparison_path: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    candidate, review, comparison = _load_review_package(
        candidate_path,
        review_path,
        comparison_path,
    )
    approved = apply_mapping_review(candidate, review, comparison)
    payload: dict[str, Any] = {
        "command": "review-mapping",
        "status": "APPROVED",
        "comparison": comparison.model_dump(mode="json"),
        "mapping": approved.model_dump(mode="json"),
    }
    if output_path is not None:
        decision = write_review_decision_artifact(
            output_path,
            candidate=candidate,
            review=review,
            comparison=comparison,
        )
        payload.update(
            {
                "decision_output": str(output_path),
                "decision_artifact_sha256": sha256_bytes(canonical_json_bytes(decision)),
            }
        )
    return payload


def _inspect_review_package_payload(
    candidate_path: Path,
    review_path: Path,
    comparison_path: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    candidate, review, comparison = _load_review_package(
        candidate_path,
        review_path,
        comparison_path,
    )
    inspection = inspect_review_package(candidate, review, comparison)
    payload: dict[str, Any] = {
        "command": "inspect-review-package",
        **inspection.model_dump(mode="json"),
    }
    if output_path is not None:
        artifact = write_review_package_preflight(
            output_path,
            candidate=candidate,
            review=review,
            comparison=comparison,
        )
        payload.update(
            {
                "output": str(output_path),
                "artifact_sha256": sha256_bytes(canonical_json_bytes(artifact)),
            }
        )
    return payload


def _verify_review_package_payload(
    preflight_path: Path,
    candidate_path: Path,
    review_path: Path,
    comparison_path: Path,
) -> dict[str, Any]:
    verification = verify_review_package_preflight(
        preflight_path,
        candidate_path=candidate_path,
        review_path=review_path,
        comparison_path=comparison_path,
    )
    return {
        "command": "verify-review-package",
        **verification.model_dump(mode="json"),
    }


def _calibrate_payload(
    *,
    data_path: Path,
    episodes_path: Path,
    candidate_path: Path,
    review_path: Path,
    comparison_path: Path,
    decision_path: Path | None,
    profile_path: Path | None,
    episode_indices: list[int],
    frames_per_episode: int,
    max_frames: int,
    output_path: Path,
) -> dict[str, Any]:
    profile = (
        load_executable_data_profile(profile_path, decision_path=decision_path)
        if profile_path is not None
        else None
    )
    profile_sha256 = sha256_bytes(canonical_json_bytes(profile)) if profile is not None else None
    candidate, review, comparison = _load_review_package(
        candidate_path,
        review_path,
        comparison_path,
    )
    mapping = apply_mapping_review(candidate, review, comparison)
    decision = None
    if decision_path is not None:
        decision = verify_review_decision_artifact(
            decision_path,
            candidate=candidate,
            review=review,
            comparison=comparison,
        )
    if profile is not None:
        if profile.dataset_alias != mapping.dataset_alias:
            raise ValueError("data profile dataset alias does not match mapping")
        if profile.source_revision != mapping.source_revision:
            raise ValueError("data profile source revision does not match mapping")
        if sha256_bytes(canonical_json_bytes(profile.mapping)) != sha256_bytes(
            canonical_json_bytes(mapping)
        ):
            raise ValueError("data profile mapping does not match approved review mapping")
        if profile.revision.data_sha256 != sha256_file(data_path):
            raise ValueError("data profile data hash does not match calibration data")
        if profile.revision.episodes_sha256 != sha256_file(episodes_path):
            raise ValueError("data profile episode hash does not match calibration episodes")
    trajectory, calibration, selection = run_parquet_calibration(
        data_path,
        episodes_path,
        mapping,
        comparison,
        episode_indices=episode_indices,
        frames_per_episode=frames_per_episode,
        max_frames=max_frames,
    )
    recipe = CalibrationRecipe(
        recipe_id=f"calibration-{output_path.stem}",
        dataset_alias=mapping.dataset_alias,
        source_revision=mapping.source_revision,
        data_sha256=selection.data_sha256,
        episodes_sha256=selection.episodes_sha256,
        mapping_sha256=sha256_bytes(canonical_json_bytes(mapping)),
        comparison_sha256=sha256_bytes(canonical_json_bytes(comparison)),
        review_sha256=sha256_file(review_path),
        decision_sha256=(
            sha256_bytes(canonical_json_bytes(decision)) if decision is not None else None
        ),
        profile_sha256=profile_sha256,
        episode_indices=tuple(episode_indices),
        frames_per_episode=frames_per_episode,
        max_frames=max_frames,
        columns=tuple(DEFAULT_CALIBRATION_COLUMNS),
    )
    manifest = write_calibration_run(
        output_path,
        recipe=recipe,
        mapping=mapping,
        comparison=comparison,
        review_sha256=recipe.review_sha256,
        decision_sha256=recipe.decision_sha256,
        profile_sha256=recipe.profile_sha256,
        selection=selection,
        calibration=calibration,
    )
    del trajectory
    return {
        "command": "calibrate",
        "status": calibration.status,
        "output": str(output_path),
        "frame_count": calibration.frame_count,
        "selected_row_count": selection.selected_frame_count,
        "recipe_sha256": manifest.recipe_sha256,
        "run_manifest": str(output_path.with_name("calibration-run-manifest.json")),
        "artifact_sha256": manifest.audit_sha256,
        "decision_sha256": recipe.decision_sha256,
    }


def _verify_calibration_payload(
    run_path: Path,
    decision_path: Path | None = None,
) -> dict[str, Any]:
    verification = verify_calibration_run(run_path, decision_path=decision_path)
    return {
        "command": "verify-calibration",
        **verification.model_dump(mode="json"),
    }


def _verify_profile_payload(
    profile_path: Path,
    decision_path: Path | None = None,
) -> dict[str, Any]:
    verification = verify_data_profile(profile_path, decision_path=decision_path)
    return {
        "command": "verify-profile",
        **verification.model_dump(mode="json"),
    }


def _timing_payload(
    *,
    data_path: Path,
    dataset_alias: str,
    source_revision: str,
    episode_indices: list[int],
    joint_indices: list[int],
    action_scales: list[float] | None,
    action_offsets: list[float] | None,
    max_shift: int,
    expected_shifts: list[int],
    output_path: Path,
) -> tuple[dict[str, Any], int]:
    report = analyze_command_timing(
        data_path,
        dataset_alias=dataset_alias,
        source_revision=source_revision,
        episode_indices=tuple(episode_indices),
        joint_indices=tuple(joint_indices),
        action_scales=tuple(action_scales) if action_scales is not None else None,
        action_offsets=tuple(action_offsets) if action_offsets is not None else None,
        max_shift=max_shift,
        expected_shift_range=(expected_shifts[0], expected_shifts[1]),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(report.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    payload = {
        "command": "analyze-timing",
        **report.model_dump(mode="json"),
        "output": str(output_path),
    }
    return payload, EXIT_OK if report.status == "SUPPORTED" else EXIT_QUALITY


def _diagnose_payload(run_path: Path) -> tuple[dict[str, Any], int]:
    report_path = run_path / "result" / "report.json"
    report = DatasetReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    payload = {
        "command": "diagnose",
        "status": report.status,
        "episode_count": report.episode_count,
        "episodes": [
            {
                "episode_index": episode.episode_index,
                "frame_count": episode.frame_count,
                "nominal_rate": episode.nominal_rate,
                "relaxed_rate": episode.relaxed_rate,
                "status": episode.status,
            }
            for episode in report.episodes
        ],
    }
    return payload, EXIT_QUALITY if report.status == "FAIL" else EXIT_OK


def _validate_input_payload(manifest_path: Path, spec_path: Path) -> tuple[dict[str, Any], int]:
    manifest = StructureManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    spec = MappingSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
    result = validate_mapping(spec, manifest)
    payload = {"command": "validate-input", **result.model_dump(mode="json")}
    return payload, EXIT_OK if result.valid else EXIT_SEMANTIC


def _normalize_payload(
    rows_path: Path,
    spec_path: Path | None,
    profile_path: Path | None,
    decision_path: Path | None,
    output_path: Path,
) -> dict[str, Any]:
    profile = (
        load_executable_data_profile(profile_path, decision_path=decision_path)
        if profile_path is not None
        else None
    )
    if profile is not None:
        spec = profile.mapping
        profile_sha256 = sha256_bytes(canonical_json_bytes(profile))
    elif spec_path is not None:
        if decision_path is not None:
            raise ValueError("normalize --decision requires --profile")
        spec = MappingSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
        profile_sha256 = None
    else:
        raise ValueError("normalize requires either --spec or --profile")
    raw_rows = json.loads(rows_path.read_text(encoding="utf-8"))
    if not isinstance(raw_rows, list) or not all(isinstance(row, dict) for row in raw_rows):
        raise ValueError("rows JSON must be a list of objects")
    trajectory = normalize_rows(
        raw_rows,
        spec,
        grippers=profile.grippers if profile is not None else (),
    )
    if profile_sha256 is not None:
        trajectory = trajectory.model_copy(
            update={"metadata": {**trajectory.metadata, "data_profile_sha256": profile_sha256}}
        )
    with output_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(trajectory.model_dump_json(indent=2))
        handle.write("\n")
    return {
        "command": "normalize",
        "status": "NORMALIZED",
        "output": output_path.name,
        "schema_version": trajectory.schema_version,
        "coordinate_frame": trajectory.coordinate_frame,
        "frame_count": trajectory.frame_count,
        "stream_names": list(trajectory.stream_names),
        "profile_sha256": profile_sha256,
    }


def _solve_payload(
    trajectory_path: Path,
    profile_path: Path,
    recipe_path: Path,
    group: str,
    initial_q: list[float],
    output_path: Path,
) -> dict[str, Any]:
    trajectory = CanonicalTrajectory.model_validate_json(
        trajectory_path.read_text(encoding="utf-8")
    )
    profile = RobotProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    recipe = Recipe.model_validate_json(recipe_path.read_text(encoding="utf-8"))
    if recipe.input_sha256.lower() != sha256_bytes(trajectory_path.read_bytes()):
        raise ValueError("recipe input_sha256 does not match the trajectory file")
    if recipe.robot_id != profile.robot_id:
        raise ValueError("recipe robot_id does not match the robot profile")
    if group not in trajectory.stream_names:
        raise ValueError(f"trajectory stream is not present: {group}")

    from retargetlab.kinematics.pink_backend import PinkBackend

    backend = PinkBackend(profile)
    if recipe.backend_name != backend.name:
        raise ValueError("recipe backend_name does not match the selected backend")
    if recipe.backend_version != backend.version:
        raise ValueError("recipe backend_version does not match the selected backend")
    results = backend.solve_sequence(
        group,
        [frame.poses[group] for frame in trajectory.frames],
        initial_q,
        recipe.solve_options,
    )
    payload = {
        "schema_version": "0.1",
        "recipe_sha256": recipe_sha256(recipe),
        "backend_name": backend.name,
        "backend_version": backend.version,
        "robot_id": profile.robot_id,
        "group": group,
        "frame_count": len(results),
        "results": [result.model_dump(mode="json") for result in results],
    }
    with output_path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return {
        "command": "solve",
        "status": "SOLVED",
        "output": output_path.name,
        "frame_count": len(results),
        "converged_count": sum(result.status.value == "CONVERGED" for result in results),
        "recipe_sha256": payload["recipe_sha256"],
    }


def _solve_run_payload(
    trajectory_path: Path,
    profile_path: Path,
    recipe_path: Path,
    group: str,
    initial_q: list[float],
    project_dir: Path,
    run_id: str,
) -> tuple[dict[str, Any], int]:
    trajectory = CanonicalTrajectory.model_validate_json(
        trajectory_path.read_text(encoding="utf-8")
    )
    profile = RobotProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    recipe = Recipe.model_validate_json(recipe_path.read_text(encoding="utf-8"))
    result = execute_solve_run(
        project_dir,
        run_id,
        trajectory,
        profile,
        recipe,
        group,
        initial_q,
        input_sha256=sha256_bytes(trajectory_path.read_bytes()),
    )
    payload = {
        "command": "solve",
        "status": "RUN_COMPLETED",
        "run_id": run_id,
        "quality_status": result.report.status,
        "frame_count": len(result.results),
        "converged_count": sum(item.status.value == "CONVERGED" for item in result.results),
        "recipe_sha256": result.manifest.recipe_sha256,
        "report_sha256": result.manifest.report_sha256,
    }
    return payload, EXIT_QUALITY if result.report.status == "FAIL" else EXIT_OK


def _emit(payload: dict[str, Any], as_json: bool, stdout: TextIO) -> None:
    if as_json:
        json.dump(payload, stdout, ensure_ascii=False, sort_keys=True)
        stdout.write("\n")
        return
    if payload.get("status") == "INVALID_INPUT":
        print(f"{payload['command']}: invalid input: {payload['error']}", file=sys.stderr)
        return
    if payload.get("status") == "ENVIRONMENT_ERROR":
        print(f"{payload['command']}: environment error: {payload['error']}", file=sys.stderr)
        return
    if payload.get("command") == "doctor":
        print(f"retargetlab doctor: {payload['status']}", file=stdout)
        for name, details in payload["dependencies"].items():
            print(f"{name}: {details['status']}", file=sys.stderr)
        return
    if payload.get("command") == "diagnose":
        print(
            f"diagnostic report: {payload['status']} ({payload['episode_count']} episodes)",
            file=stdout,
        )
        return
    if payload.get("kind") == "parquet":
        print(
            f"parquet structure: {payload['row_count']} rows, {len(payload['fields'])} fields",
            file=stdout,
        )
        comparison = payload.get("comparison")
        if comparison is not None:
            status = (
                "FULLY_VERIFIED"
                if comparison["fully_verified"]
                else "COMPATIBLE_UNVERIFIED"
                if comparison["compatible"]
                else "INCONSISTENT"
            )
            print(f"metadata comparison: {status}", file=stdout)
        return
    if payload.get("kind") == "lerobot-info":
        print(
            f"metadata manifest: {payload['total_frames']} frames, "
            f"{len(payload['features'])} features",
            file=stdout,
        )
        return
    if payload.get("command") == "scan-coverage":
        print(
            f"dataset coverage: {payload['status']} "
            f"({payload['observed_episode_count']} episodes, "
            f"{payload['observed_frame_count']} frames) -> {payload['output']}",
            file=stdout,
        )
        return
    if payload.get("command") == "build-robot-profile":
        print(
            f"robot profile: {payload['robot_id']} -> {payload['output']} "
            f"({payload['profile_sha256']})",
            file=stdout,
        )
        return
    if payload.get("command") == "map-grippers":
        print(
            f"target grippers: {payload['frame_count']} frames -> {payload['output']} "
            f"({payload['profile_sha256']})",
            file=stdout,
        )
        return
    if payload.get("command") == "build-replay-manifest":
        print(
            f"replay manifest: {payload['replay_id']} -> {payload['output']} "
            f"({payload['frame_count']} frames)",
            file=stdout,
        )
        return
    if payload.get("command") == "verify-replay-manifest":
        print(
            f"replay manifest: {payload['replay_id']} VERIFIED ({payload['frame_count']} frames)",
            file=stdout,
        )
        return
    if payload.get("command") == "candidate":
        print(
            f"mapping candidate: {payload['status']} "
            f"({len(payload['mapping']['streams'])} streams)",
            file=stdout,
        )
        return
    if payload.get("command") == "review-mapping":
        print(f"mapping review: {payload['status']}", file=stdout)
        return
    if payload.get("command") == "inspect-review-package":
        print(
            f"review package: {payload['status']} (next={payload['next_action']})",
            file=stdout,
        )
        return
    if payload.get("command") == "verify-review-package":
        print(
            f"review package preflight: {payload['status']} ({payload['inspection_status']})",
            file=stdout,
        )
        return
    if payload.get("command") == "calibrate":
        print(
            f"calibration: {payload['status']} "
            f"({payload['frame_count']} frames) -> {payload['output']}",
            file=stdout,
        )
        return
    if payload.get("command") == "analyze-timing":
        print(
            f"command timing: {payload['status']} "
            f"(best shift={payload['best_shift']}) -> {payload['output']}",
            file=stdout,
        )
        return
    if payload.get("command") == "verify-calibration":
        print(
            f"calibration run: {payload['status']} ({payload['selected_frame_count']} frames)",
            file=stdout,
        )
        return
    if payload.get("command") == "verify-profile":
        print(
            f"data profile: {payload['profile_status']} "
            f"(decision_verified={payload['decision_verified']})",
            file=stdout,
        )
        return
    if payload.get("command") == "validate-input":
        print(
            f"input mapping: {'VALID' if payload['valid'] else 'INVALID'}",
            file=stdout,
        )
        return
    if payload.get("command") == "normalize":
        print(
            f"normalized trajectory: {payload['frame_count']} frames -> {payload['output']}",
            file=stdout,
        )
        return
    if payload.get("command") == "solve":
        if payload.get("status") == "RUN_COMPLETED":
            print(
                f"run completed: {payload['converged_count']}/{payload['frame_count']} "
                f"converged, quality={payload['quality_status']}",
                file=stdout,
            )
            return
        print(
            f"solved trajectory: {payload['converged_count']}/{payload['frame_count']} "
            f"converged -> {payload['output']}",
            file=stdout,
        )
        return
    print(
        f"canonical trajectory: {payload['frame_count']} frames, "
        f"streams={','.join(payload['stream_names'])}",
        file=stdout,
    )


def app(argv: list[str] | None = None) -> int:
    """Run the CLI and return a documented process exit code."""

    args = _parser().parse_args(argv)
    if args.command == "doctor":
        payload, exit_code = _doctor_payload()
        _emit(payload, args.json, sys.stdout)
        return exit_code
    if args.command == "inspect":
        try:
            payload = _inspect_payload(
                args.path,
                args.dataset_alias,
                args.source_revision,
                args.metadata,
            )
        except RuntimeError as exc:
            error = {"command": "inspect", "status": "ENVIRONMENT_ERROR", "error": str(exc)}
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, ValidationError, ValueError) as exc:
            error = {"command": "inspect", "status": "INVALID_INPUT", "error": str(exc)}
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "scan-coverage":
        try:
            payload, exit_code = _coverage_payload(
                info_path=args.info,
                data_path=args.data,
                episodes_path=args.episodes,
                tasks_path=args.tasks,
                stats_path=args.stats,
                dataset_alias=args.dataset_alias,
                source_revision=args.source_revision,
                validation_scope=args.validation_scope,
                output_path=args.output,
            )
        except RuntimeError as exc:
            error = {
                "command": "scan-coverage",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "scan-coverage",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return exit_code
    if args.command == "build-robot-profile":
        try:
            payload = _robot_profile_payload(
                robot_id=args.robot,
                asset_dir=args.asset_dir,
                output_path=args.output,
            )
        except RuntimeError as exc:
            error = {
                "command": "build-robot-profile",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "build-robot-profile",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "build-export-profile":
        try:
            payload = _export_profile_payload(
                profile_path=args.profile,
                output_path=args.output,
            )
        except RuntimeError as exc:
            error = {
                "command": "build-export-profile",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "build-export-profile",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "map-grippers":
        try:
            payload = _map_grippers_payload(
                trajectory_path=args.trajectory,
                profile_path=args.profile,
                raw_bindings=args.binding,
                output_path=args.output,
            )
        except RuntimeError as exc:
            error = {
                "command": "map-grippers",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "map-grippers",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "build-replay-manifest":
        try:
            payload = _replay_manifest_payload(
                replay_id=args.replay_id,
                trajectory_path=args.trajectory,
                profile_path=args.profile,
                recipe_path=args.recipe,
                arm_solve_paths=args.arm_solve,
                target_grippers_path=args.target_grippers,
                coupling=args.coupling,
                output_path=args.output,
            )
        except RuntimeError as exc:
            error = {
                "command": "build-replay-manifest",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "build-replay-manifest",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "verify-replay-manifest":
        try:
            payload = _verify_replay_payload(args.manifest)
        except RuntimeError as exc:
            error = {
                "command": "verify-replay-manifest",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "verify-replay-manifest",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "materialize-replay":
        try:
            payload = _materialize_replay_payload(
                manifest_path=args.manifest,
                export_profile_path=args.export_profile,
                stream_name=args.stream,
                output_path=args.output,
            )
        except RuntimeError as exc:
            error = {
                "command": "materialize-replay",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "materialize-replay",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "verify-target-replay":
        try:
            payload = _verify_target_replay_payload(args.artifact)
        except RuntimeError as exc:
            error = {
                "command": "verify-target-replay",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "verify-target-replay",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "build-replay-bundle":
        try:
            payload = _build_replay_bundle_payload(
                observation_state_path=args.observation_state,
                action_path=args.action,
                output_path=args.output,
            )
        except RuntimeError as exc:
            error = {
                "command": "build-replay-bundle",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "build-replay-bundle",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "verify-replay-bundle":
        try:
            payload = _verify_replay_bundle_payload(args.bundle)
        except RuntimeError as exc:
            error = {
                "command": "verify-replay-bundle",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "verify-replay-bundle",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "verify-export-inputs":
        try:
            payload = _verify_export_inputs_payload(
                data_profile_path=args.data_profile,
                decision_path=args.decision,
                coverage_path=args.coverage,
                target_replay_bundle_path=args.target_replay_bundle,
                export_profile_path=args.export_profile,
                episode_indices=args.episode_indices,
                output_path=args.output,
            )
        except RuntimeError as exc:
            error = {
                "command": "verify-export-inputs",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "verify-export-inputs",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "write-synthetic-table":
        try:
            payload = _write_synthetic_table_payload(
                source_path=args.source,
                target_replay_bundle_path=args.target_replay_bundle,
                output_path=args.output,
                preflight_path=args.preflight,
                report_path=args.report,
            )
        except RuntimeError as exc:
            error = {
                "command": "write-synthetic-table",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "write-synthetic-table",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "verify-synthetic-table":
        try:
            payload = _verify_synthetic_table_payload(
                source_path=args.source,
                target_replay_bundle_path=args.target_replay_bundle,
                output_path=args.output,
                preflight_path=args.preflight,
                report_path=args.report,
            )
        except RuntimeError as exc:
            error = {
                "command": "verify-synthetic-table",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "verify-synthetic-table",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "build-synthetic-table-preflight":
        try:
            payload = _build_synthetic_preflight_payload(
                export_input_gate_path=args.export_input_gate,
                source_path=args.source,
                target_replay_bundle_path=args.target_replay_bundle,
                output_table_path=args.output_table,
                output_path=args.output,
            )
        except RuntimeError as exc:
            error = {
                "command": "build-synthetic-table-preflight",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "build-synthetic-table-preflight",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "verify-synthetic-table-preflight":
        try:
            payload = _verify_synthetic_preflight_payload(args.preflight)
        except RuntimeError as exc:
            error = {
                "command": "verify-synthetic-table-preflight",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "verify-synthetic-table-preflight",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "build-lerobot-metadata-plan":
        try:
            payload = _build_lerobot_plan_payload(
                export_input_gate_path=args.export_input_gate,
                export_profile_path=args.export_profile,
                fps=args.fps,
                features_path=args.features,
                tasks_path=args.tasks,
                episodes_path=args.episodes,
                output_path=args.output,
            )
        except RuntimeError as exc:
            error = {
                "command": "build-lerobot-metadata-plan",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "build-lerobot-metadata-plan",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "verify-lerobot-metadata-plan":
        try:
            payload = _verify_lerobot_plan_payload(args.plan)
        except RuntimeError as exc:
            error = {
                "command": "verify-lerobot-metadata-plan",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "verify-lerobot-metadata-plan",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "write-lerobot-metadata-skeleton":
        try:
            payload = _write_lerobot_skeleton_payload(
                plan_path=args.plan,
                output_root=args.output_root,
                report_path=args.report,
            )
        except RuntimeError as exc:
            error = {
                "command": "write-lerobot-metadata-skeleton",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "write-lerobot-metadata-skeleton",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "verify-lerobot-metadata-skeleton":
        try:
            payload = _verify_lerobot_skeleton_payload(
                plan_path=args.plan,
                output_root=args.output_root,
            )
        except RuntimeError as exc:
            error = {
                "command": "verify-lerobot-metadata-skeleton",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "verify-lerobot-metadata-skeleton",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "write-lerobot-partial-dataset":
        try:
            payload = _write_lerobot_partial_payload(
                plan_path=args.plan,
                output_root=args.output_root,
                target_table_report_path=args.target_table_report,
                report_path=args.report,
            )
        except RuntimeError as exc:
            error = {
                "command": "write-lerobot-partial-dataset",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "write-lerobot-partial-dataset",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "verify-lerobot-partial-dataset":
        try:
            payload = _verify_lerobot_partial_payload(
                plan_path=args.plan,
                output_root=args.output_root,
                target_table_report_path=args.target_table_report,
            )
        except RuntimeError as exc:
            error = {
                "command": "verify-lerobot-partial-dataset",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "verify-lerobot-partial-dataset",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "candidate":
        try:
            payload = _candidate_payload(
                args.metadata,
                args.dataset_alias,
                args.source_revision,
            )
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {"command": "candidate", "status": "INVALID_INPUT", "error": str(exc)}
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "review-mapping":
        try:
            payload = _review_mapping_payload(
                args.candidate,
                args.review,
                args.comparison,
                args.output,
            )
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {"command": "review-mapping", "status": "INVALID_INPUT", "error": str(exc)}
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "inspect-review-package":
        try:
            payload = _inspect_review_package_payload(
                args.candidate,
                args.review,
                args.comparison,
                args.output,
            )
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "inspect-review-package",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_SEMANTIC if payload["status"] == "BLOCKED" else EXIT_OK
    if args.command == "verify-review-package":
        try:
            payload = _verify_review_package_payload(
                args.preflight,
                args.candidate,
                args.review,
                args.comparison,
            )
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "verify-review-package",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "calibrate":
        try:
            payload = _calibrate_payload(
                data_path=args.data,
                episodes_path=args.episodes,
                candidate_path=args.candidate,
                review_path=args.review,
                comparison_path=args.comparison,
                decision_path=args.decision,
                profile_path=args.profile,
                episode_indices=args.episode_indices,
                frames_per_episode=args.frames_per_episode,
                max_frames=args.max_frames,
                output_path=args.output,
            )
        except RuntimeError as exc:
            error = {"command": "calibrate", "status": "ENVIRONMENT_ERROR", "error": str(exc)}
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {"command": "calibrate", "status": "INVALID_INPUT", "error": str(exc)}
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "verify-calibration":
        try:
            payload = _verify_calibration_payload(args.run, args.decision)
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "verify-calibration",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "verify-profile":
        try:
            payload = _verify_profile_payload(args.profile, args.decision)
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "verify-profile",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "analyze-timing":
        try:
            payload, exit_code = _timing_payload(
                data_path=args.data,
                dataset_alias=args.dataset_alias,
                source_revision=args.source_revision,
                episode_indices=args.episode_indices,
                joint_indices=args.joint_indices,
                action_scales=args.action_scales,
                action_offsets=args.action_offsets,
                max_shift=args.max_shift,
                expected_shifts=args.expected_shifts,
                output_path=args.output,
            )
        except RuntimeError as exc:
            error = {
                "command": "analyze-timing",
                "status": "ENVIRONMENT_ERROR",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "analyze-timing",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return exit_code
    if args.command == "diagnose":
        try:
            payload, exit_code = _diagnose_payload(args.run)
        except (OSError, ValidationError, ValueError) as exc:
            error = {"command": "diagnose", "status": "INVALID_INPUT", "error": str(exc)}
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return exit_code
    if args.command == "validate-input":
        try:
            payload, exit_code = _validate_input_payload(args.manifest, args.spec)
        except (OSError, ValidationError, ValueError) as exc:
            error = {
                "command": "validate-input",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return exit_code
    if args.command == "normalize":
        try:
            payload = _normalize_payload(
                args.rows,
                args.spec,
                args.profile,
                args.decision,
                args.output,
            )
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {
                "command": "normalize",
                "status": "INVALID_INPUT",
                "error": str(exc),
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return EXIT_OK
    if args.command == "solve":
        if args.output is None and args.run_id is None:
            error = {
                "command": "solve",
                "status": "INVALID_INPUT",
                "error": "--run-id is required with --project",
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        if args.output is not None and args.run_id is not None:
            error = {
                "command": "solve",
                "status": "INVALID_INPUT",
                "error": "--run-id is only valid with --project",
            }
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        try:
            if args.output is not None:
                payload = _solve_payload(
                    args.trajectory,
                    args.profile,
                    args.recipe,
                    args.group,
                    args.initial_q,
                    args.output,
                )
                exit_code = EXIT_OK
            else:
                payload, exit_code = _solve_run_payload(
                    args.trajectory,
                    args.profile,
                    args.recipe,
                    args.group,
                    args.initial_q,
                    args.project,
                    args.run_id,
                )
        except RuntimeError as exc:
            error = {"command": "solve", "status": "ENVIRONMENT_ERROR", "error": str(exc)}
            _emit(error, args.json, sys.stdout)
            return EXIT_ENVIRONMENT
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            error = {"command": "solve", "status": "INVALID_INPUT", "error": str(exc)}
            _emit(error, args.json, sys.stdout)
            return EXIT_SEMANTIC
        _emit(payload, args.json, sys.stdout)
        return exit_code
    return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(app())
