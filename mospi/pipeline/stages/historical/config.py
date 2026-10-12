"""Versioned working configuration for the historical layer.

These are research settings, not PLFS error thresholds.  They are recorded in
every run's metadata.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# v1.1: change must also exceed its sampling noise.
# v2.0: finite-sample tail probabilities against the out-of-sample reference;
#       same-season comparison; casual daily wage; design-based standard
#       errors (FSU as PSU within strata) for area indicators; known-events
#       calendar; fail-loud input contract; hashed reference snapshot.
HISTORICAL_METHOD_VERSION = "plfs-historical-v2.0"

RECORD_TARGETS = ("cws_earnings_salaried", "cws_earnings_self_employed", "day7_total_hours", "day7_casual_wage")
# Comparison cells, most detailed first; the first with enough past records is used.
EARNINGS_LEVELS = (("state", "sector", "cws_status", "occupation_major_group"), ("state", "sector", "cws_status"))
HOURS_LEVELS = (("state", "sector", "cws_status", "industry_division"), ("state", "sector", "cws_status"))
CASUAL_WAGE_LEVELS = (("state", "sector", "day7_activity1_status", "day7_activity1_industry"), ("state", "sector", "day7_activity1_status"))
TARGET_LEVELS = {
    "cws_earnings_salaried": EARNINGS_LEVELS, "cws_earnings_self_employed": EARNINGS_LEVELS,
    "day7_total_hours": HOURS_LEVELS, "day7_casual_wage": CASUAL_WAGE_LEVELS,
}

# PLFS Vol. I §1.5.11: workers = CWS 11-72; unemployed = 81 (sought work) and
# 82 (did not seek but available); labour force = workers + unemployed.
WORKER_CODES = frozenset({"11", "12", "21", "31", "41", "42", "51", "61", "62", "71", "72"})
UNEMPLOYED_CODES = frozenset({"81", "82"})
MINIMUM_INDICATOR_AGE = 15  # PLFS headline indicators are reported for persons aged 15 years and above.

# HSD-maintained list of known events (e.g. a wage revision, a festival month)
# whose effect on an area indicator is expected.  Matching changes are shown
# as "expected (known event)" instead of being screened as unusual.  Empty
# until HSD supplies entries; nothing is invented here.
KNOWN_EVENTS_PATH = Path(__file__).parent / "known_events.yaml"


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
    # Same season one year earlier: 4 quarters back (pre-2025).  For 2025
    # the same month one year earlier lies across the design break, so it is
    # never used (it needs 2026 data, plan gate G7).
    pre_2025_same_season_lag: int = 4
    # Aggregate screening: a domain-period needs this many unweighted persons
    # (age 15+) in both periods; a change is notable when its robust z among
    # the same period's domain changes is at least this large (Iglewicz-Hoaglin 3.5).
    minimum_domain_persons: int = 150
    minimum_domain_earners: int = 30
    notable_robust_z: float = 3.5
    # ...and the change must also exceed 3 design-based standard errors of the
    # change (FSU as PSU within strata), so sampling noise in small domains is
    # not screened as unusual change.
    notable_change_over_se: float = 3.0

    def window(self, design_period: str) -> int:
        return self.post_2025_window_periods if design_period == "post_2025" else self.pre_2025_window_periods

    def same_season_lag(self, design_period: str) -> int | None:
        return None if design_period == "post_2025" else self.pre_2025_same_season_lag
