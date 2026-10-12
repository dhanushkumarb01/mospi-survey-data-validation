"""Configurable, release-aware PLFS peer-group construction."""

from .config import DEFAULT_SPECIFICATIONS, PEER_GROUP_SPECIFICATION_VERSION
from .engine import PeerGroupEngine, PeerGroupFailure, RunConfig

__all__ = [
    "DEFAULT_SPECIFICATIONS",
    "PEER_GROUP_SPECIFICATION_VERSION",
    "PeerGroupEngine",
    "PeerGroupFailure",
    "RunConfig",
]
