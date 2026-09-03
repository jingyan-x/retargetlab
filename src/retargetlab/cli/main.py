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
    MappingReview,
    MappingSpec,
    Recipe,
    RobotProfile,
    StructureComparison,
    StructureManifest,
)
from retargetlab.io import (
    DEFAULT_CALIBRATION_COLUMNS,
    apply_mapping_review,
    build_pose_mapping_candidate,
    compare_info_to_structure,
    inspect_review_package,
    normalize_rows,
    probe_lerobot_info,
    probe_parquet,
    run_parquet_calibration,
    validate_mapping,
)
from retargetlab.robot.assets import sha256_file
from retargetlab.run import (
    canonical_json_bytes,
    execute_solve_run,
    recipe_sha256,
    verify_calibration_run,
    write_calibration_run,
    write_review_package_preflight,
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

    inspect = subparsers.add_parser(
        "inspect", help="inspect a canonical JSON trajectory or source structure"
    )
    inspect.add_argument("path", type=Path)
    inspect.add_argument("--dataset-alias")
    inspect.add_argument("--source-revision")
    inspect.add_argument("--metadata", type=Path, help="LeRobot info.json for Parquet comparison")
    inspect.add_argument("--json", action="store_true", help="emit JSON to stdout")

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

    calibrate = subparsers.add_parser(
        "calibrate", help="run a bounded approved calibration and write an audit artifact"
    )
    calibrate.add_argument("--data", required=True, type=Path)
    calibrate.add_argument("--episodes", required=True, type=Path)
    calibrate.add_argument("--candidate", required=True, type=Path)
    calibrate.add_argument("--review", required=True, type=Path)
    calibrate.add_argument("--comparison", required=True, type=Path)
    calibrate.add_argument("--episode-indices", required=True, nargs="+", type=int)
    calibrate.add_argument("--frames-per-episode", required=True, type=int)
    calibrate.add_argument("--max-frames", default=60, type=int)
    calibrate.add_argument("--output", required=True, type=Path)
    calibrate.add_argument("--json", action="store_true", help="emit JSON to stdout")

    verify_calibration = subparsers.add_parser(
        "verify-calibration", help="verify a bounded calibration artifact set"
    )
    verify_calibration.add_argument("--run", required=True, type=Path)
    verify_calibration.add_argument("--json", action="store_true", help="emit JSON to stdout")

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
    normalize.add_argument("--spec", required=True, type=Path)
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
) -> dict[str, Any]:
    approved, comparison = _load_reviewed_mapping(candidate_path, review_path, comparison_path)
    return {
        "command": "review-mapping",
        "status": "APPROVED",
        "comparison": comparison.model_dump(mode="json"),
        "mapping": approved.model_dump(mode="json"),
    }


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


def _calibrate_payload(
    *,
    data_path: Path,
    episodes_path: Path,
    candidate_path: Path,
    review_path: Path,
    comparison_path: Path,
    episode_indices: list[int],
    frames_per_episode: int,
    max_frames: int,
    output_path: Path,
) -> dict[str, Any]:
    mapping, comparison = _load_reviewed_mapping(
        candidate_path,
        review_path,
        comparison_path,
    )
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
    }


def _verify_calibration_payload(run_path: Path) -> dict[str, Any]:
    verification = verify_calibration_run(run_path)
    return {
        "command": "verify-calibration",
        **verification.model_dump(mode="json"),
    }


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
    spec_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    raw_rows = json.loads(rows_path.read_text(encoding="utf-8"))
    if not isinstance(raw_rows, list) or not all(isinstance(row, dict) for row in raw_rows):
        raise ValueError("rows JSON must be a list of objects")
    spec = MappingSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
    trajectory = normalize_rows(raw_rows, spec)
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
    if payload.get("command") == "calibrate":
        print(
            f"calibration: {payload['status']} "
            f"({payload['frame_count']} frames) -> {payload['output']}",
            file=stdout,
        )
        return
    if payload.get("command") == "verify-calibration":
        print(
            f"calibration run: {payload['status']} ({payload['selected_frame_count']} frames)",
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
            payload = _review_mapping_payload(args.candidate, args.review, args.comparison)
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
    if args.command == "calibrate":
        try:
            payload = _calibrate_payload(
                data_path=args.data,
                episodes_path=args.episodes,
                candidate_path=args.candidate,
                review_path=args.review,
                comparison_path=args.comparison,
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
            payload = _verify_calibration_payload(args.run)
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
            payload = _normalize_payload(args.rows, args.spec, args.output)
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
