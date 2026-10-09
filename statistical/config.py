"""Versioned parameters and source mappings for the Statistical Evidence Layer."""

from __future__ import annotations

from dataclasses import dataclass


# v1.1: questionnaire applicability gate.  v2.0: leave-one-out placement and
# finite-sample (conformal) tail probabilities; day-7 casual wage target.
STATISTICAL_METHOD_VERSION = "plfs-statistical-v2.0"
APPROVED_TARGETS = (
    "cws_earnings_salaried",
    "cws_earnings_self_employed",
    "day7_total_hours",
    "day7_casual_wage",
)


@dataclass(frozen=True)
class StatisticalParameters:
    """Research working parameters; they describe distributions, never errors."""

    lower_tail_quantile: float = 0.05
    upper_tail_quantile: float = 0.95
    minimum_revisit_change_group_size: int = 30

    def __post_init__(self) -> None:
        if not 0 <= self.lower_tail_quantile < 0.5:
            raise ValueError("lower_tail_quantile must be in [0, 0.5)")
        if not 0.5 < self.upper_tail_quantile <= 1:
            raise ValueError("upper_tail_quantile must be in (0.5, 1]")
        if self.lower_tail_quantile >= self.upper_tail_quantile:
            raise ValueError("tail quantiles must be ordered")
        if self.minimum_revisit_change_group_size < 2:
            raise ValueError("minimum_revisit_change_group_size must be at least 2")


# These keys are the documented exact Release-1 linkage identity, excluding
# quarter and visit.  They deliberately do not attempt any cross-release join.
REVISIT_LINK_COLUMNS = {
    "first_visit": (
        "MoSPI_state", "distcode_perv1", "MoSPI_sector", "b1q1_perv1",
        "b1q13_perv1", "b1q14_perv1", "b1q15_perv1", "b4q1_perv1",
    ),
    "revisit": (
        "MoSPI_state", "dist_code_perrv", "MoSPI_sector", "b1q1_perrv",
        "b1q13_perrv", "b1q14_perrv", "b1q15_perrv", "b4q1_pervv",
    ),
}
