"""PLFS Schedule 10.4 rules used by several evidence layers.

Every rule below is transcribed from a document supplied in this repository;
the citation is kept beside the rule so it can be checked and, for another
survey, replaced by that survey's own rules without touching the engines.

Sources
-------
* Instructions to Field Staff, PLFS Vol. I (``Jan-Dec2024/Instruction manual
  PLFS Vol I (1).pdf``; identical text in ``2023-June2024/2_1_...Vol_I.pdf``
  and ``Post2025/PLFS_Vol_I_Instruction_to_FieldStaff_Jul_Dece2025.pdf``).
* Release README files (``1_README.docx``, ``README_Calendar_2024 (3).docx``,
  ``README2025.docx``) for the weighting formulae.
* Data layouts for the NSS / NSC / NO_QTR field meanings.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

APPLICABLE = "APPLICABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"
ZERO_BY_DEFINITION = "ZERO_BY_DEFINITION"

# Vol. I §3.6.17: Block 6 item 9 (earnings during the *preceding calendar
# month* from regular salaried/wage work) is recorded only for current weekly
# status 31, 71 or 72.  §3.6.19: such a person who did not pursue the work in
# that month is recorded as 0, so a zero here is a genuine reported value.
SALARIED_EARNINGS_STATUSES = frozenset({"31", "71", "72"})
# Vol. I §3.6.18: item 10 (gross earnings during the *last 30 days* from
# self-employment) is recorded for status 11, 12, 21, 61 or 62; for helpers
# (21) it is 0 by definition (§1.5.26(g), §3.6.18).  Negative values are valid.
# The Jan–Jun 2025 schedule form lists 11, 12, 61, 62 only; either way code 21
# carries no reported earnings information.
SELF_EMPLOYED_EARNINGS_STATUSES = frozenset({"11", "12", "61", "62"})
SELF_EMPLOYED_ZERO_BY_DEFINITION = frozenset({"21"})
# CWS codes 11–72 are the worker codes (Vol. I Box 7 / §3.6.15).  Day-7 total
# hours actually worked (Block 6 col. 7) is a work-time measure; for persons
# whose CWS is 81–99 it is structurally 0.  A worker with 0 hours on day 7
# (e.g. a day off) is a genuine value.
WORKER_STATUSES = frozenset({"11", "12", "21", "31", "41", "42", "51", "61", "62", "71", "72"})

TARGET_APPLICABILITY: dict[str, dict[str, frozenset[str]]] = {
    "cws_earnings_salaried": {"applicable": SALARIED_EARNINGS_STATUSES, "zero_by_definition": frozenset()},
    "cws_earnings_self_employed": {"applicable": SELF_EMPLOYED_EARNINGS_STATUSES, "zero_by_definition": SELF_EMPLOYED_ZERO_BY_DEFINITION},
    "day7_total_hours": {"applicable": WORKER_STATUSES, "zero_by_definition": frozenset()},
}


def _clean(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in {"nan", "none", "<na>"} else text


def applicability(target: str, cws_status: object) -> str:
    """Return APPLICABLE / ZERO_BY_DEFINITION / NOT_APPLICABLE for one value."""
    rule = TARGET_APPLICABILITY.get(target)
    if rule is None:
        return APPLICABLE
    status = _clean(cws_status)
    if status in rule["applicable"]:
        return APPLICABLE
    if status in rule["zero_by_definition"]:
        return ZERO_BY_DEFINITION
    return NOT_APPLICABLE


def applicability_series(target: str, cws_status: pd.Series) -> pd.Series:
    """Vectorised :func:`applicability`."""
    status = cws_status.astype("string").fillna("").str.strip()
    rule = TARGET_APPLICABILITY.get(target)
    if rule is None:
        return pd.Series(APPLICABLE, index=status.index, dtype="string")
    result = pd.Series(NOT_APPLICABLE, index=status.index, dtype="string")
    result = result.mask(status.isin(rule["zero_by_definition"]), ZERO_BY_DEFINITION)
    return result.mask(status.isin(rule["applicable"]), APPLICABLE)


# Prepared-person columns needed for the documented final weight.
WEIGHT_FIELDS: dict[tuple[str, str], dict[str, str | None]] = {
    ("2023_24", "first_visit"): {"mult": "mult_perv1", "nss": "NSS_perv1", "nsc": "NSC_perv1", "no_qtr": "no_qtr_perv1"},
    ("2023_24", "revisit"): {"mult": "mult_perrv", "nss": "NSS_perrv", "nsc": "NSC_perrv", "no_qtr": "no_qtr_perrv"},
    # Layout rows 137-140: NSS, NSC, MULT, NO_QTR (the CSV header of NO_QTR is
    # truncated to "State_Sector_Stratum_Substra").
    ("2024", "first_visit"): {"mult": "Subsample_Multiplier", "nss": "Ns_Count_Sector_Stratum_Substratum_Subsample",
                              "nsc": "Ns_Count_Sector_Stratum_Substratum", "no_qtr": "State_Sector_Stratum_Substra"},
    ("2025", "first_visit"): {"mult": "mult", "nss": None, "nsc": "nsc", "no_qtr": None},
}


def final_quarterly_weight(release: str, mult: pd.Series, nss: pd.Series | None = None, nsc: pd.Series | None = None) -> pd.Series:
    """Final weight for an estimate of one quarter (pre-2025) or month (2025).

    Pre-2025 READMEs, combined (both sub-samples) estimate: MULT/100 if
    NSS = NSC, otherwise MULT/200.  README2025: MULT/100.  NO_QTR is only
    needed for annual pooling and is therefore not applied here: every use in
    MoSPI is within one quarter or month.
    """
    m = pd.to_numeric(mult, errors="coerce").astype("float64")
    if str(release) == "2025":
        return m / 100.0
    if nss is None or nsc is None:
        return pd.Series(np.nan, index=m.index)
    nss_n, nsc_n = pd.to_numeric(nss, errors="coerce"), pd.to_numeric(nsc, errors="coerce")
    same = nss_n.eq(nsc_n)
    weight = pd.Series(np.where(same, m / 100.0, m / 200.0), index=m.index, dtype="float64")
    return weight.where(nss_n.notna() & nsc_n.notna() & m.notna())


# A single, de-duplicated time axis per design period.  2024 calendar Q3/Q4
# are the same records as 2023-24 Q3/Q4 (verified: 209,512 identical person
# keys and weights), so they share a period index; Q5/Q6 continue the axis.
_PRE_2025_QUARTERS = {
    ("2023_24", "Q1"): (1, "Jul–Sep 2023"), ("2023_24", "Q2"): (2, "Oct–Dec 2023"),
    ("2023_24", "Q3"): (3, "Jan–Mar 2024"), ("2023_24", "Q4"): (4, "Apr–Jun 2024"),
    ("2024", "Q3"): (3, "Jan–Mar 2024"), ("2024", "Q4"): (4, "Apr–Jun 2024"),
    ("2024", "Q5"): (5, "Jul–Sep 2024"), ("2024", "Q6"): (6, "Oct–Dec 2024"),
}
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def period_index(release: str, quarter: object, month: object) -> int | None:
    """Ordinal period within the record's design period (quarters pre-2025, months 2025)."""
    if str(release) == "2025":
        try:
            value = int(float(_clean(month)))
        except ValueError:
            return None
        return value if 1 <= value <= 12 else None
    found = _PRE_2025_QUARTERS.get((str(release), _clean(quarter)))
    return found[0] if found else None


def period_label(design_period: str, index: int | None) -> str:
    if index is None:
        return "unknown period"
    if design_period == "post_2025":
        return f"{_MONTHS[index - 1]} 2025"
    return next((label for (_, _), (i, label) in _PRE_2025_QUARTERS.items() if i == index), f"period {index}")
