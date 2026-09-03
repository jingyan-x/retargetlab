"""Backend-independent data contracts."""

from .canonical import CanonicalFrame, CanonicalTrajectory, Pose
from .evidence import EvidenceLevel, Provenance, SemanticField
from .robot_profile import CollisionProfile, KinematicGroup, RobotProfile
from .solve import IKResult, IKStatus, SolveOptions
from .threshold import Threshold

__all__ = [
    "CanonicalFrame",
    "CanonicalTrajectory",
    "CollisionProfile",
    "EvidenceLevel",
    "IKResult",
    "IKStatus",
    "KinematicGroup",
    "Pose",
    "Provenance",
    "RobotProfile",
    "SemanticField",
    "SolveOptions",
    "Threshold",
]
