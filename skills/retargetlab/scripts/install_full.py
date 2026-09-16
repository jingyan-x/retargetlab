"""Install the complete supported RetargetLab runtime, or check it without changes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

VERSION = "0.1.0rc4"
KIT = f"retargetlab-{VERSION}-kit.zip"
KIT_SHA256 = "c544c6c18f2a439283a2c935abeda8823caa528d17f20e5b5b5fd96a24b46e3f"
WHEEL = f"retargetlab-{VERSION}-py3-none-any.whl"
WHEEL_SHA256 = "f53249bc328f5ede506c51472a2ccf59e222d98f024cf533978d3ea664941761"
URL = f"https://github.com/jingyan-x/retargetlab/releases/download/v{VERSION}/{KIT}"
PROCESS_EXTRAS = "pipeline,collision-mesh,viz"


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def environment():
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["MPLBACKEND"] = "Agg"
    return env


def command(args, cwd, log=None):
    result = subprocess.run(
        [str(value) for value in args],
        cwd=cwd,
        env=environment(),
        text=True,
        capture_output=True,
    )
    if log is not None:
        Path(log).write_text(result.stdout + "\n" + result.stderr)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"{args[0]} exited {result.returncode}: {detail[-1800:]}")
    return result.stdout


def check(prefix):
    """Read-only verification: never installs, updates, or writes to either environment."""
    prefix = Path(prefix).resolve()
    manifest_path = prefix / "installation.json"
    if not manifest_path.is_file():
        raise ValueError(
            "installation.json missing; select a complete installation or request installation"
        )
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("version") != VERSION or manifest.get("status") != "COMPLETE":
        raise ValueError(f"this skill verifies complete installations of {VERSION}")
    checks = {}
    modules = {
        "process": [
            "pinocchio",
            "pink",
            "mujoco",
            "mink",
            "coacd",
            "matplotlib.pyplot",
            "pyarrow",
            "yaml",
            "xacro",
            "trimesh",
            "collada",
            "PIL",
            "av",
            "daqp",
            "osqp",
        ],
        "reader": [
            "lerobot.datasets.lerobot_dataset",
            "torch",
            "torchvision",
            "datasets",
            "pyarrow",
            "pandas",
            "av",
        ],
    }
    for name in ("process", "reader"):
        python = prefix / name / "bin/python"
        if not python.is_file():
            raise ValueError(f"missing {name} interpreter: {python}")
        version = command([python, "-B", "-m", "retargetlab", "--version"], prefix).strip()
        if version != f"retargetlab {VERSION}":
            raise ValueError(f"unexpected {name} CLI version: {version}")
        command([python, "-B", "-m", "pip", "check"], prefix)
        probe = (
            "import importlib,json; "
            f"names={modules[name]!r}; "
            "[importlib.import_module(n) for n in names]; print(json.dumps(names))"
        )
        command([python, "-B", "-c", probe], prefix)
        scope = "pipeline" if name == "process" else "reader"
        doctor = json.loads(
            command(
                [python, "-B", "-m", "retargetlab", "doctor", "--scope", scope, "--json"], prefix
            )
        )
        checks[name] = {
            "python": str(python),
            "version": version,
            "doctor": doctor,
            "imported_modules": modules[name],
            "pip_check": "PASSED",
        }
    return {
        "status": "PASSED",
        "version": VERSION,
        "prefix": str(prefix),
        "full_runtime": True,
        "environment_mutated": False,
        "checks": checks,
    }


def install(prefix, kit_path=None):
    prefix = Path(prefix).resolve()
    if (
        sys.version_info[:2] != (3, 12)
        or platform.system() != "Linux"
        or platform.machine() != "x86_64"
    ):
        raise ValueError("supported installation host is Linux x86_64 with Python 3.12")
    if prefix.exists():
        raise ValueError(
            "installation prefix already exists; use --check or select a new installation directory"
        )
    local_kit = Path(kit_path).resolve() if kit_path else None
    if local_kit and not local_kit.is_file():
        raise ValueError("provided release kit does not exist")
    prefix.mkdir(parents=True)
    logs = prefix / "logs"
    logs.mkdir()
    step = "release archive"
    try:
        archive_path = local_kit or prefix / KIT
        if local_kit is None:
            print(f"Downloading RetargetLab {VERSION} release kit", file=sys.stderr, flush=True)
            request = urllib.request.Request(URL, headers={"User-Agent": "RetargetLab-installer"})
            with (
                urllib.request.urlopen(request, timeout=60) as source,
                archive_path.open("wb") as dest,
            ):
                import shutil

                shutil.copyfileobj(source, dest)
        if digest(archive_path) != KIT_SHA256:
            raise ValueError("release kit SHA256 mismatch; refusing installation")
        release = prefix / "release"
        release.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                if not (release / member.filename).resolve().is_relative_to(release):
                    raise ValueError("release archive contains an escaping path")
            archive.extractall(release)
        wheel = release / "dist" / WHEEL
        if digest(wheel) != WHEEL_SHA256:
            raise ValueError("release wheel SHA256 mismatch")
        commands = [
            ("create-process", [sys.executable, "-m", "venv", prefix / "process"]),
            ("create-reader", [sys.executable, "-m", "venv", prefix / "reader"]),
        ]
        for step, args in commands:
            print(step, file=sys.stderr, flush=True)
            command(args, prefix, logs / f"{step}.log")
        process = prefix / "process/bin/python"
        reader = prefix / "reader/bin/python"
        commands = [
            (
                "install-process",
                [
                    process,
                    "-m",
                    "pip",
                    "install",
                    "-c",
                    release / "env/v0.1-process-linux-py312.txt",
                    f"{wheel}[{PROCESS_EXTRAS}]",
                ],
            ),
            (
                "install-reader-torch",
                [
                    reader,
                    "-m",
                    "pip",
                    "install",
                    "torch==2.7.1",
                    "torchvision==0.22.1",
                    "--index-url",
                    "https://download.pytorch.org/whl/cpu",
                ],
            ),
            (
                "install-reader",
                [
                    reader,
                    "-m",
                    "pip",
                    "install",
                    "-c",
                    release / "env/v0.1-reader-linux-py312.txt",
                    f"{wheel}[lerobot]",
                ],
            ),
        ]
        for step, args in commands:
            print(step, file=sys.stderr, flush=True)
            command(args, prefix, logs / f"{step}.log")
        manifest = {
            "status": "COMPLETE",
            "version": VERSION,
            "platform": "linux-x86_64-py312",
            "kit_sha256": KIT_SHA256,
            "wheel_sha256": WHEEL_SHA256,
            "process_extras": PROCESS_EXTRAS.split(","),
            "reader_extras": ["lerobot"],
            "process_python": str(process),
            "reader_python": str(reader),
        }
        # The checker uses the same published manifest interface as later usage.
        (prefix / "installation.json").write_text(json.dumps(manifest, indent=2))
        step = "full-runtime-check"
        report = check(prefix)
        for name, python in (("process", process), ("reader", reader)):
            (prefix / f"{name}-freeze.txt").write_text(
                command([python, "-m", "pip", "freeze"], prefix)
            )
        (prefix / "installation-check.json").write_text(json.dumps(report, indent=2))
        return {
            "status": "COMPLETE",
            "version": VERSION,
            "prefix": str(prefix),
            "manifest": str(prefix / "installation.json"),
            "full_runtime": True,
            "process_python": str(process),
            "reader_python": str(reader),
        }
    except Exception as error:
        failure = {"status": "INCOMPLETE", "step": step, "error": str(error), "full_runtime": False}
        (prefix / "installation.json").write_text(json.dumps(failure, indent=2))
        raise


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--prefix", required=True, type=Path)
    parser.add_argument(
        "--kit", type=Path, help="existing official rc4 kit; SHA256 is always checked"
    )
    parser.add_argument(
        "--check", action="store_true", help="read-only verification of a complete installation"
    )
    args = parser.parse_args()
    if args.check and args.kit:
        parser.error("--kit is only used during installation")
    try:
        result = check(args.prefix) if args.check else install(args.prefix, args.kit)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        print(json.dumps({"status": "FAILED", "error": str(error)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
