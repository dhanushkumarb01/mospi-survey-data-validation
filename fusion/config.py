"""Versioned, deliberately transparent fusion parameters.

v2.1 ("lanes") replaces the V2.0 average-of-ranks x influence priority, whose
measured failure is documented in docs/10_10_IMPROVEMENT_PLAN.md §5.7.  There
are no source weights, no override and no rank bands any more.

v2.2 (9 Oct 2026): discrete-test (Tarone) multiplicity in the value lane, see
fusion/lanes.py.  Measured reason: the v2.1 runs on 2024 and 2025 flagged 0.51
and 0.52 of the nominal rate because small current-peer groups cannot reach
the threshold yet were counted in the Sidak correction.

PROVISIONAL: the review budget and lane shares are defaults until HSD supplies
supervisor capacity (plan §20, open question 6).  None of these numbers has
been learned from confirmed PLFS errors; the evaluation stage (§12) measures
how they behave.
"""

from __future__ import annotations

from dataclasses import dataclass

VALUE_VARIABLES = ("cws_earnings_salaried", "cws_earnings_self_employed", "day7_total_hours", "day7_casual_wage")
FUSION_VERSION = "MoSPI-fusion-v2.2-lanes"


@dataclass(frozen=True)
class FusionParameters:
    """Queue settings (engineering defaults, documented and recorded with every run)."""

    # Share of a batch's records that supervisors can review ("Check now").
    # Default 1% until HSD supplies capacity (cases per supervisor-day x days / records).
    review_budget_share: float = 0.01
    # Share of that budget reserved for occupation coding checks (plan §8.3: 10%).
    coding_budget_share: float = 0.10
    # At most this many value checks per FSU in "Check now"; the rest go to "Check if time".
    per_fsu_cap: int = 10
    # "Check if time": evidence up to this multiple of the threshold, up to this multiple of the budget.
    tier_b_factor: float = 5.0
    tier_b_multiplier: float = 2.0
    # FSU group alerts: FSU-level q-value (Cauchy combination + BH across FSUs).
    group_alert_q: float = 0.05
    group_strong_q: float = 0.01
    # Use the expected-value (conditional) models as a value-check mechanism.
    use_conditional_model: bool = True
    # Leave mechanisms/variables that cannot attain the value threshold out of the Sidak count (Tarone 1990).
    # False reproduces fusion v2.1.
    discrete_test_correction: bool = True
    evidence_card_capacity: int = 10_000
    fusion_version: str = FUSION_VERSION
    calibration_version: str = "finite-sample-tail-probabilities-v2 (LOO peers, out-of-sample history, State-conditional split-conformal model; Tarone count)"
    impact_version: str = "delta-domain-mean-over-design-se-v1"

    def __post_init__(self) -> None:
        if not 0 < self.review_budget_share < 1:
            raise ValueError("review_budget_share must be in (0, 1).")
        if not 0 <= self.coding_budget_share < 1:
            raise ValueError("coding_budget_share must be in [0, 1).")
        if self.per_fsu_cap < 0 or self.tier_b_factor < 1 or self.tier_b_multiplier < 0:
            raise ValueError("per_fsu_cap must be >= 0, tier_b_factor >= 1 and tier_b_multiplier >= 0.")
