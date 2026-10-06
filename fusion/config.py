"""Versioned, deliberately transparent fusion parameters (V2).

PROVISIONAL: every number here is an engineering setting.  None has been
learned from confirmed PLFS errors; the controlled injection study
(evaluation/) measures how they behave, it does not make them "optimal".
"""

from __future__ import annotations

from dataclasses import dataclass, field

RECORD_SOURCES = ("statistical", "contextual", "ml", "historical")


@dataclass(frozen=True)
class FusionParameters:
    """Engineering settings, not learned PLFS error-model parameters."""

    # Record-level evidence only.  FSU (Pattern) evidence describes a group and
    # is deliberately NOT part of an individual record's risk (audit H3).
    source_weights: dict[str, float] = field(
        default_factory=lambda: {"statistical": 0.30, "contextual": 0.20, "ml": 0.25, "historical": 0.25}
    )
    # A record-level percentile rank at or above this sets risk to at least
    # that rank, so one exceptional source is not diluted by ordinary ones.
    override_rank_threshold: float = 0.995
    priority_bands: tuple[tuple[str, float], ...] = (
        ("CRITICAL", 0.80),
        ("HIGH", 0.50),
        ("MEDIUM", 0.20),
        ("LOW", 0.00),
    )
    # FSU group alerts: Benjamini-Hochberg q-value of the strongest FSU check.
    group_bands: tuple[tuple[str, float], ...] = (("HIGH", 0.01), ("MEDIUM", 0.05))
    calibration_version: str = "percentile-midrank-v2-zero-deviation-is-no-evidence"
    fusion_version: str = "MoSPI-fusion-v2.0"
    influence_version: str = "selective-editing-local-score-v2-provisional"
    evidence_card_capacity: int = 10_000

    def __post_init__(self) -> None:
        if set(self.source_weights) != set(RECORD_SOURCES) or any(v < 0 for v in self.source_weights.values()):
            raise ValueError(f"Fusion weights must be non-negative and name each record-level source: {RECORD_SOURCES}.")
        if sum(self.source_weights.values()) <= 0:
            raise ValueError("At least one fusion weight must be positive.")
        if not 0 < self.override_rank_threshold <= 1:
            raise ValueError("override_rank_threshold must be in (0, 1].")
