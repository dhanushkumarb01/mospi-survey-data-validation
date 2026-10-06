"""Transparent, peer-conditioned statistical evidence for PLFS V1."""

from .config import STATISTICAL_METHOD_VERSION
from .engine import StatisticalEngine, StatisticalFailure, RunConfig

__all__ = ["STATISTICAL_METHOD_VERSION", "RunConfig", "StatisticalEngine", "StatisticalFailure"]
