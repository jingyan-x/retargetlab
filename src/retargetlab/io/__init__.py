"""Input structure and mapping utilities."""

from .normalize import NormalizationError, normalize_rows
from .validate import validate_mapping

__all__ = ["NormalizationError", "normalize_rows", "validate_mapping"]
