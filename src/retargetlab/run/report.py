"""Write machine-readable and human-readable diagnostic reports."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path

from retargetlab.contracts import DatasetReport, RunManifest
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes
from retargetlab.run.workspace import RunWorkspace


def _write_text_exclusive(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def _write_json_exclusive(path: Path, payload: object) -> None:
    _write_text_exclusive(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _markdown(report: DatasetReport) -> str:
    lines = [
        "# RetargetLab diagnostic report",
        "",
        f"- schema_version: `{report.schema_version}`",
        f"- dataset_status: `{report.status}`",
        f"- episode_count: `{report.episode_count}`",
        "",
        "| episode | frames | nominal | relaxed | "
        "collision invalid | limit invalid | delta invalid | status |",
        "|---:|---:|---:|---:|---:|---:|---:|:---|",
    ]
    for episode in report.episodes:
        row = (
            episode.episode_index,
            episode.frame_count,
            f"{episode.nominal_rate:.3f}",
            f"{episode.relaxed_rate:.3f}",
            f"{episode.collision_fraction:.3f}",
            f"{episode.joint_limit_violation_fraction:.3f}",
            f"{episode.delta_violation_fraction:.3f}",
            f"`{episode.status}`",
        )
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines) + "\n"


def _metrics_csv(report: DatasetReport) -> str:
    rows: list[list[object]] = []
    for episode in report.episodes:
        rows.append(
            [
                episode.episode_index,
                episode.frame_count,
                episode.nominal_rate,
                episode.relaxed_rate,
                episode.collision_fraction,
                episode.joint_limit_violation_fraction,
                episode.delta_violation_fraction,
                episode.status,
            ]
        )
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "episode_index",
            "frame_count",
            "nominal_rate",
            "relaxed_rate",
            "collision_fraction",
            "joint_limit_violation_fraction",
            "delta_violation_fraction",
            "status",
        ]
    )
    writer.writerows(rows)
    return output.getvalue()


def write_dataset_report(workspace: RunWorkspace, report: DatasetReport) -> RunManifest:
    """Persist one report and completion manifest without overwriting files."""

    report_payload = report.model_dump(mode="json")
    report_digest = sha256_bytes(canonical_json_bytes(report))
    _write_json_exclusive(workspace.result_dir / "report.json", report_payload)
    _write_text_exclusive(workspace.result_dir / "report.md", _markdown(report))
    _write_text_exclusive(workspace.result_dir / "metrics.csv", _metrics_csv(report))
    metrics_lines = "".join(
        json.dumps(
            episode.model_dump(exclude={"frames"}, mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        for episode in report.episodes
    )
    _write_text_exclusive(workspace.result_dir / "metrics.jsonl", metrics_lines)

    manifest = RunManifest(
        run_id=workspace.run_id,
        recipe_sha256=workspace.recipe_sha256,
        report_sha256=report_digest,
        artifacts=(
            "recipe.json",
            "recipe.sha256",
            "result/report.json",
            "result/report.md",
            "result/metrics.csv",
            "result/metrics.jsonl",
        ),
        completed_at_utc=datetime.now(UTC).isoformat(),
    )
    _write_json_exclusive(workspace.path / "run-manifest.json", manifest.model_dump(mode="json"))
    return manifest
