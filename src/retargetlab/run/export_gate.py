"""Verify value-free prerequisites before a dataset writer can run."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from retargetlab.contracts import (
    DataProfile,
    DatasetCoverage,
    ExportInputGate,
    ExportProfile,
)
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes
from retargetlab.run.profile import verify_data_profile
from retargetlab.run.replay import verify_target_replay_trajectory


def build_export_input_gate(
    *,
    data_profile_path: Path,
    decision_path: Path,
    coverage_path: Path,
    target_replay_path: Path,
    export_profile_path: Path,
    training_episode_allowlist: Sequence[int],
) -> ExportInputGate:
    """Verify export prerequisites without opening source rows or videos."""

    data_profile = DataProfile.model_validate_json(
        data_profile_path.read_text(encoding="utf-8")
    )
    if data_profile.status != "CERTIFIED":
        raise ValueError("export input gate requires a CERTIFIED data profile")
    profile_verification = verify_data_profile(
        data_profile_path,
        decision_path=decision_path,
    )
    if profile_verification.profile_status != "CERTIFIED":
        raise ValueError("export input gate requires a CERTIFIED data profile")
    if not profile_verification.decision_verified:
        raise ValueError("export input gate requires a verified semantic decision")

    coverage = DatasetCoverage.model_validate_json(coverage_path.read_text(encoding="utf-8"))
    if coverage.status != "COMPLETE":
        raise ValueError("export input gate requires COMPLETE dataset coverage")
    if not coverage.structure_compatible or not coverage.structure_fully_verified:
        raise ValueError("export input gate requires fully verified source structure")
    if coverage.shape_unverified:
        raise ValueError("export input gate cannot accept unverified source shapes")
    if coverage.dataset_alias != data_profile.dataset_alias:
        raise ValueError("coverage dataset alias does not match data profile")
    if coverage.source_revision != data_profile.source_revision:
        raise ValueError("coverage source revision does not match data profile")
    if coverage.reader_version != data_profile.reader_version:
        raise ValueError("coverage reader version does not match data profile")
    if coverage.revision != data_profile.revision:
        raise ValueError("coverage revision hashes do not match data profile")
    coverage_sha256 = sha256_bytes(canonical_json_bytes(coverage))
    if data_profile.coverage_sha256 != coverage_sha256:
        raise ValueError("coverage hash does not match data profile")

    allowlist = tuple(training_episode_allowlist)
    if not allowlist:
        raise ValueError("training episode allowlist must not be empty")
    if len(set(allowlist)) != len(allowlist):
        raise ValueError("training episode allowlist must be unique")
    if any(index < 0 for index in allowlist):
        raise ValueError("training episode allowlist indices must be non-negative")
    covered_indices = {item.episode_index for item in coverage.episode_ranges}
    if not set(allowlist).issubset(covered_indices):
        raise ValueError("training episode allowlist contains an uncovered episode")

    export_profile = ExportProfile.model_validate_json(
        export_profile_path.read_text(encoding="utf-8")
    )
    export_profile_sha256 = sha256_bytes(canonical_json_bytes(export_profile))
    replay_verification = verify_target_replay_trajectory(target_replay_path)
    if replay_verification.export_profile_sha256 != export_profile_sha256:
        raise ValueError("target replay export profile hash does not match export profile")
    if replay_verification.robot_id != export_profile.robot_id:
        raise ValueError("target replay robot id does not match export profile")

    return ExportInputGate(
        dataset_alias=data_profile.dataset_alias,
        source_revision=data_profile.source_revision,
        data_profile_sha256=profile_verification.profile_sha256,
        coverage_sha256=coverage_sha256,
        target_replay_sha256=replay_verification.artifact_sha256,
        export_profile_sha256=export_profile_sha256,
        robot_id=export_profile.robot_id,
        source_frame_count=coverage.observed_frame_count,
        target_replay_frame_count=replay_verification.frame_count,
        training_episode_allowlist=allowlist,
        normalization_exclude=export_profile.normalization_exclude,
    )


def write_export_input_gate(path: Path, gate: ExportInputGate) -> ExportInputGate:
    """Write one value-free export preflight artifact exclusively."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(gate.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return gate
