"""Build and persist a metadata-only LeRobot v3 export plan."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from retargetlab.contracts import (
    ExportInputGate,
    ExportProfile,
    FeatureDeclaration,
    LeRobotEpisodeMetadata,
    LeRobotMetadataPlan,
    LeRobotMetadataPlanVerification,
    LeRobotTaskMetadata,
)
from retargetlab.robot.assets import sha256_file
from retargetlab.run.fingerprint import canonical_json_bytes, sha256_bytes


def build_lerobot_metadata_plan(
    *,
    export_input_gate_path: Path,
    export_profile_path: Path,
    fps: float,
    features: Mapping[str, FeatureDeclaration],
    tasks: Sequence[LeRobotTaskMetadata],
    episodes: Sequence[LeRobotEpisodeMetadata],
    stats_features: Sequence[str] = ("observation.state", "action"),
    video_keys: Sequence[str] = (),
    video_path_templates: Mapping[str, str] | None = None,
) -> LeRobotMetadataPlan:
    """Build a value-free v3 metadata plan without opening dataset rows/videos."""

    gate = ExportInputGate.model_validate_json(
        export_input_gate_path.read_text(encoding="utf-8")
    )
    export_profile = ExportProfile.model_validate_json(
        export_profile_path.read_text(encoding="utf-8")
    )
    export_profile_sha256 = sha256_bytes(canonical_json_bytes(export_profile))
    if gate.export_profile_sha256 != export_profile_sha256:
        raise ValueError("export input gate profile hash does not match export profile")
    if gate.robot_id != export_profile.robot_id:
        raise ValueError("export input gate robot id does not match export profile")

    episode_values = tuple(episodes)
    if sum(episode.length for episode in episode_values) != gate.target_replay_frame_count:
        raise ValueError("metadata episode lengths do not match target replay frame count")
    if tuple(episode.episode_index for episode in episode_values) != (
        tuple(gate.training_episode_allowlist)
    ):
        raise ValueError("metadata episodes must match the export gate episode allowlist")

    return LeRobotMetadataPlan(
        dataset_alias=gate.dataset_alias,
        source_revision=gate.source_revision,
        export_input_gate_path=str(export_input_gate_path),
        export_input_gate_sha256=sha256_file(export_input_gate_path),
        export_profile_path=str(export_profile_path),
        export_profile_sha256=export_profile_sha256,
        robot_id=export_profile.robot_id,
        target_layout=export_profile.target_layout,
        fps=fps,
        total_episodes=len(episode_values),
        total_frames=sum(episode.length for episode in episode_values),
        total_tasks=len(tuple(tasks)),
        features=dict(features),
        tasks=tuple(tasks),
        episodes=episode_values,
        training_episode_allowlist=tuple(gate.training_episode_allowlist),
        stats_features=tuple(stats_features),
        video_keys=tuple(video_keys),
        video_path_templates=dict(video_path_templates or {}),
    )


def write_lerobot_metadata_plan(
    path: Path,
    plan: LeRobotMetadataPlan,
) -> LeRobotMetadataPlan:
    """Write one exclusive metadata-only LeRobot plan."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(plan.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return plan


def verify_lerobot_metadata_plan(path: Path) -> LeRobotMetadataPlanVerification:
    """Rebuild a metadata plan from its gate, profile, and embedded declarations."""

    plan = LeRobotMetadataPlan.model_validate_json(path.read_text(encoding="utf-8"))
    expected = build_lerobot_metadata_plan(
        export_input_gate_path=Path(plan.export_input_gate_path),
        export_profile_path=Path(plan.export_profile_path),
        fps=plan.fps,
        features=plan.features,
        tasks=plan.tasks,
        episodes=plan.episodes,
        stats_features=plan.stats_features,
        video_keys=plan.video_keys,
        video_path_templates=plan.video_path_templates,
    )
    if expected != plan:
        raise ValueError("LeRobot metadata plan does not match its bound inputs")
    return LeRobotMetadataPlanVerification(
        dataset_alias=plan.dataset_alias,
        source_revision=plan.source_revision,
        robot_id=plan.robot_id,
        plan_sha256=sha256_bytes(canonical_json_bytes(plan)),
        export_input_gate_sha256=plan.export_input_gate_sha256,
        export_profile_sha256=plan.export_profile_sha256,
        total_episodes=plan.total_episodes,
        total_frames=plan.total_frames,
        total_tasks=plan.total_tasks,
    )
