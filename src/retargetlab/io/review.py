"""Promote a mapping candidate only after explicit semantic review."""

from __future__ import annotations

from retargetlab.contracts import MappingReview, MappingSpec, StreamMapping, StructureComparison


def apply_mapping_review(
    candidate: MappingSpec,
    review: MappingReview,
    comparison: StructureComparison,
) -> MappingSpec:
    """Apply reviewed frame/unit/slot metadata to a candidate mapping."""

    if not review.approved:
        raise ValueError("mapping review is not approved")
    if candidate.dataset_alias != review.dataset_alias:
        raise ValueError("mapping review dataset alias does not match candidate")
    if candidate.source_revision != review.source_revision:
        raise ValueError("mapping review source revision does not match candidate")
    if not comparison.compatible:
        raise ValueError("structure comparison is incompatible with candidate")
    if not comparison.fully_verified and not review.accept_unverified_shape:
        raise ValueError("review must explicitly accept unverified source shapes")
    if not comparison.fully_verified and (
        review.checklist is None or review.checklist.shape_acceptance != "ACCEPTED"
    ):
        raise ValueError("approved review must explicitly accept unverified source shapes")

    streams: list[StreamMapping] = []
    for stream in candidate.streams:
        if ".slot_" not in stream.name:
            raise ValueError(f"candidate stream has no explicit slot suffix: {stream.name}")
        source, slot = stream.name.rsplit(".slot_", 1)
        slot_key = f"slot_{slot}"
        if slot_key not in review.slot_labels:
            raise ValueError(f"candidate stream uses an unreviewed slot: {slot_key}")
        fields = dict(stream.fields)
        position = fields.get("position")
        orientation = fields.get("orientation")
        if position is None or orientation is None:
            raise ValueError(f"candidate stream is missing pose fields: {stream.name}")
        fields["position"] = position.model_copy(
            update={"unit": review.position_unit, "frame": review.coordinate_frame}
        )
        fields["orientation"] = orientation.model_copy(
            update={
                "frame": review.coordinate_frame,
                "quaternion_order": review.orientation_quaternion_order,
            }
        )
        streams.append(
            StreamMapping(
                name=f"{source}.{review.slot_labels[slot_key]}",
                role=stream.role,
                fields=fields,
            )
        )

    metadata = dict(candidate.metadata)
    metadata.update(
        {
            "candidate_status": "APPROVED",
            "coordinate_frame": review.coordinate_frame,
            "position_unit": review.position_unit,
            "timestamp_unit": review.timestamp_unit,
            "quaternion_order": review.orientation_quaternion_order,
            "reviewer": review.reviewer,
            "review_evidence": ";".join(review.evidence),
            "accepted_unverified_shape": str(review.accept_unverified_shape).lower(),
            "target_group.slot_0": review.target_group_by_slot["slot_0"],
            "target_group.slot_1": review.target_group_by_slot["slot_1"],
        }
    )
    return candidate.model_copy(
        update={
            "coordinate_frame": review.coordinate_frame,
            "timestamp": candidate.timestamp.model_copy(update={"unit": review.timestamp_unit}),
            "streams": tuple(streams),
            "metadata": metadata,
        }
    )
