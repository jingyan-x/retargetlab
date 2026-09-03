"""Merge disjoint M-1 prescreen reports without reading private pose values."""

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
        raise ValueError(f"cannot read prescreen report: {path.name}") from exc
    if not isinstance(report, dict):
        raise ValueError("prescreen report must be a JSON object")
    return report


def merge_reports(paths: list[Path]) -> dict[str, Any]:
    if not paths:
        raise ValueError("at least one prescreen report is required")
    first = read_report(paths[0])
    expected_recipe = first.get("recipe_id")
    expected_dataset = first.get("dataset")
    expected_budget = first.get("candidate_budget", {})
    expected_count = int(expected_budget.get("expected_candidates", -1))
    expected_frame_count = int(expected_budget.get("prescreen_frame_count", -1))
    if first.get("status") != "PASS" or first.get("run_mode") != "prescreen_only":
        raise ValueError("all prescreen inputs must be PASS prescreen_only reports")
    if expected_count < 1 or expected_frame_count < 1:
        raise ValueError("prescreen input has no valid candidate or frame budget")

    candidates: dict[str, dict[str, Any]] = {}
    input_hashes: list[str] = []
    for path in paths:
        report = read_report(path)
        input_hashes.append(sha256_file(path))
        if report.get("status") != "PASS" or report.get("run_mode") != "prescreen_only":
            raise ValueError("all prescreen inputs must be PASS prescreen_only reports")
        if report.get("recipe_id") != expected_recipe:
            raise ValueError("prescreen inputs use different recipes")
        if report.get("dataset") != expected_dataset:
            raise ValueError("prescreen inputs use different dataset hashes")
        budget = report.get("candidate_budget", {})
        if int(budget.get("expected_candidates", -1)) != expected_count:
            raise ValueError("prescreen inputs use different candidate budgets")
        if int(budget.get("prescreen_frame_count", -1)) != expected_frame_count:
            raise ValueError("prescreen inputs use different frame budgets")
        if any(
            bool(report.get(field))
            for field in (
                "held_out_values_read",
                "private_values_emitted",
                "source_paths_emitted",
            )
        ):
            raise ValueError("prescreen input violates the private-data output policy")
        for summary in report.get("candidates", []):
            candidate_id = summary.get("candidate_id")
            if not isinstance(candidate_id, str) or candidate_id in candidates:
                raise ValueError("prescreen inputs contain duplicate candidate IDs")
            if not isinstance(summary.get("prescreen"), dict):
                raise ValueError("prescreen input candidate has no metrics")
            candidates[candidate_id] = summary

    if len(candidates) != expected_count:
        raise ValueError(
            f"prescreen inputs cover {len(candidates)} of {expected_count} candidates"
        )

    merged = copy.deepcopy(first)
    merged["candidates"] = sorted(
        candidates.values(),
        key=lambda item: (
            -item["prescreen"]["nominal_rate"],
            -item["prescreen"]["mean_joint_limit_margin"],
            item["candidate_id"],
        ),
    )
    merged["full_candidates"] = []
    merged["candidate_budget"] = dict(expected_budget)
    merged["candidate_budget"]["candidates_run"] = len(candidates)
    merged["candidate_budget"]["candidate_start"] = 0
    merged["prescreen_source"] = {
        "mode": "merged_reports",
        "input_report_sha256": sorted(input_hashes),
    }
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
