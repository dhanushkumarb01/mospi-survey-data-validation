"""Versioned, conservative working configuration for Pattern V1.

The values here are research operating settings, not PLFS error thresholds or
claims of statistical optimality.  Targets are configured separately from the
generic aggregate calculations so another survey can supply an adapter.
"""
from __future__ import annotations

from dataclasses import dataclass


PATTERN_METHOD_VERSION = "plfs-pattern-v1.1"  # tested scores, applicability, q-values
PATTERN_SPECIFICATION_VERSION = "plfs-pattern-spec-v1.1"
READY_STATUS = "ready_for_downstream_preparation_only"


@dataclass(frozen=True)
class PatternParameters:
    """V1 research configuration. Scores are evidence ranks, never probabilities."""

    minimum_fsu_population: int = 10
    minimum_reference_population: int = 30
    minimum_valid_target_population: int = 10
    minimum_temporal_history: int = 2
    minimum_temporal_population: int = 10
    minimum_revisit_linked_population: int = 10
    categorical_targets: tuple[str, ...] = (
        "cws_status", "principal_occupation_major_group", "principal_industry_division",
    )
    numerical_targets: tuple[str, ...] = (
        "day7_total_hours", "cws_earnings_salaried", "cws_earnings_self_employed", "age",
    )
    # Only age: 0/5 terminal-digit preference is an established heaping
    # signal for age; rupee amounts are routinely rounded and day-7 hours are
    # not a terminal-digit measure (audit H4/H5).
    heaping_targets: tuple[str, ...] = ("age",)
    temporal_targets: tuple[str, ...] = (
        "day7_total_hours", "cws_earnings_salaried", "cws_earnings_self_employed", "age", "cws_status",
    )
    distribution_metric: str = "g_test_williams_corrected_minus_log10_p"
    numerical_distance_metric: str = "mann_whitney_two_sided_minus_log10_p"
    concentration_metric: str = "one_sided_binomial_share_inside_reference_iqr"
    heaping_metric: str = "one_sided_binomial_share_ending_0_or_5"
    multiplicity: str = "benjamini_hochberg_within_component_and_variable"
    notable_q_value: float = 0.05
    ranking_method: str = "empirical_percentile_of_minus_log10_p_among_assessable_fsus"

    def __post_init__(self) -> None:
        for name in (
            "minimum_fsu_population", "minimum_reference_population", "minimum_valid_target_population",
            "minimum_temporal_history", "minimum_temporal_population", "minimum_revisit_linked_population",
        ):
            if getattr(self, name) < 2:
                raise ValueError(f"{name} must be at least 2")
