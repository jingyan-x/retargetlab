"""Build a value-free, still-pending DataProfile for private-sample-20."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from retargetlab.contracts import (
    AffineMap,
    CommandTimingReport,
    DataProfile,
    DatasetCoverage,
    DatasetRevision,
    GripperProfile,
    MappingSpec,
    ProfileChannel,
    TimingEvidence,
)
from retargetlab.io import probe_lerobot_info
from retargetlab.robot.assets import sha256_file
from retargetlab.run import canonical_json_bytes, write_data_profile
from retargetlab.run.fingerprint import sha256_bytes


def _mapping(path: Path) -> MappingSpec:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("mapping candidate must contain a JSON object")
    return MappingSpec.model_validate(raw.get("mapping", raw))


def _timing_binding(value: str) -> tuple[str, Path]:
    group, separator, path = value.partition("=")
    if not separator or not group or not path:
        raise ValueError("timing binding must use GROUP=PATH")
    return group, Path(path)


def _gripper(slot: str) -> GripperProfile:
    eef_index = 0 if slot == "slot_0" else 8
    reference_index = 7 if slot == "slot_0" else 15
    return GripperProfile(
        slot=slot,
        observation_state=ProfileChannel(
            stream="observation.state",
            index=eef_index,
            semantics="joint_angle",
            unit="rad",
        ),
        action=ProfileChannel(
            stream="action",
            index=eef_index,
            semantics="normalized_open",
            unit="unitless",
        ),
        reference_observation_state=ProfileChannel(
            stream="observation.state.position",
            index=reference_index,
            semantics="joint_angle",
            unit="rad",
        ),
        reference_action=ProfileChannel(
            stream="action.position",
            index=reference_index,
            semantics="normalized_open",
            unit="unitless",
        ),
        observation_to_aperture=AffineMap(scale=0.2, offset=0.6),
        action_to_aperture=AffineMap(scale=1.0, offset=0.0),
    )


def build_profile(
    *,
    candidate_path: Path,
    info_path: Path,
    data_path: Path,
    episodes_path: Path,
    tasks_path: Path,
    stats_path: Path,
    coverage_path: Path | None,
    timing_bindings: tuple[tuple[str, Path], ...],
    profile_id: str,
) -> DataProfile:
    mapping = _mapping(candidate_path)
    info = probe_lerobot_info(
        info_path,
        dataset_alias=mapping.dataset_alias,
        source_revision=mapping.source_revision,
    )
    revision = DatasetRevision(
        info_sha256=info.source_sha256 or sha256_file(info_path),
        data_sha256=sha256_file(data_path),
        episodes_sha256=sha256_file(episodes_path),
        tasks_sha256=sha256_file(tasks_path),
        stats_sha256=sha256_file(stats_path),
    )
    coverage_sha256: str | None = None
    if coverage_path is not None:
        coverage = DatasetCoverage.model_validate_json(coverage_path.read_text(encoding="utf-8"))
        if coverage.status != "COMPLETE":
            raise ValueError("dataset coverage is not complete")
        if coverage.dataset_alias != mapping.dataset_alias:
            raise ValueError("coverage dataset alias does not match mapping")
        if coverage.source_revision != mapping.source_revision:
            raise ValueError("coverage source revision does not match mapping")
        if coverage.revision != revision:
            raise ValueError("coverage revision does not match profile revision")
        coverage_sha256 = sha256_bytes(canonical_json_bytes(coverage))
    timing: list[TimingEvidence] = []
    for group, path in timing_bindings:
        report = CommandTimingReport.model_validate_json(path.read_text(encoding="utf-8"))
        if report.status != "SUPPORTED":
            raise ValueError(f"timing report is not supported: {group}")
        if report.data_sha256 != revision.data_sha256:
            raise ValueError(f"timing report data hash does not match revision: {group}")
        timing.append(
            TimingEvidence(
                group=group,
                report_sha256=sha256_bytes(canonical_json_bytes(report)),
                data_sha256=report.data_sha256,
                joint_indices=report.joint_indices,
                action_scales=report.action_scales,
                action_offsets=report.action_offsets,
                expected_shift_min=report.expected_shift_min,
                expected_shift_max=report.expected_shift_max,
                observed_best_shift=report.best_shift,
                status=report.status,
            )
        )
    if not timing:
        raise ValueError("at least one supported timing report is required")
    return DataProfile(
        profile_id=profile_id,
        status="REVIEW_REQUIRED",
        dataset_alias=mapping.dataset_alias,
        source_revision=mapping.source_revision,
        storage_adapter="lerobot_v3",
        reader_version="lerobot==0.6.1",
        revision=revision,
        mapping=mapping,
        grippers=(_gripper("slot_0"), _gripper("slot_1")),
        timing=tuple(timing),
        validation_scope=(
            "private-sample-20 all accessible episodes and metadata files"
            if coverage_path is not None
            else "private-sample-20 calibration allowlist only"
        ),
        evidence_scope=(
            "info.json feature names",
            "calibration command timing reports",
            *(("all-episode dataset coverage scan",) if coverage_path is not None else ()),
        ),
        limitations=(
            "EEF frame identity remains unresolved",
            "timing evidence does not authorize row shifting",
            "source robot identity is not included in this profile",
        ),
        coverage_sha256=coverage_sha256,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--info", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--episodes", type=Path, required=True)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--timing", action="append", required=True, metavar="GROUP=PATH")
    parser.add_argument("--profile-id", default="private-sample-20-lerobot-v3")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    profile = build_profile(
        candidate_path=args.candidate,
        info_path=args.info,
        data_path=args.data,
        episodes_path=args.episodes,
        tasks_path=args.tasks,
        stats_path=args.stats,
        coverage_path=args.coverage,
        timing_bindings=tuple(_timing_binding(value) for value in args.timing),
        profile_id=args.profile_id,
    )
    write_data_profile(args.output, profile)
    print(json.dumps({"status": profile.status, "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
