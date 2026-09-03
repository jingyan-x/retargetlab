"""Backend-independent data contracts."""

from .calibration import (
    CalibrationRecipe,
    CalibrationReport,
    CalibrationRunManifest,
    CalibrationRunVerification,
    ReviewRunArtifact,
)
from .canonical import CanonicalFrame, CanonicalTrajectory, Pose
from .diagnostics import DatasetReport, EpisodeReport, FrameDiagnostics
from .evidence import EvidenceLevel, Provenance, SemanticField
from .mapping import (
    ColumnRef,
    DatasetInfoManifest,
    FeatureDeclaration,
    MappingReview,
    MappingSpec,
    MappingValidation,
    ReviewPackageInspection,
    ReviewPackagePreflightArtifact,
    ReviewPackagePreflightVerification,
    StreamMapping,
    StructureComparison,
    StructureField,
    StructureManifest,
)
from .recipe import Recipe, RunManifest
from .robot_profile import CollisionProfile, KinematicGroup, RobotProfile
from .selection import CalibrationSelection, EpisodeRange
from .solve import IKResult, IKStatus, SolveOptions
from .threshold import Threshold

__all__ = [
    "CanonicalFrame",
    "CanonicalTrajectory",
    "CalibrationReport",
    "CalibrationRecipe",
    "CalibrationRunManifest",
    "CalibrationRunVerification",
    "CalibrationSelection",
    "ColumnRef",
    "CollisionProfile",
    "DatasetInfoManifest",
    "DatasetReport",
    "EpisodeReport",
    "EvidenceLevel",
    "EpisodeRange",
    "FeatureDeclaration",
    "IKResult",
    "IKStatus",
    "KinematicGroup",
    "MappingSpec",
    "MappingReview",
    "ReviewPackageInspection",
    "ReviewPackagePreflightArtifact",
    "ReviewPackagePreflightVerification",
    "MappingValidation",
    "FrameDiagnostics",
    "Pose",
    "Provenance",
    "Recipe",
    "RobotProfile",
    "RunManifest",
    "ReviewRunArtifact",
    "SemanticField",
    "SolveOptions",
    "StreamMapping",
    "StructureComparison",
    "StructureField",
    "StructureManifest",
    "Threshold",
]
