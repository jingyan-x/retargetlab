"""Backend-independent data contracts."""

from .canonical import CanonicalFrame, CanonicalTrajectory, Pose
from .diagnostics import DatasetReport, EpisodeReport, FrameDiagnostics
from .evidence import EvidenceLevel, Provenance, SemanticField
from .recipe import Recipe, RunManifest
from .robot_profile import CollisionProfile, KinematicGroup, RobotProfile
from .solve import IKResult, IKStatus, SolveOptions
from .threshold import Threshold

__all__ = [
    "CanonicalFrame",
    "CanonicalTrajectory",
    "CollisionProfile",
    "DatasetReport",
    "EpisodeReport",
    "EvidenceLevel",
    "IKResult",
    "IKStatus",
    "KinematicGroup",
    "FrameDiagnostics",
    "Pose",
    "Provenance",
    "Recipe",
    "RobotProfile",
    "RunManifest",
    "SemanticField",
    "SolveOptions",
    "Threshold",
]
