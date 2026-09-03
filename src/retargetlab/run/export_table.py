"""Persist and verify synthetic table-writer preflight records."""

from __future__ import annotations

import json
from pathlib import Path

from retargetlab.contracts import (
    ExportInputGate,
    SyntheticTableWritePreflight,
    SyntheticTableWritePreflightVerification,
)
from retargetlab.robot.assets import sha256_file
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes
from retargetlab.run.replay import verify_target_replay_bundle


def build_synthetic_table_write_preflight(
    *,
    export_input_gate_path: Path,
    source_table_path: Path,
    target_replay_bundle_path: Path,
    output_table_path: Path,
) -> SyntheticTableWritePreflight:
    """Bind a synthetic table rewrite to an existing export input gate."""

    gate = ExportInputGate.model_validate_json(
        export_input_gate_path.read_text(encoding="utf-8")
    )
    if not source_table_path.is_file():
        raise FileNotFoundError(f"synthetic source table does not exist: {source_table_path}")
    if source_table_path.resolve() == output_table_path.resolve():
        raise ValueError("synthetic table source and output paths must be different")

    replay_verification = verify_target_replay_bundle(target_replay_bundle_path)
    if gate.target_replay_bundle_sha256 != replay_verification.bundle_sha256:
        raise ValueError("export input gate bundle hash does not match target replay bundle")
    if gate.robot_id != replay_verification.robot_id:
        raise ValueError("export input gate robot id does not match target replay bundle")
    if gate.export_profile_sha256 != replay_verification.export_profile_sha256:
        raise ValueError("export input gate profile hash does not match target replay bundle")
    if gate.target_replay_frame_count != replay_verification.frame_count:
        raise ValueError("export input gate frame count does not match target replay bundle")

    return SyntheticTableWritePreflight(
        export_input_gate_path=str(export_input_gate_path),
        export_input_gate_sha256=sha256_file(export_input_gate_path),
        source_table_path=str(source_table_path),
        source_table_sha256=sha256_file(source_table_path),
        target_replay_bundle_path=str(target_replay_bundle_path),
        target_replay_bundle_sha256=replay_verification.bundle_sha256,
        output_table_path=str(output_table_path),
        dataset_alias=gate.dataset_alias,
        source_revision=gate.source_revision,
        robot_id=gate.robot_id,
        replay_id=replay_verification.replay_id,
        gated_source_frame_count=gate.source_frame_count,
        target_replay_frame_count=gate.target_replay_frame_count,
        training_episode_allowlist=gate.training_episode_allowlist,
    )


def write_synthetic_table_write_preflight(
    path: Path,
    preflight: SyntheticTableWritePreflight,
) -> SyntheticTableWritePreflight:
    """Write one exclusive value-free synthetic table preflight."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(preflight.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return preflight


def verify_synthetic_table_write_preflight(
    path: Path,
) -> SyntheticTableWritePreflightVerification:
    """Rebuild a synthetic table preflight from its bound files."""

    preflight = SyntheticTableWritePreflight.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    expected = build_synthetic_table_write_preflight(
        export_input_gate_path=Path(preflight.export_input_gate_path),
        source_table_path=Path(preflight.source_table_path),
        target_replay_bundle_path=Path(preflight.target_replay_bundle_path),
        output_table_path=Path(preflight.output_table_path),
    )
    if expected != preflight:
        raise ValueError("synthetic table preflight does not match its bound inputs")
    return SyntheticTableWritePreflightVerification(
        dataset_alias=preflight.dataset_alias,
        source_revision=preflight.source_revision,
        robot_id=preflight.robot_id,
        replay_id=preflight.replay_id,
        preflight_sha256=sha256_bytes(canonical_json_bytes(preflight)),
        export_input_gate_sha256=preflight.export_input_gate_sha256,
        source_table_sha256=preflight.source_table_sha256,
        target_replay_bundle_sha256=preflight.target_replay_bundle_sha256,
        target_replay_frame_count=preflight.target_replay_frame_count,
    )
