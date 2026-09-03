"""Bounded, approval-gated calibration normalization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from retargetlab.contracts import (
    CalibrationReport,
    CanonicalTrajectory,
    MappingSpec,
    StructureComparison,
)
from retargetlab.io.normalize import normalize_rows

DEFAULT_MAX_CALIBRATION_FRAMES = 60
MAX_CALIBRATION_FRAMES = 600


def _require_approved_mapping(spec: MappingSpec, comparison: StructureComparison) -> None:
    if spec.metadata.get("candidate_status") != "APPROVED":
        raise ValueError("calibration requires an approved mapping")
    if not comparison.alias_match:
        raise ValueError("calibration structure comparison alias does not match mapping")
    if not comparison.revision_match:
        raise ValueError("calibration structure comparison revision does not match mapping")
    if not comparison.compatible:
        raise ValueError("calibration structure comparison is incompatible")
    if not comparison.fully_verified and spec.metadata.get("accepted_unverified_shape") != "true":
        raise ValueError("approved mapping does not accept unverified source shapes")
    required_metadata = (
        "reviewer",
        "review_evidence",
        "target_group.slot_0",
        "target_group.slot_1",
    )
    missing = [key for key in required_metadata if not spec.metadata.get(key)]
    if missing:
        raise ValueError(f"approved mapping is missing review metadata: {missing}")
    if spec.coordinate_frame == "UNRESOLVED":
        raise ValueError("approved mapping has an unresolved coordinate frame")


def run_bounded_calibration(
    rows: Sequence[Mapping[str, object]],
    spec: MappingSpec,
    comparison: StructureComparison,
    *,
    max_frames: int = DEFAULT_MAX_CALIBRATION_FRAMES,
) -> tuple[CanonicalTrajectory, CalibrationReport]:
    """Normalize a small approved slice and return a value-free completion report."""

    if max_frames <= 0 or max_frames > MAX_CALIBRATION_FRAMES:
        raise ValueError(f"max_frames must be between 1 and {MAX_CALIBRATION_FRAMES}")
    if not rows:
        raise ValueError("calibration rows must not be empty")
    if len(rows) > max_frames:
        raise ValueError(f"calibration slice has {len(rows)} rows; limit is {max_frames}")
    _require_approved_mapping(spec, comparison)
    trajectory = normalize_rows(rows, spec)
    report = CalibrationReport(
        frame_count=trajectory.frame_count,
        max_frames=max_frames,
        stream_names=trajectory.stream_names,
        structure_status=(
            "FULLY_VERIFIED" if comparison.fully_verified else "COMPATIBLE_UNVERIFIED"
        ),
    )
    return trajectory, report
