import math

import pytest
from pydantic import ValidationError

from retargetlab.contracts import (
    CanonicalFrame,
    CanonicalTrajectory,
    EvidenceLevel,
    KinematicGroup,
    Pose,
    Provenance,
    RobotProfile,
    SemanticField,
    SolveOptions,
    Threshold,
)


def test_canonical_trajectory_requires_aligned_streams_and_frames() -> None:
    pose = Pose(position_m=(0.0, 0.0, 0.0), quaternion_wxyz=(1.0, 0.0, 0.0, 0.0))
    trajectory = CanonicalTrajectory(
        frames=[
            CanonicalFrame(timestamp_s=0.0, poses={"left": pose, "right": pose}),
            CanonicalFrame(timestamp_s=0.01, poses={"left": pose, "right": pose}),
        ]
    )
    assert trajectory.frame_count == 2
    assert trajectory.stream_names == ("left", "right")

    with pytest.raises(ValidationError, match="same stream names"):
        CanonicalTrajectory(
            frames=[
                CanonicalFrame(timestamp_s=0.0, poses={"left": pose}),
                CanonicalFrame(timestamp_s=0.01, poses={"right": pose}),
            ]
        )


def test_evidence_and_threshold_require_provenance() -> None:
    field = SemanticField[float](
        value=0.005,
        unit="m",
        frame="dataset_native",
        provenance=Provenance(
            level=EvidenceLevel.EXPLICIT,
            source="synthetic fixture",
        ),
    )
    assert field.provenance.level is EvidenceLevel.EXPLICIT

    with pytest.raises(ValidationError, match="calibrated_on"):
        Threshold(
            warn=0.01,
            fail=0.02,
            unit="m",
            source="fixture",
            provenance="fixture",
            status="sample_validated",
        )


def test_robot_profile_and_solve_options_are_explicit() -> None:
    profile = RobotProfile(
        robot_id="fixture",
        asset_dir="assets/robots/fixture",
        urdf_path="robot.urdf",
        urdf_sha256="0" * 64,
        groups=(
            KinematicGroup(
                name="arm",
                joint_names=("joint1",),
                end_effector_frame="tool",
            ),
        ),
    )
    assert profile.groups[0].end_effector_frame == "tool"
    options = SolveOptions()
    assert options.qp_solver == "osqp"
    assert math.isclose(options.orientation_tolerance_rad, math.radians(2.0))
    with pytest.raises(ValidationError, match="only the registered osqp"):
        SolveOptions(qp_solver="other")
