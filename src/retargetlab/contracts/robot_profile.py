"""Robot and collision profile contracts."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MimicJoint(BaseModel):
    """One target joint driven by an explicit affine mimic relation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    joint_name: str = Field(min_length=1)
    multiplier: float = 1.0
    offset_m: float = 0.0

    @model_validator(mode="after")
    def validate_coefficients(self) -> MimicJoint:
        if not self.joint_name.strip():
            raise ValueError("mimic joint name must not be blank")
        if not math.isfinite(self.multiplier) or not math.isfinite(self.offset_m):
            raise ValueError("mimic coefficients must be finite")
        return self


class TargetGripperProfile(BaseModel):
    """Target-side aperture semantics independent of arm IK."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    driver_joint_name: str = Field(min_length=1)
    mimic_joints: tuple[MimicJoint, ...] = ()
    joint_unit: Literal["m"] = "m"
    driver_lower_m: float
    driver_upper_m: float
    aperture_semantics: Literal["aperture_fraction"] = "aperture_fraction"

    @model_validator(mode="after")
    def validate_mapping(self) -> TargetGripperProfile:
        if not self.driver_joint_name.strip():
            raise ValueError("gripper driver joint name must not be blank")
        if not math.isfinite(self.driver_lower_m) or not math.isfinite(self.driver_upper_m):
            raise ValueError("gripper driver limits must be finite")
        if self.driver_upper_m <= self.driver_lower_m:
            raise ValueError("gripper driver upper limit must exceed lower limit")
        names = (self.driver_joint_name,) + tuple(item.joint_name for item in self.mimic_joints)
        if len(set(names)) != len(names):
            raise ValueError("gripper driver and mimic joint names must be unique")
        return self

    @property
    def joint_names(self) -> tuple[str, ...]:
        """Return joints in the declared target-side command order."""

        return (self.driver_joint_name,) + tuple(item.joint_name for item in self.mimic_joints)

    def aperture_to_joint_positions(self, aperture_fraction: float) -> dict[str, float]:
        """Map ``0=closed`` and ``1=open`` to target joint positions in metres."""

        if not math.isfinite(aperture_fraction) or not 0.0 <= aperture_fraction <= 1.0:
            raise ValueError("aperture_fraction must be finite and in [0, 1]")
        driver = self.driver_lower_m + aperture_fraction * (
            self.driver_upper_m - self.driver_lower_m
        )
        positions = {self.driver_joint_name: driver}
        positions.update(
            {
                mimic.joint_name: mimic.multiplier * driver + mimic.offset_m
                for mimic in self.mimic_joints
            }
        )
        return positions


class KinematicGroup(BaseModel):
    """A named group of joints and one target frame in a robot model."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    joint_names: tuple[str, ...] = Field(min_length=1)
    end_effector_frame: str = Field(min_length=1)
    gripper_joint_names: tuple[str, ...] = ()
    gripper: TargetGripperProfile | None = None

    @model_validator(mode="after")
    def validate_joint_names(self) -> KinematicGroup:
        all_names = self.joint_names + self.gripper_joint_names
        if len(set(all_names)) != len(all_names):
            raise ValueError("joint names must be unique within a kinematic group")
        if any(not name.strip() for name in all_names):
            raise ValueError("joint names must not be blank")
        if self.gripper is not None and self.gripper.joint_names != self.gripper_joint_names:
            raise ValueError("gripper semantics must match gripper_joint_names order")
        return self


class CollisionProfile(BaseModel):
    """Collision geometry and SRDF policy associated with a robot asset."""

    model_config = ConfigDict(extra="forbid")

    srdf_path: str | None = None
    srdf_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
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
