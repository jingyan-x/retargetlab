"""Backend-agnostic sequence and cross-stream solve orchestration."""

from .coupling import SolveCoupling, solve_coupled
from .sequence import StreamSolution, solve_stream

__all__ = ["SolveCoupling", "StreamSolution", "solve_coupled", "solve_stream"]
