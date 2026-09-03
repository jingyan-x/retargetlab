"""Backend-independent data contracts."""

from .calibration import (
    CalibrationRecipe,
    CalibrationReport,
    CalibrationRunManifest,
    CalibrationRunVerification,
    ReviewRunArtifact,
)
from .canonical import CanonicalFrame, CanonicalTrajectory, Pose
from .coverage import DatasetCoverage, EpisodeCoverage
from .diagnostics import DatasetReport, EpisodeReport, FrameDiagnostics
from .evidence import EvidenceLevel, Provenance, SemanticField
from .gripper import TargetGripperFrame, TargetGripperTrajectory
from .mapping import (
    ColumnRef,
    DatasetInfoManifest,
    FeatureDeclaration,
    MappingReview,
    MappingSpec,
    MappingValidation,
    ReviewDecisionArtifact,
    ReviewEvidenceChecklist,
    ReviewPackageInspection,
    ReviewPackagePreflightArtifact,
    ReviewPackagePreflightVerification,
    StreamMapping,
    StructureComparison,
    StructureField,
    StructureManifest,
)
from .profile import (
    AffineMap,
    DataProfile,
    DataProfileVerification,
    DatasetRevision,
    GripperProfile,
    ProfileChannel,
    TimingEvidence,
)
from .recipe import Recipe, RunManifest
from .replay import ReplayArtifact, TargetReplayManifest
from .robot_profile import (
    CollisionProfile,
    KinematicGroup,
    MimicJoint,
    RobotProfile,
    TargetGripperProfile,
)
from .selection import CalibrationSelection, EpisodeRange
from .solve import IKResult, IKStatus, SolveOptions
from .threshold import Threshold
from .timing import CommandTimingReport, TimingShiftResult

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
    "DatasetCoverage",
    "DatasetReport",
    "EpisodeReport",
    "EpisodeCoverage",
    "EvidenceLevel",
    "EpisodeRange",
    "FeatureDeclaration",
    "IKResult",
    "IKStatus",
    "KinematicGroup",
    "MimicJoint",
    "MappingSpec",
    "MappingReview",
    "ReviewPackageInspection",
    "ReviewPackagePreflightArtifact",
    "ReviewPackagePreflightVerification",
    "ReviewEvidenceChecklist",
    "ReviewDecisionArtifact",
    "MappingValidation",
    "FrameDiagnostics",
    "Pose",
    "Provenance",
    "Recipe",
    "ReplayArtifact",
    "RobotProfile",
    "TargetGripperProfile",
    "RunManifest",
    "ReviewRunArtifact",
    "SemanticField",
    "SolveOptions",
    "StreamMapping",
    "StructureComparison",
    "StructureField",
    "StructureManifest",
    "Threshold",
    "TargetGripperFrame",
    "TargetGripperTrajectory",
    "TargetReplayManifest",
    "CommandTimingReport",
    "TimingShiftResult",
    "AffineMap",
    "DataProfile",
    "DataProfileVerification",
    "DatasetRevision",
    "GripperProfile",
    "ProfileChannel",
    "TimingEvidence",
]
