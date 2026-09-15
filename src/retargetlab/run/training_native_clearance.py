"""Explicit native clearance gate evaluated on the final exported configuration."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NativeClearancePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_distance_m: float = Field(gt=0, allow_inf_nan=False)
    numeric_epsilon_m: float = Field(default=1e-8, ge=0, allow_inf_nan=False)
    distance_clip_m: float = Field(default=0.02, gt=0, allow_inf_nan=False)
    model_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def check_range(self):
        if self.numeric_epsilon_m >= self.minimum_distance_m:
            raise ValueError("native clearance epsilon must be smaller than the margin")
        if self.distance_clip_m <= self.minimum_distance_m:
            raise ValueError("native distance clip must exceed the margin")
        return self


class NativeExportClearance:
    def __init__(self, spec, config, binding, profile, joint_names):
        from retargetlab.replay.bundle import digest
        from retargetlab.robot.mujoco_model import MujocoKinematics
        from retargetlab.robot.native_collision import NativeCollisionGeometry

        self.spec = NativeClearancePolicy.model_validate(spec)
        if not config.get("mujoco_model"):
            raise ValueError("native export clearance requires the processing MuJoCo model")
        path = Path(config["mujoco_model"])
        actual = digest(path / "manifest.json")
        if actual != self.spec.model_manifest_sha256 or actual != binding.get(
            "mujoco_model_manifest_sha256"
        ):
            raise ValueError("native export model differs from policy or processing binding")
        self.engine = MujocoKinematics(path)
        if (
            self.engine.metadata["robot_id"] != profile.robot_id
            or self.engine.metadata["source_urdf_sha256"] != profile.urdf_sha256
            or self.engine.metadata["root_frame"] != profile.root_frame
        ):
            raise ValueError("native export model/profile identity mismatch")
        self.geometry = NativeCollisionGeometry(self.engine, profile)
        if not self.geometry.pairs:
            raise ValueError("native export clearance has no collision pairs to assess")
        self.joint_names = joint_names

    def assess(self, q):
        self.engine.set_configuration(self.joint_names, q)
        distance = self.geometry.minimum(self.engine.data, self.spec.distance_clip_m)
        return {
            "native_min_distance_m": distance,
            "native_clearance_ok": distance
            >= self.spec.minimum_distance_m - self.spec.numeric_epsilon_m,
        }

    def summary(self):
        return {
            **self.spec.model_dump(),
            "evaluated_configuration": "exported float32 arms; registered fixed gripper",
            "geometry": self.geometry.summary(),
            "swept_volume_checked": False,
        }
