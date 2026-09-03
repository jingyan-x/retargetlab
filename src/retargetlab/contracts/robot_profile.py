"""Robot and collision profile contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class KinematicGroup(BaseModel):
    """A named group of joints and one target frame in a robot model."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    joint_names: tuple[str, ...] = Field(min_length=1)
    end_effector_frame: str = Field(min_length=1)
    gripper_joint_names: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_joint_names(self) -> KinematicGroup:
        all_names = self.joint_names + self.gripper_joint_names
        if len(set(all_names)) != len(all_names):
            raise ValueError("joint names must be unique within a kinematic group")
        if any(not name.strip() for name in all_names):
            raise ValueError("joint names must not be blank")
        return self


class CollisionProfile(BaseModel):
    """Collision geometry and SRDF policy associated with a robot asset."""

    model_config = ConfigDict(extra="forbid")

    srdf_path: str | None = None
    allowed_contact_pairs: tuple[tuple[str, str], ...] = ()
    required_barrier_pairs: tuple[tuple[str, str], ...] = ()
    strategy: str = Field(default="srdf", min_length=1)

    @model_validator(mode="after")
    def validate_pairs(self) -> CollisionProfile:
        normalized: list[tuple[str, str]] = []
        for first, second in self.allowed_contact_pairs + self.required_barrier_pairs:
            if not first.strip() or not second.strip() or first == second:
                raise ValueError("collision contact pairs must contain two distinct names")
            normalized.append((first, second) if first <= second else (second, first))
        if len(set(normalized)) != len(normalized):
            raise ValueError("collision contact pairs must be unique")
        allowed_count = len(self.allowed_contact_pairs)
        self.allowed_contact_pairs = tuple(normalized[:allowed_count])
        self.required_barrier_pairs = tuple(normalized[allowed_count:])
        return self


class RobotProfile(BaseModel):
    """Versioned robot asset metadata consumed by kinematics backends."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="0.1", pattern=r"^0\.1$")
    robot_id: str = Field(min_length=1)
    asset_dir: str = Field(min_length=1)
    urdf_path: str = Field(min_length=1)
    urdf_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    root_frame: str = Field(default="base", min_length=1)
    groups: tuple[KinematicGroup, ...] = Field(min_length=1)
    collision: CollisionProfile | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_groups(self) -> RobotProfile:
        names = [group.name for group in self.groups]
        if len(set(names)) != len(names):
            raise ValueError("kinematic group names must be unique")
        return self
