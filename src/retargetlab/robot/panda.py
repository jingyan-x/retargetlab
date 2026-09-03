"""Runtime Panda profile factory for the formal M0 kinematics slice."""

from __future__ import annotations

from pathlib import Path

from retargetlab.contracts import CollisionProfile, KinematicGroup, RobotProfile
from retargetlab.robot.assets import load_manifest, verify_urdf_manifest


def _arm_joint_names(prefix: str) -> tuple[str, ...]:
    return tuple(f"{prefix}_joint{index}" for index in range(1, 8))


def _finger_joint_names(prefix: str) -> tuple[str, ...]:
    return (f"{prefix}_finger_joint1", f"{prefix}_finger_joint2")


def load_panda_bimanual_profile(asset_dir: Path) -> RobotProfile:
    """Build a profile from a versioned Panda asset directory."""

    asset_dir = asset_dir.resolve()
    manifest = load_manifest(asset_dir)
    urdf_path = verify_urdf_manifest(asset_dir, manifest)
    srdf_relative = manifest.get("srdf_path")
    srdf_path = asset_dir / srdf_relative if isinstance(srdf_relative, str) else None
    if srdf_path is not None and not srdf_path.is_file():
        raise FileNotFoundError(f"manifest SRDF is missing: {srdf_path}")

    groups = tuple(
        KinematicGroup(
            name=prefix,
            joint_names=_arm_joint_names(prefix),
            gripper_joint_names=_finger_joint_names(prefix),
            end_effector_frame=f"{prefix}_hand_tcp",
        )
        for prefix in ("panda_1", "panda_2")
    )
    collision = CollisionProfile(
        srdf_path=str(srdf_relative) if isinstance(srdf_relative, str) else None,
        allowed_contact_pairs=(
            ("panda_1_leftfinger", "panda_1_rightfinger"),
            ("panda_2_leftfinger", "panda_2_rightfinger"),
        ),
        strategy=str(manifest.get("collision_geometry_strategy", "srdf")),
    )
    return RobotProfile(
        robot_id="panda_bimanual",
        asset_dir=str(asset_dir),
        urdf_path=str(urdf_path.relative_to(asset_dir)),
        urdf_sha256=str(manifest["generated_urdf_sha256"]),
        root_frame=str(manifest.get("root_link", "base")),
        groups=groups,
        collision=collision,
        metadata={
            "asset_role": str(manifest.get("asset_role", "unspecified")),
            "source_repository": str(manifest.get("source_repository", "unknown")),
            "source_revision": str(manifest.get("source_revision", "unknown")),
        },
    )
