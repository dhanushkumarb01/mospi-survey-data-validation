"""Versioned working configuration for the historical layer.

These are research settings, not PLFS error thresholds.  They are recorded in
every run's metadata.
"""
from __future__ import annotations

from dataclasses import dataclass

HISTORICAL_METHOD_VERSION = "plfs-historical-v1.1"  # v1.1: change must also exceed its sampling noise

RECORD_TARGETS = ("cws_earnings_salaried", "cws_earnings_self_employed", "day7_total_hours")
# Comparison cells, most detailed first; the first with enough past records is used.
EARNINGS_LEVELS = (("state", "sector", "cws_status", "occupation_major_group"), ("state", "sector", "cws_status"))
HOURS_LEVELS = (("state", "sector", "cws_status", "industry_division"), ("state", "sector", "cws_status"))

# PLFS Vol. I §1.5.11: workers = CWS 11-72; unemployed = 81 (sought work) and
# 82 (did not seek but available); labour force = workers + unemployed.
WORKER_CODES = frozenset({"11", "12", "21", "31", "41", "42", "51", "61", "62", "71", "72"})
UNEMPLOYED_CODES = frozenset({"81", "82"})
MINIMUM_INDICATOR_AGE = 15  # PLFS headline indicators are reported for persons aged 15 years and above.


@dataclass(frozen=True)
class HistoricalParameters:
    # Pre-2025: up to four preceding quarters (one year).  Post-2025: up to
    # three preceding months, kept short because monthly 2025 estimates are
    # seasonal and only 2025 exists after the January-2025 design break.
    pre_2025_window_periods: int = 4
    post_2025_window_periods: int = 3
    minimum_reference_size: int = 30
    lower_tail_quantile: float = 0.05
    upper_tail_quantile: float = 0.95
    # Aggregate screening: a domain-period needs this many unweighted persons
    # (age 15+) in both periods; a change is notable when its robust z among
    # the same period's domain changes is at least this large (Iglewicz-Hoaglin 3.5).
    minimum_domain_persons: int = 150
    minimum_domain_earners: int = 30
    notable_robust_z: float = 3.5
    # ...and the change must also exceed 3 simple-random-sampling standard errors,
    # so that small domains' sampling noise is not screened as unusual change.
    notable_change_over_se: float = 3.0

    def window(self, design_period: str) -> int:
        return self.post_2025_window_periods if design_period == "post_2025" else self.pre_2025_window_periods
