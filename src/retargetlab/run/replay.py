"""Build value-free provenance for a canonical-to-target replay."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from retargetlab.contracts import (
    CanonicalTrajectory,
    ExportProfile,
    Recipe,
    ReplayArtifact,
    RobotProfile,
    TargetGripperTrajectory,
    TargetReplayArtifactVerification,
    TargetReplayFrame,
    TargetReplayManifest,
    TargetReplayTrajectory,
    TargetReplayVerification,
)
from retargetlab.export import build_target_vector_layout
from retargetlab.robot.assets import sha256_file, verify_robot_profile_asset
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
    arm_solve_paths: Sequence[Path],
    target_grippers_path: Path,
    coupling: str,
) -> TargetReplayManifest:
    """Cross-check replay inputs and return a value-free manifest."""

    if not arm_solve_paths:
        raise ValueError("at least one arm solve artifact is required")
    trajectory = CanonicalTrajectory.model_validate_json(
        trajectory_path.read_text(encoding="utf-8")
    )
    profile = RobotProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    verify_robot_profile_asset(profile)
    recipe = Recipe.model_validate_json(recipe_path.read_text(encoding="utf-8"))
    target_grippers = TargetGripperTrajectory.model_validate_json(
        target_grippers_path.read_text(encoding="utf-8")
    )
    solves = [_read_object(path, "arm solve artifact") for path in arm_solve_paths]

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

    solve_by_group: dict[str, dict[str, Any]] = {}
    for solve in solves:
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
        if (
            solve_backend_name != recipe.backend_name
            or solve_backend_version != recipe.backend_version
        ):
            raise ValueError("arm solve backend does not match recipe")
        if solve_group not in profile_groups:
            raise ValueError("arm solve group is not present in robot profile")
        if solve_group in solve_by_group:
            raise ValueError(f"duplicate arm solve group: {solve_group}")
        if solve_frame_count != trajectory.frame_count:
            raise ValueError("arm solve frame count does not match canonical trajectory")
        solve_by_group[solve_group] = solve
    if set(solve_by_group) != set(profile_groups):
        raise ValueError("arm solve groups must cover every target robot group")
    if trajectory.frame_count != len(target_grippers.frames):
        raise ValueError("target gripper frame count does not match canonical trajectory")

    path_by_group = {
        solve["group"]: path for solve, path in zip(solves, arm_solve_paths, strict=True)
    }
    if set(path_by_group) != set(profile_groups):
        raise ValueError("arm solve paths do not match arm solve groups")
    solve_hashes = {group: sha256_file(path_by_group[group]) for group in profile_groups}
    artifact_hashes: dict[str, str] = {
        "canonical_trajectory": trajectory_hash,
        "robot_profile": profile_hash,
        "recipe": recipe_sha256(recipe),
        "target_grippers": sha256_file(target_grippers_path),
    }
    artifacts: list[ReplayArtifact] = [
        ReplayArtifact(
            role="canonical_trajectory",
            path=str(trajectory_path),
            sha256=artifact_hashes["canonical_trajectory"],
        ),
        ReplayArtifact(
            role="robot_profile",
            path=str(profile_path),
            sha256=artifact_hashes["robot_profile"],
        ),
        ReplayArtifact(
            role="recipe",
            path=str(recipe_path),
            sha256=artifact_hashes["recipe"],
        ),
    ]
    artifacts.extend(
        ReplayArtifact(
            role="arm_solve",
            path=str(path_by_group[group]),
            sha256=solve_hashes[group],
            group=group,
        )
        for group in profile_groups
    )
    artifacts.append(
        ReplayArtifact(
            role="target_grippers",
            path=str(target_grippers_path),
            sha256=artifact_hashes["target_grippers"],
        )
    )
    solve_backend = solves[0]
    return TargetReplayManifest(
        replay_id=replay_id,
        robot_id=profile.robot_id,
        coupling=coupling,
        backend_name=_required_string(solve_backend, "backend_name", "arm solve artifact"),
        backend_version=_required_string(solve_backend, "backend_version", "arm solve artifact"),
        arm_groups=profile_groups,
        frame_count=trajectory.frame_count,
        target_group_names=profile_groups,
        canonical_trajectory_sha256=artifact_hashes["canonical_trajectory"],
        robot_profile_sha256=artifact_hashes["robot_profile"],
        recipe_sha256=artifact_hashes["recipe"],
        arm_solve_sha256s=tuple(solve_hashes[group] for group in profile_groups),
        target_grippers_sha256=artifact_hashes["target_grippers"],
        artifacts=tuple(artifacts),
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


def verify_target_replay_manifest(path: Path) -> TargetReplayVerification:
    """Recompute all replay bindings and return a value-free verification."""

    manifest = TargetReplayManifest.model_validate_json(path.read_text(encoding="utf-8"))
    by_role = {item.role: item for item in manifest.artifacts if item.role != "arm_solve"}
    arm_by_group = {item.group: item for item in manifest.artifacts if item.role == "arm_solve"}
    required_roles = {
        "canonical_trajectory",
        "robot_profile",
        "recipe",
        "target_grippers",
    }
    if set(by_role) != required_roles or set(arm_by_group) != set(manifest.arm_groups):
        raise ValueError("replay manifest artifact roles are incomplete")
    all_paths = [item.path for item in by_role.values()] + [
        arm_by_group[group].path for group in manifest.arm_groups
    ]
    if any(not Path(raw_path).is_file() for raw_path in all_paths):
        missing = [raw_path for raw_path in all_paths if not Path(raw_path).is_file()]
        raise FileNotFoundError(f"replay manifest input is missing: {missing}")
    expected = build_target_replay_manifest(
        replay_id=manifest.replay_id,
        trajectory_path=Path(by_role["canonical_trajectory"].path),
        profile_path=Path(by_role["robot_profile"].path),
        recipe_path=Path(by_role["recipe"].path),
        arm_solve_paths=tuple(Path(arm_by_group[group].path) for group in manifest.arm_groups),
        target_grippers_path=Path(by_role["target_grippers"].path),
        coupling=manifest.coupling,
    )
    if expected != manifest:
        raise ValueError("replay manifest does not match its input artifacts")
    return TargetReplayVerification(
        replay_id=manifest.replay_id,
        robot_id=manifest.robot_id,
        frame_count=manifest.frame_count,
        manifest_sha256=sha256_bytes(canonical_json_bytes(manifest)),
        robot_profile_sha256=manifest.robot_profile_sha256,
        arm_groups=manifest.arm_groups,
        artifact_roles=tuple(item.role for item in manifest.artifacts),
    )


def _solve_positions(
    solve: dict[str, Any],
    *,
    group: str,
    frame_count: int,
    joint_count: int,
) -> tuple[tuple[float, ...], ...]:
    """Validate converged q values before they enter a target command row."""

    if solve.get("group") != group:
        raise ValueError(f"arm solve group does not match its bound group: {group}")
    raw_results = solve.get("results")
    if not isinstance(raw_results, list) or len(raw_results) != frame_count:
        raise ValueError(f"arm solve results do not cover every frame: {group}")
    positions: list[tuple[float, ...]] = []
    for frame_index, raw_result in enumerate(raw_results):
        if not isinstance(raw_result, dict):
            raise ValueError(f"arm solve result is not an object: {group}[{frame_index}]")
        if raw_result.get("status") != "CONVERGED":
            raise ValueError(f"arm solve frame is not CONVERGED: {group}[{frame_index}]")
        raw_q = raw_result.get("q")
        if not isinstance(raw_q, list) or len(raw_q) != joint_count:
            raise ValueError(f"arm solve q dimension does not match the profile: {group}")
        if not all(isinstance(value, (int, float)) for value in raw_q):
            raise ValueError(f"arm solve q values must be numeric: {group}[{frame_index}]")
        q = tuple(float(value) for value in raw_q)
        if not all(math.isfinite(value) for value in q):
            raise ValueError(f"arm solve q values must be finite: {group}[{frame_index}]")
        positions.append(q)
    return tuple(positions)


def build_target_replay_trajectory(
    *,
    manifest_path: Path,
    export_profile_path: Path,
) -> TargetReplayTrajectory:
    """Materialize converged arm and gripper values in the verified layout."""

    verify_target_replay_manifest(manifest_path)
    manifest = TargetReplayManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    by_role = {item.role: item for item in manifest.artifacts if item.role != "arm_solve"}
    arm_paths: dict[str, Path] = {}
    for artifact in manifest.artifacts:
        if artifact.role == "arm_solve":
            if artifact.group is None:
                raise ValueError("arm solve artifact has no bound group")
            arm_paths[artifact.group] = Path(artifact.path)

    trajectory = CanonicalTrajectory.model_validate_json(
        Path(by_role["canonical_trajectory"].path).read_text(encoding="utf-8")
    )
    robot_profile = RobotProfile.model_validate_json(
        Path(by_role["robot_profile"].path).read_text(encoding="utf-8")
    )
    export_profile = ExportProfile.model_validate_json(
        export_profile_path.read_text(encoding="utf-8")
    )
    target_grippers = TargetGripperTrajectory.model_validate_json(
        Path(by_role["target_grippers"].path).read_text(encoding="utf-8")
    )
    expected_layout = build_target_vector_layout(robot_profile)
    if export_profile.robot_id != manifest.robot_id:
        raise ValueError("export profile robot id does not match replay manifest")
    if export_profile.robot_profile_sha256 != manifest.robot_profile_sha256:
        raise ValueError("export profile robot hash does not match replay manifest")
    if export_profile.target_layout != expected_layout:
        raise ValueError("export profile layout does not match robot profile")
    profile_groups = tuple(group.name for group in robot_profile.groups)
    if target_grippers.group_names != profile_groups:
        raise ValueError("target gripper replay group order does not match robot profile")
    if len(target_grippers.frames) != trajectory.frame_count:
        raise ValueError("target gripper replay frame count does not match trajectory")

    expected_gripper_joints: set[str] = set()
    for group in robot_profile.groups:
        if group.gripper is None:
            if group.gripper_joint_names:
                raise ValueError(
                    f"target group has gripper joints but no explicit semantics: {group.name}"
                )
            continue
        expected_gripper_joints.update(group.gripper.joint_names)
    if not expected_gripper_joints:
        raise ValueError("target replay requires at least one explicit gripper mapping")
    if set(target_grippers.frames[0].joint_positions) != expected_gripper_joints:
        raise ValueError("target gripper replay joints do not match robot profile")

    solve_positions: dict[str, tuple[tuple[float, ...], ...]] = {}
    for group in robot_profile.groups:
        solve = _read_object(arm_paths[group.name], "arm solve artifact")
        solve_positions[group.name] = _solve_positions(
            solve,
            group=group.name,
            frame_count=trajectory.frame_count,
            joint_count=len(group.joint_names),
        )

    frames: list[TargetReplayFrame] = []
    for frame_index, (canonical_frame, gripper_frame) in enumerate(
        zip(trajectory.frames, target_grippers.frames, strict=True)
    ):
        if not math.isclose(
            canonical_frame.timestamp_s,
            gripper_frame.timestamp_s,
            abs_tol=1e-12,
        ):
            raise ValueError(f"target gripper timestamp does not match trajectory: {frame_index}")
        values: list[float] = []
        for group in robot_profile.groups:
            values.extend(solve_positions[group.name][frame_index])
            if group.gripper is None:
                continue
            driver = gripper_frame.joint_positions[group.gripper.driver_joint_name]
            if not (
                group.gripper.driver_lower_m - 1e-9 <= driver <= group.gripper.driver_upper_m + 1e-9
            ):
                raise ValueError(
                    f"target gripper driver is outside its profile limits: {group.name}"
                )
            for mimic in group.gripper.mimic_joints:
                expected = mimic.multiplier * driver + mimic.offset_m
                observed = gripper_frame.joint_positions[mimic.joint_name]
                if not math.isclose(observed, expected, abs_tol=1e-9):
                    raise ValueError(
                        f"target gripper mimic value does not match the profile: {group.name}"
                    )
            values.append(driver)
        frames.append(
            TargetReplayFrame(
                timestamp_s=canonical_frame.timestamp_s,
                joint_positions=tuple(values),
            )
        )

    return TargetReplayTrajectory(
        replay_id=manifest.replay_id,
        robot_id=manifest.robot_id,
        replay_manifest_path=str(manifest_path),
        replay_manifest_sha256=sha256_bytes(canonical_json_bytes(manifest)),
        export_profile_path=str(export_profile_path),
        export_profile_sha256=sha256_bytes(canonical_json_bytes(export_profile)),
        layout=export_profile.target_layout,
        frame_count=len(frames),
        frames=frames,
    )


def write_target_replay_trajectory(
    path: Path,
    trajectory: TargetReplayTrajectory,
) -> TargetReplayTrajectory:
    """Write one value-bearing target command artifact exclusively."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(trajectory.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return trajectory


def verify_target_replay_trajectory(path: Path) -> TargetReplayArtifactVerification:
    """Rebuild and compare one materialized target replay artifact."""

    artifact = TargetReplayTrajectory.model_validate_json(path.read_text(encoding="utf-8"))
    expected = build_target_replay_trajectory(
        manifest_path=Path(artifact.replay_manifest_path),
        export_profile_path=Path(artifact.export_profile_path),
    )
    if expected != artifact:
        raise ValueError("target replay artifact does not match its bound inputs")
    return TargetReplayArtifactVerification(
        replay_id=artifact.replay_id,
        robot_id=artifact.robot_id,
        frame_count=artifact.frame_count,
        artifact_sha256=sha256_bytes(canonical_json_bytes(artifact)),
        replay_manifest_sha256=artifact.replay_manifest_sha256,
        export_profile_sha256=artifact.export_profile_sha256,
    )
