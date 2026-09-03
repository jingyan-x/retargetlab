"""Backend-independent data contracts."""

from .canonical import CanonicalFrame, CanonicalTrajectory, Pose
from .diagnostics import DatasetReport, EpisodeReport, FrameDiagnostics
from .evidence import EvidenceLevel, Provenance, SemanticField
from .mapping import (
    ColumnRef,
    DatasetInfoManifest,
    FeatureDeclaration,
    MappingSpec,
    MappingValidation,
    StreamMapping,
    StructureComparison,
    StructureField,
    StructureManifest,
)
from .recipe import Recipe, RunManifest
from .robot_profile import CollisionProfile, KinematicGroup, RobotProfile
from .solve import IKResult, IKStatus, SolveOptions
from .threshold import Threshold

__all__ = [
    "CanonicalFrame",
    "CanonicalTrajectory",
    "ColumnRef",
    "CollisionProfile",
    "DatasetInfoManifest",
    "DatasetReport",
    "EpisodeReport",
    "EvidenceLevel",
    "FeatureDeclaration",
    "IKResult",
    "IKStatus",
    "KinematicGroup",
    "MappingSpec",
    "MappingValidation",
    "FrameDiagnostics",
    "Pose",
    "Provenance",
    "Recipe",
    "RobotProfile",
    "RunManifest",
    "SemanticField",
    "SolveOptions",
    "StreamMapping",
    "StructureComparison",
    "StructureField",
    "StructureManifest",
    "Threshold",
]
