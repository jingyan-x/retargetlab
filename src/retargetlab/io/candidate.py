"""Build review-only mappings from declared feature element names."""

from __future__ import annotations

from typing import Literal

from retargetlab.contracts import (
    ColumnRef,
    DatasetInfoManifest,
    FeatureDeclaration,
    MappingSpec,
    StreamMapping,
)


def _feature(info: DatasetInfoManifest, source: str) -> FeatureDeclaration:
    feature = info.features.get(source)
    if feature is None:
        raise ValueError(f"required feature is missing from metadata: {source}")
    if feature.storage != "parquet":
        raise ValueError(f"feature is not stored in Parquet: {source}")
    if feature.shape is None:
        raise ValueError(f"feature shape is not declared: {source}")
    return feature


def _named_indices(
    feature: FeatureDeclaration,
    *,
    source: str,
    names: tuple[str, ...],
) -> tuple[int, ...]:
    if not feature.names or len(set(feature.names)) != len(feature.names):
        raise ValueError(f"feature element names are missing or duplicated: {source}")
    positions = {name: index for index, name in enumerate(feature.names)}
    missing = [name for name in names if name not in positions]
    if missing:
        raise ValueError(f"feature element names are missing from {source}: {missing}")
    return tuple(positions[name] for name in names)


def _pose_stream(
    *,
    source: str,
    role: Literal["robot_state", "command"],
    slot: int,
    feature: FeatureDeclaration,
) -> StreamMapping:
    position_names = tuple(f"epos_{slot}_{axis}" for axis in ("x", "y", "z"))
    quaternion_names = tuple(f"epos_{slot}_q{axis}" for axis in ("w", "x", "y", "z"))
    return StreamMapping(
        name=f"{source}.slot_{slot}",
        role=role,
        fields={
            "position": ColumnRef(
                source=source,
                expected_shape=feature.shape,
                indices=_named_indices(
                    feature,
                    source=source,
                    names=position_names,
                ),
            ),
            "orientation": ColumnRef(
                source=source,
                expected_shape=feature.shape,
                indices=_named_indices(
                    feature,
                    source=source,
                    names=quaternion_names,
                ),
                quaternion_order="wxyz",
            ),
        },
    )


def build_pose_mapping_candidate(info: DatasetInfoManifest) -> MappingSpec:
    """Build a non-executable pose mapping candidate from declared names.

    The candidate intentionally leaves frame and position units unset. Slot
    labels are preserved as ``slot_0``/``slot_1`` because metadata alone does
    not establish left/right or target-robot correspondence.
    """

    timestamp = _feature(info, "timestamp")
    streams: list[StreamMapping] = []
    source_roles: tuple[tuple[str, Literal["robot_state", "command"]], ...] = (
        ("observation.state", "robot_state"),
        ("action", "command"),
    )
    sources_present: list[str] = []
    for source, role in source_roles:
        feature = info.features.get(source)
        if feature is None:
            continue
        feature = _feature(info, source)
        sources_present.append(source)
        streams.append(
            _pose_stream(source=source, role=role, slot=0, feature=feature),
        )
        streams.append(
            _pose_stream(source=source, role=role, slot=1, feature=feature),
        )
    if not streams:
        raise ValueError("metadata contains no pose feature candidates")

    return MappingSpec(
        dataset_alias=info.dataset_alias,
        source_revision=info.source_revision,
        coordinate_frame="UNRESOLVED",
        timestamp=ColumnRef(source="timestamp", expected_shape=timestamp.shape),
        streams=tuple(streams),
        metadata={
            "candidate_status": "REVIEW_REQUIRED",
            "coordinate_frame": "UNRESOLVED",
            "position_unit": "UNRESOLVED",
            "slot_semantics": "slot_0/slot_1; left_right_and_target_mapping_unresolved",
            "quaternion_order_basis": "declared_element_names_qw_qx_qy_qz",
            "gripper_indices": "; ".join(f"{source}[0,8]" for source in sources_present),
        },
    )
