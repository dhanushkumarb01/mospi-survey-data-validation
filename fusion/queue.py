"""Workload-aware supervisor queue (plan §8.3, W2.8).

Tier A, "Check now"
    * every finding of an approved hard integrity rule (person or household);
    * value checks whose record-level tail probability is at or below the
      value threshold, strongest first, up to the value share of the review
      budget and at most ``per_fsu_cap`` per FSU;
    * coding checks at or below the coding threshold, up to the coding share.
Tier B, "Check if time"
    * findings of approved soft rules;
    * value or coding checks that passed the threshold but did not fit the
      budget or the FSU cap, and the next band of evidence (threshold x
      ``tier_b_factor``), up to ``tier_b_multiplier`` x budget.

The thresholds are tail probabilities, not ranks: a quiet batch produces a
short list, a degraded batch a long one (capped, with the overflow shown).
Thresholds are the lane's budget divided by the records the lane can assess,
so with calibrated evidence the expected number of alerts among clean records
equals the budget; every run reports the observed rate against that.

Within a tier, cases are ordered by impact (change in the domain estimate in
standard errors), then by evidence; impact never changes which tier a case is
in.  The supervisor's worklist groups cases by FSU and household.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

TIER_LABELS = {"A": "CHECK_NOW", "B": "CHECK_IF_TIME", "NONE": "NOT_FLAGGED", "NOT_ASSESSABLE": "NOT_ASSESSABLE"}


def thresholds(parameters, value_budget: int | None = None, coding_budget: int | None = None,
               value_assessable: int | None = None, coding_assessable: int | None = None) -> dict[str, float]:
    """Per-lane tail-probability thresholds.

    The expected number of alerts among clean records is threshold x the records
    the lane can assess, so the threshold is the lane's budget divided by its
    assessable records (plan §8.3: capacity / records).  Without counts, the
    budget shares of all records are returned (used for reporting only).
    """
    if value_budget is None:
        return {"value": parameters.review_budget_share * (1.0 - parameters.coding_budget_share),
                "coding": parameters.review_budget_share * parameters.coding_budget_share}
    return {"value": min(1.0, value_budget / max(value_assessable or 0, 1)),
            "coding": min(1.0, coding_budget / max(coding_assessable or 0, 1)) if coding_budget else 0.0}


def budgets(parameters, records: int) -> tuple[int, int, int]:
    """(total, value, coding) "Check now" budgets for a batch of ``records`` persons."""
    budget = max(1, math.ceil(parameters.review_budget_share * records))
    value_budget = max(1, math.floor(budget * (1.0 - parameters.coding_budget_share)))
    return budget, value_budget, max(0, budget - value_budget)


def value_threshold(parameters, records: int, value_assessable: int) -> float:
    """The value threshold build_queue will use; known before the evidence is combined (it depends on counts only)."""
    _, value_budget, coding_budget = budgets(parameters, records)
    return thresholds(parameters, value_budget, coding_budget, value_assessable, 0)["value"]


def build_queue(cases: pd.DataFrame, parameters) -> pd.DataFrame:
    """Assign tier, lanes, reason and queue position.  Pure: ``cases`` is not modified."""
    out = cases.copy()
    persons = out["case_level"].eq("PERSON")
    records = int(persons.sum())
    budget, value_budget, coding_budget = budgets(parameters, records)
    value_p = pd.to_numeric(out.get("value_p"), errors="coerce")
    coding_p = pd.to_numeric(out.get("coding_p"), errors="coerce")
    limits = thresholds(parameters, value_budget, coding_budget, int((persons & value_p.notna()).sum()), int((persons & coding_p.notna()).sum()))
    hard = pd.to_numeric(out.get("rule_error_count", 0), errors="coerce").fillna(0).gt(0)
    soft = pd.to_numeric(out.get("rule_warning_count", 0), errors="coerce").fillna(0).gt(0)

    tier = pd.Series("NONE", index=out.index, dtype="object")
    reason = pd.Series("", index=out.index, dtype="object")
    lanes: dict[int, list[str]] = {i: [] for i in out.index}
    tier[hard] = "A"
    reason[hard] = "A documented questionnaire rule is not met."
    for i in out.index[hard]:
        lanes[i].append("RULE")

    fsu_key = out["state"].astype(str) + "|" + out["sector"].astype(str) + "|" + out["fsu"].astype(str)
    per_fsu: dict[str, int] = {}

    # Value lane: strongest evidence first, within budget and FSU cap.
    candidates = out.index[persons & value_p.le(limits["value"])]
    ordered = value_p.loc[candidates].sort_values(kind="mergesort").index
    taken = 0
    for i in ordered:
        lanes[i].append("VALUE")
        if tier[i] == "A":
            continue
        if taken >= value_budget:
            tier[i], reason[i] = "B", "Passed the value-check threshold but the review budget for this batch is full."
            continue
        if parameters.per_fsu_cap and per_fsu.get(fsu_key[i], 0) >= parameters.per_fsu_cap:
            tier[i], reason[i] = "B", f"Passed the value-check threshold; this FSU already has {parameters.per_fsu_cap} value checks in 'Check now'."
            continue
        tier[i], reason[i] = "A", "A reported value is rare for comparable people (value check)."
        per_fsu[fsu_key[i]] = per_fsu.get(fsu_key[i], 0) + 1
        taken += 1

    # Coding lane: its own small share of the budget.
    candidates = out.index[persons & coding_p.le(limits["coding"])]
    taken = 0
    for i in coding_p.loc[candidates].sort_values(kind="mergesort").index:
        lanes[i].append("CODING")
        if tier[i] == "A":
            continue
        if taken >= coding_budget:
            tier[i], reason[i] = "B", "Passed the coding-check threshold but the coding share of the budget is full."
            continue
        tier[i], reason[i] = "A", "The recorded occupation code is rare for comparable people (coding check)."
        taken += 1

    # Tier B: soft rules and the next band of evidence, up to the Tier-B allowance.
    tier_b_allowance = int(parameters.tier_b_multiplier * budget)
    in_b = int(tier.eq("B").sum())
    for i in out.index[soft & tier.eq("NONE")]:
        tier[i], reason[i] = "B", "A soft (warning) questionnaire check is not met."
        lanes[i].append("RULE_SOFT")
        in_b += 1
    band = pd.concat([value_p.where(persons & value_p.gt(limits["value"]) & value_p.le(limits["value"] * parameters.tier_b_factor)) / limits["value"],
                      coding_p.where(persons & coding_p.gt(limits["coding"]) & coding_p.le(limits["coding"] * parameters.tier_b_factor)) / max(limits["coding"], 1e-12)],
                     axis=1).min(axis=1).dropna().sort_values(kind="mergesort")
    for i in band.index:
        if in_b >= tier_b_allowance:
            break
        if tier[i] != "NONE":
            continue
        is_value = pd.notna(value_p[i]) and value_p[i] <= limits["value"] * parameters.tier_b_factor
        tier[i] = "B"
        reason[i] = "Moderately rare for comparable people (next band of evidence)."
        lanes[i].append("VALUE" if is_value else "CODING")
        in_b += 1

    assessable = value_p.notna() | coding_p.notna() | hard | soft
    tier[~assessable & tier.eq("NONE")] = "NOT_ASSESSABLE"
    out["tier"] = tier
    out["priority_band"] = tier.map(TIER_LABELS)
    out["tier_reason"] = reason.replace("", np.nan)
    out["lanes"] = pd.Series({i: ",".join(dict.fromkeys(v)) for i, v in lanes.items()}).reindex(out.index).replace("", np.nan)
    out["lane"] = out["lanes"].str.split(",").str[0]

    # Ordering: rules first in Tier A, then impact, then evidence; Tier B the same; then the rest by evidence.
    tier_order = out["tier"].map({"A": 0, "B": 1, "NONE": 2, "NOT_ASSESSABLE": 3})
    best_p = pd.concat([value_p, coding_p], axis=1).min(axis=1)
    impact = pd.to_numeric(out.get("impact_se"), errors="coerce")
    key = pd.DataFrame({"tier": tier_order, "rule": np.where(hard, 0, 1), "impact": -impact.fillna(-1.0), "p": best_p.fillna(2.0), "id": out["case_id"]})
    key.loc[key["tier"].ge(2), "impact"] = 0.0          # outside the queue, order by evidence only
    order = key.sort_values(["tier", "rule", "impact", "p", "id"], kind="mergesort").index
    position = pd.Series(np.arange(1, len(out) + 1), index=order)
    out["queue_position"] = position.reindex(out.index).astype(int)
    out["priority_score"] = 1.0 - (out["queue_position"] - 1) / max(len(out), 1)
    out.attrs["queue_summary"] = {"records": records, "review_budget_share": parameters.review_budget_share, "budget_cases": budget,
                                  "value_budget": value_budget, "coding_budget": coding_budget, "value_threshold": limits["value"],
                                  "coding_threshold": limits["coding"], "tier_b_allowance": tier_b_allowance, "per_fsu_cap": parameters.per_fsu_cap}
    return out
