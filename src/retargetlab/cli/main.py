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
    CanonicalTrajectory,
    DatasetReport,
    MappingSpec,
    StructureManifest,
)
from retargetlab.io import normalize_rows, validate_mapping

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

    inspect = subparsers.add_parser("inspect", help="inspect a canonical JSON trajectory")
    inspect.add_argument("path", type=Path)
    inspect.add_argument("--json", action="store_true", help="emit JSON to stdout")

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


def _inspect_payload(path: Path) -> dict[str, Any]:
    trajectory = CanonicalTrajectory.model_validate_json(path.read_text(encoding="utf-8"))
    return {
        "command": "inspect",
        "schema_version": trajectory.schema_version,
        "coordinate_frame": trajectory.coordinate_frame,
        "frame_count": trajectory.frame_count,
        "stream_names": list(trajectory.stream_names),
        "metadata_keys": sorted(trajectory.metadata),
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


def _emit(payload: dict[str, Any], as_json: bool, stdout: TextIO) -> None:
    if as_json:
        json.dump(payload, stdout, ensure_ascii=False, sort_keys=True)
        stdout.write("\n")
        return
    if payload.get("status") == "INVALID_INPUT":
        print(f"{payload['command']}: invalid input: {payload['error']}", file=sys.stderr)
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
            payload = _inspect_payload(args.path)
        except (OSError, ValidationError, ValueError) as exc:
            error = {"command": "inspect", "status": "INVALID_INPUT", "error": str(exc)}
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
    return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(app())
