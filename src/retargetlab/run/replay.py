"""Build value-free provenance for a canonical-to-target replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from retargetlab.contracts import (
    CanonicalTrajectory,
    Recipe,
    ReplayArtifact,
    RobotProfile,
    TargetGripperTrajectory,
    TargetReplayManifest,
)
from retargetlab.contracts.replay import ReplayArtifactRole
from retargetlab.robot.assets import sha256_file
from retargetlab.run.fingerprint import canonical_json_bytes, recipe_sha256, sha256_bytes


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be a JSON object: {path}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return raw


def _required_string(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} is missing a non-empty {key}")
    return value


def build_target_replay_manifest(
    *,
    replay_id: str,
    trajectory_path: Path,
    profile_path: Path,
    recipe_path: Path,
    arm_solve_path: Path,
    target_grippers_path: Path,
    coupling: str,
) -> TargetReplayManifest:
    """Cross-check replay inputs and return a value-free manifest."""

    trajectory = CanonicalTrajectory.model_validate_json(
        trajectory_path.read_text(encoding="utf-8")
    )
    profile = RobotProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    recipe = Recipe.model_validate_json(recipe_path.read_text(encoding="utf-8"))
    target_grippers = TargetGripperTrajectory.model_validate_json(
        target_grippers_path.read_text(encoding="utf-8")
    )
    solve = _read_object(arm_solve_path, "arm solve artifact")

    profile_hash = sha256_bytes(canonical_json_bytes(profile))
    if target_grippers.robot_id != profile.robot_id:
        raise ValueError("target gripper replay robot id does not match robot profile")
    if target_grippers.profile_sha256 != profile_hash:
        raise ValueError("target gripper replay profile hash does not match robot profile")
    profile_groups = tuple(group.name for group in profile.groups)
    if set(target_grippers.group_names) != set(profile_groups):
        raise ValueError("target gripper replay groups do not match robot profile")

    trajectory_hash = sha256_file(trajectory_path)
    if recipe.input_sha256.lower() != trajectory_hash.lower():
        raise ValueError("recipe input hash does not match canonical trajectory file")
    if recipe.robot_id != profile.robot_id:
        raise ValueError("recipe robot id does not match robot profile")
    if recipe.solve_coupling != coupling:
        raise ValueError("replay coupling does not match recipe solve coupling")

    solve_robot_id = _required_string(solve, "robot_id", "arm solve artifact")
    solve_recipe_hash = _required_string(solve, "recipe_sha256", "arm solve artifact")
    solve_backend_name = _required_string(solve, "backend_name", "arm solve artifact")
    solve_backend_version = _required_string(solve, "backend_version", "arm solve artifact")
    solve_group = _required_string(solve, "group", "arm solve artifact")
    solve_frame_count = solve.get("frame_count")
    if not isinstance(solve_frame_count, int) or solve_frame_count <= 0:
        raise ValueError("arm solve artifact frame_count must be a positive integer")
    if solve_robot_id != profile.robot_id:
        raise ValueError("arm solve robot id does not match robot profile")
    if solve_recipe_hash != recipe_sha256(recipe):
        raise ValueError("arm solve recipe hash does not match recipe")
    if solve_backend_name != recipe.backend_name or solve_backend_version != recipe.backend_version:
        raise ValueError("arm solve backend does not match recipe")
    if solve_group not in profile_groups:
        raise ValueError("arm solve group is not present in robot profile")
    if trajectory.frame_count != len(target_grippers.frames):
        raise ValueError("target gripper frame count does not match canonical trajectory")
    if solve_frame_count != trajectory.frame_count:
        raise ValueError("arm solve frame count does not match canonical trajectory")

    artifact_hashes = {
        "canonical_trajectory": trajectory_hash,
        "robot_profile": profile_hash,
        "recipe": recipe_sha256(recipe),
        "arm_solve": sha256_file(arm_solve_path),
        "target_grippers": sha256_file(target_grippers_path),
    }
    artifact_paths = {
        "canonical_trajectory": trajectory_path,
        "robot_profile": profile_path,
        "recipe": recipe_path,
        "arm_solve": arm_solve_path,
        "target_grippers": target_grippers_path,
    }
    roles: tuple[ReplayArtifactRole, ...] = (
        "canonical_trajectory",
        "robot_profile",
        "recipe",
        "arm_solve",
        "target_grippers",
    )
    return TargetReplayManifest(
        replay_id=replay_id,
        robot_id=profile.robot_id,
        coupling=coupling,
        backend_name=solve_backend_name,
        backend_version=solve_backend_version,
        arm_group=solve_group,
        frame_count=trajectory.frame_count,
        target_group_names=profile_groups,
        canonical_trajectory_sha256=artifact_hashes["canonical_trajectory"],
        robot_profile_sha256=artifact_hashes["robot_profile"],
        recipe_sha256=artifact_hashes["recipe"],
        arm_solve_sha256=artifact_hashes["arm_solve"],
        target_grippers_sha256=artifact_hashes["target_grippers"],
        artifacts=tuple(
            ReplayArtifact(role=role, path=str(artifact_paths[role]), sha256=artifact_hashes[role])
            for role in roles
        ),
    )


def write_target_replay_manifest(
    path: Path,
    manifest: TargetReplayManifest,
) -> TargetReplayManifest:
    """Write one exclusive value-free replay manifest."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(manifest.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return manifest
