"""Merge independent full-candidate M-1 reports into one audited result."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read full report: {path.name}") from exc
    if not isinstance(report, dict):
        raise ValueError("full report must be a JSON object")
    return report


def merge_reports(paths: list[Path]) -> dict[str, Any]:
    if not paths:
        raise ValueError("at least one full report is required")
    first = read_report(paths[0])
    if first.get("status") != "PASS" or first.get("run_mode") != "full_candidate":
        raise ValueError("all inputs must be PASS full_candidate reports")
    recipe_id = first.get("recipe_id")
    dataset = first.get("dataset")
    prescreen_source = first.get("prescreen_source")
    candidates: dict[str, dict[str, Any]] = {}
    input_hashes: list[str] = []
    for path in paths:
        report = read_report(path)
        input_hashes.append(sha256_file(path))
        if report.get("status") != "PASS" or report.get("run_mode") != "full_candidate":
            raise ValueError("all inputs must be PASS full_candidate reports")
        if report.get("recipe_id") != recipe_id or report.get("dataset") != dataset:
            raise ValueError("full inputs use different recipes or datasets")
        if report.get("prescreen_source") != prescreen_source:
            raise ValueError("full inputs do not share one frozen prescreen")
        if any(
            bool(report.get(field))
            for field in (
                "held_out_values_read",
                "private_values_emitted",
                "source_paths_emitted",
            )
        ):
            raise ValueError("full input violates the private-data output policy")
        full = report.get("full_candidates", [])
        if not isinstance(full, list) or len(full) != 1:
            raise ValueError("each full input must contain exactly one candidate")
        summary = full[0]
        candidate_id = summary.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id in candidates:
            raise ValueError("full inputs contain duplicate candidate IDs")
        if "full_single_frames" not in summary or "full_continuous_segments" not in summary:
            raise ValueError("full input candidate is missing aggregate metrics")
        candidates[candidate_id] = summary

    merged = copy.deepcopy(first)
    merged["run_mode"] = "full_budget"
    merged["full_candidates"] = sorted(
        candidates.values(),
        key=lambda item: (
            -item["full_single_frames"]["nominal_rate"],
            -item["full_continuous_segments"]["segment_rate"],
            -item["full_single_frames"]["mean_joint_limit_margin"],
            item["candidate_id"],
        ),
    )
    merged["full_evaluation"] = {
        "mode": "merged_single_candidate_reports",
        "candidate_count": len(candidates),
    }
    merged["full_source"] = {
        "mode": "merged_candidate_reports",
        "input_report_sha256": sorted(input_hashes),
    }
    best = merged["full_candidates"][0]
    merged["best_candidate_id"] = best["candidate_id"]
    merged["gate"] = best.get("gate", merged.get("gate"))
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = merge_reports([path.resolve() for path in args.input])
    except (OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "failures": [str(exc)]}, indent=2))
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
