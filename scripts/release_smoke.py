"""Exercise installed wheels outside the checkout with a pinned public model."""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--process-python", type=Path, required=True)
    parser.add_argument("--reader-python", type=Path, required=True)
    parser.add_argument("--openarm-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    process_python = args.process_python.absolute()
    reader_python = args.reader_python.absolute()
    source, output = args.openarm_source.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["OPENBLAS_NUM_THREADS"] = "1"
    records = []

    def run(label, command, reader=False):
        python = reader_python if reader else process_python
        start = time.perf_counter()
        result = subprocess.run(
            [str(python), "-m", "retargetlab", *command, "--json"],
            cwd=output,
            env=env,
            text=True,
            capture_output=True,
        )
        (output / f"{label}.stdout").write_text(result.stdout)
        (output / f"{label}.stderr").write_text(result.stderr)
        if result.returncode:
            raise RuntimeError(f"{label} exited {result.returncode}; see {output}/{label}.stderr")
        payload = json.loads(result.stdout)
        record = {
            "command": label,
            "status": payload["status"],
            "elapsed_s": time.perf_counter() - start,
        }
        records.append(record)
        print(json.dumps(record), flush=True)
        return payload

    run("doctor-process", ["doctor", "--scope", "pipeline"])
    run("doctor-reader", ["doctor", "--scope", "reader"], reader=True)
    demo = output / "demo"
    run("demo", ["demo-init", "--openarm-source", str(source), "--output", str(demo)])
    run(
        "model",
        [
            "build-mujoco-model",
            "--profile",
            str(demo / "robot-profile.json"),
            "--output",
            str(demo / "mujoco"),
            "--kinematic-inertia-repair",
        ],
    )
    views = []
    for backend in ("pink", "mink"):
        processed, dataset = demo / f"processed-{backend}", demo / f"dataset-{backend}"
        run(
            f"process-{backend}",
            [
                "process",
                "--config",
                str(demo / f"process-{backend}.json"),
                "--output",
                str(processed),
            ],
        )
        exported = run(
            f"export-{backend}",
            [
                "training-export",
                "--processing-run",
                str(processed),
                "--policy",
                str(demo / "quality-policy.json"),
                "--output",
                str(dataset),
            ],
        )
        assert exported["frames"] == 192 and exported["eligible_paired_rows"] == 190
        assert exported["videos_copied"] == 6
        checked = run(
            f"reader-{backend}",
            [
                "verify-reader",
                "--dataset",
                str(dataset),
                "--output",
                str(output / f"reader-{backend}.json"),
            ],
            reader=True,
        )
        assert checked["status"] == "PASSED" and checked["masked_training_windows"] == 130
        assert len(checked["image_shapes"]) == 3
        views.append(
            {
                "id": f"demo-{backend}",
                "processing_run": str(processed),
                "quality_dataset": str(dataset),
                "model": str(demo / "mujoco"),
                "label": f"Synthetic public demo / {backend}",
            }
        )
    config = output / "replay.json"
    config.write_text(json.dumps(views, indent=2) + "\n")
    replay = run(
        "replay", ["replay-build", "--config", str(config), "--output", str(output / "replay")]
    )
    assert replay["views"] == 2 and replay["stream_frames"] == 768
    report = {
        "status": "PASS",
        "data": "synthetic; public OpenArm model",
        "PYTHONPATH_removed": True,
        "commands": records,
    }
    (output / "smoke-report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
