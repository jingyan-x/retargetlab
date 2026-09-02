"""M-1 environment and input-boundary check.

This is intentionally standalone: the disposable M-1 harness must not import
the formal ``src/`` package.  It reports machine-readable JSON and never emits
configured absolute paths, dataset contents, or SSH details.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CONSTRAINTS_PATH = REPO_ROOT / "env" / "constraints.txt"
OPTIONAL_DISTRIBUTIONS = {"lerobot"}
IMPORT_NAMES = {
    "pin": "pinocchio",
    "pin-pink": "pink",
    "qpsolvers": "qpsolvers",
    "osqp": "osqp",
    "pyarrow": "pyarrow",
    "pydantic": "pydantic",
}


def parse_constraints() -> dict[str, str]:
    pins: dict[str, str] = {}
    if not CONSTRAINTS_PATH.is_file():
        return pins
    for raw_line in CONSTRAINTS_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, version = line.split("==", 1)
        pins[name.strip().lower()] = version.strip()
    return pins


def distribution_status(name: str, expected: str | None) -> dict[str, Any]:
    try:
        actual = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return {
            "expected": expected,
            "actual": None,
            "status": "missing",
            "required": name not in OPTIONAL_DISTRIBUTIONS,
        }
    return {
        "expected": expected,
        "actual": actual,
        "status": "ok" if expected in (None, actual) else "mismatch",
        "required": name not in OPTIONAL_DISTRIBUTIONS,
    }


def import_status(module_name: str) -> dict[str, Any]:
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001 - doctor must summarize import errors.
        return {"status": "error", "error_type": type(exc).__name__}
    result: dict[str, Any] = {"status": "ok"}
    version = getattr(module, "__version__", None)
    if version is not None:
        result["module_version"] = str(version)
    return result


def check_configured_path(raw_path: str | None, *, kind: str) -> dict[str, Any]:
    if not raw_path:
        return {"kind": kind, "status": "not_configured"}
    path = Path(raw_path)
    exists = path.exists()
    readable = os.access(path, os.R_OK) if exists else False
    is_dir = path.is_dir() if exists else False
    return {
        "kind": kind,
        "status": "ready" if exists and readable and is_dir else "unavailable",
        "exists": exists,
        "readable": readable,
        "directory": is_dir,
    }


def check_storage(raw_root: str | None, minimum_free_gib: float) -> dict[str, Any]:
    if not raw_root:
        return {"status": "not_configured"}
    root = Path(raw_root)
    if not root.exists() or not root.is_dir():
        return {"status": "unavailable", "directory": False}
    usage = shutil.disk_usage(root)
    free_gib = usage.free / (1024**3)
    return {
        "status": "ready"
        if os.access(root, os.W_OK) and free_gib >= minimum_free_gib
        else "unavailable",
        "directory": True,
        "writable": os.access(root, os.W_OK),
        "free_gib": round(free_gib, 2),
        "minimum_free_gib": minimum_free_gib,
    }


def check_qpsolvers() -> dict[str, Any]:
    try:
        module = importlib.import_module("qpsolvers")
        available = sorted(str(item) for item in module.available_solvers)
    except Exception as exc:  # noqa: BLE001 - doctor must summarize import errors.
        return {"status": "error", "error_type": type(exc).__name__}
    return {
        "status": "ok" if "osqp" in available else "missing_osqp",
        "available_solvers": available,
        "required_solver": "osqp",
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    pins = parse_constraints()
    packages = {
        name: distribution_status(name, pins.get(name.lower()))
        for name in sorted(pins)
    }
    imports = {
        distribution: import_status(module)
        for distribution, module in IMPORT_NAMES.items()
    }
    python_ok = sys.version_info >= (3, 12)
    storage = check_storage(os.environ.get("RETARGETLAB_REMOTE_ROOT"), args.min_free_gib)
    dataset = check_configured_path(
        os.environ.get("RETARGETLAB_DATA_PATH"), kind=os.environ.get(
            "RETARGETLAB_DATA_ALIAS", "private-sample-20"
        )
    )
    assets = check_configured_path(
        os.environ.get("RETARGETLAB_OPENARM_ASSET_DIR"), kind="openarm-assets"
    )
    required_package_failures = [
        name
        for name, status in packages.items()
        if status["required"] and status["status"] != "ok"
    ]
    required_import_failures = [
        name for name, status in imports.items() if status["status"] != "ok"
    ]
    environment_ready = python_ok and not required_package_failures and not required_import_failures
    storage_ready = storage["status"] == "ready"
    data_ready = dataset["status"] == "ready"
    assets_ready = assets["status"] == "ready"
    required_inputs_ready = (not args.require_data or data_ready) and (
        not args.require_assets or assets_ready
    )
    overall_ready = environment_ready and storage_ready and required_inputs_ready
    if overall_ready and data_ready and assets_ready:
        overall_status = "READY_FOR_M_MINUS_1"
    elif environment_ready and storage_ready:
        overall_status = "ENV_READY_WAITING_FOR_INPUTS"
    else:
        overall_status = "NOT_READY"
    return {
        "schema_version": "m_minus_1.doctor.v1",
        "status": overall_status,
        "python": {
            "version": ".".join(str(part) for part in sys.version_info[:3]),
            "required": ">=3.12",
            "status": "ok" if python_ok else "too_old",
        },
        "storage": storage,
        "dataset": dataset,
        "assets": assets,
        "packages": packages,
        "imports": imports,
        "qpsolvers": check_qpsolvers(),
        "policy": {
            "dataset_alias": os.environ.get(
                "RETARGETLAB_DATA_ALIAS", "private-sample-20"
            ),
            "absolute_paths_emitted": False,
            "private_data_read": False,
        },
        "exit_ok": overall_ready,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="kept for CLI symmetry")
    parser.add_argument("--require-data", action="store_true")
    parser.add_argument("--require-assets", action="store_true")
    parser.add_argument("--min-free-gib", type=float, default=100.0)
    args = parser.parse_args()
    print(json.dumps(build_report(args), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if build_report(args)["exit_ok"] else 5


if __name__ == "__main__":
    raise SystemExit(main())
