"""Controlled, seeded error injection into a copy of a prepared PLFS delivery.

The injected file is written to a separate evaluation directory with its own
run metadata (flagged ``evaluation_injected``); the real prepared runs are
never modified.  Every injected change is recorded in ``injection_labels``.

Error types (research design §17; only types that exist in a first-visit
delivery are used; panel/revisit inconsistencies cannot be injected here):

    scale_x10            earnings multiplied by 10 (an extra zero)
    scale_div10          earnings divided by 10 (a lost zero)
    digit_transposition  first two digits of earnings swapped (e.g. 15000 -> 51000)
    occupation_miscode   3-digit occupation code replaced by a code of another major group
    hours_keying         day-7 hours h replaced by h + 10 (a stray leading 1), within 0-24
    status_earnings_rule salaried worker's activity status changed to 91 with earnings kept
    age_status_rule      worker's age keyed as 3
    duplicate_person     a person's answers copied from another person of the same FSU
    fsu_fabrication      (group) every age in an FSU rounded to a multiple of 5 and every
                         salaried earner given the same earnings value

Catalogue v2 additions (plan §12.3):
    scale_x12            earnings x12 (a yearly amount entered as monthly)
    scale_x100           earnings x100 (two extra zeros)
    plausible_but_wrong  earnings replaced by a value from the 80th-97th percentile of the
                         same activity status in a *different* State (rule-valid, not extreme)
    casual_wage_x10      day-7 casual wage x10
    copied_household     (household) every person of a household gets the answers of the
                         corresponding person of another household in the FSU
    fsu_short_interviews (group, paradata) every household interview duration in an FSU / 3
    fsu_one_day          (group, paradata) every household of an FSU interviewed on one date
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from peer_groups.config import SOURCE_PROFILES
from preprocessing.config import CONTRACTS
from survey_rules import APPLICABLE, applicability_series

CATALOGUE_VERSION = "plfs-injection-catalogue-v2"
RECORD_TYPES = ("scale_x10", "scale_div10", "digit_transposition", "occupation_miscode", "hours_keying",
                "status_earnings_rule", "age_status_rule", "duplicate_person",
                "scale_x12", "scale_x100", "plausible_but_wrong", "casual_wage_x10")
GROUP_TYPES = ("fsu_fabrication", "copied_household", "fsu_short_interviews", "fsu_one_day")


@dataclass(frozen=True)
class InjectionPlan:
    per_type: int = 300
    fabricated_fsus: int = 30
    seed: int = 20261003
    copied_households: int = 30
    paradata_fsus: int = 30


def _fields(release: str) -> dict[str, str]:
    profile = SOURCE_PROFILES[(release, "first_visit")]
    contract = next(c for c in CONTRACTS.values() if (c.release, c.observation) == (release, "first_visit"))
    return {"serial": profile.person_serial_column, "status": profile.context_columns["cws_status"], "age": contract.person_fields["age"],
            "occupation": profile.context_columns["occupation_major_group"], "salaried": profile.target_columns["cws_earnings_salaried"],
            "self_employed": profile.target_columns["cws_earnings_self_employed"], "hours": profile.target_columns["day7_total_hours"],
            "wage": profile.target_columns.get("day7_casual_wage"), "day_status": profile.context_columns.get("day7_activity1_status")}


def _swap_first_digits(value: float) -> float | None:
    text = str(int(round(value)))
    if len(text) < 3 or text[0] == text[1]:
        return None
    swapped = float(text[1] + text[0] + text[2:])
    return swapped if swapped > 0 and abs(swapped - value) / value >= .2 else None


def inject(frame: pd.DataFrame, release: str, plan: InjectionPlan, eligible_mask: pd.Series | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (modified copy, labels).  ``eligible_mask`` limits which rows may be altered (e.g. months with history)."""
    f = _fields(release)
    rng = np.random.default_rng(plan.seed)
    data = frame.copy()
    status = data[f["status"]].astype("string").fillna("").str.strip()
    ids = data["MoSPI_record_key"].astype(str) + "|person=" + data[f["serial"]].astype(str).str.strip()
    allowed = eligible_mask.reindex(data.index).fillna(False).to_numpy() if eligible_mask is not None else np.ones(len(data), dtype=bool)
    salaried = applicability_series("cws_earnings_salaried", status).eq(APPLICABLE).to_numpy() & (pd.to_numeric(data[f["salaried"]], errors="coerce") > 0).to_numpy()
    self_emp = applicability_series("cws_earnings_self_employed", status).eq(APPLICABLE).to_numpy() & (pd.to_numeric(data[f["self_employed"]], errors="coerce") > 0).to_numpy()
    worker = applicability_series("day7_total_hours", status).eq(APPLICABLE).to_numpy()
    occupation = data[f["occupation"]].astype("string").fillna("").str.strip()
    used = np.zeros(len(data), dtype=bool)
    labels = []

    def pick(mask: np.ndarray, n: int) -> np.ndarray:
        candidates = np.flatnonzero(mask & allowed & ~used)
        chosen = rng.choice(candidates, size=min(n, len(candidates)), replace=False) if len(candidates) else np.array([], dtype=int)
        used[chosen] = True
        return np.sort(chosen)

    def label(rows, kind, field, before, after, level="record"):
        for r, b, a in zip(rows, before, after):
            labels.append({"source_observation_id": ids.iloc[r], "error_type": kind, "level": level, "field": field, "original": str(b), "injected": str(a)})

    earner = salaried | self_emp
    for kind in ("scale_x10", "scale_div10", "digit_transposition", "scale_x12", "scale_x100"):
        rows = pick(earner, plan.per_type)
        for r in rows:
            column = f["salaried"] if salaried[r] else f["self_employed"]
            before = float(data.iloc[r][column])
            if kind == "scale_x10":
                after = before * 10
            elif kind == "scale_x12":
                after = before * 12
            elif kind == "scale_x100":
                after = before * 100
            elif kind == "scale_div10":
                after = round(before / 10)
            else:
                after = _swap_first_digits(before)
                if after is None:
                    continue
            data.iat[r, data.columns.get_loc(column)] = str(int(after))
            label([r], kind, column, [before], [int(after)])
    # plausible_but_wrong: an ordinary-looking value from another State's distribution (80th-97th percentile).
    state = data["MoSPI_state"].astype(str)
    salary_values = pd.to_numeric(data[f["salaried"]], errors="coerce")
    for r in pick(salaried, plan.per_type):
        others = salary_values[salaried & (state != state.iloc[r]).to_numpy()]
        if len(others) < 50:
            continue
        low, high = np.quantile(others, [0.80, 0.97])
        pool = others[(others >= low) & (others <= high)].to_numpy()
        after = float(pool[int(rng.integers(len(pool)))])
        before = float(salary_values.iloc[r])
        if abs(after - before) / max(before, 1.0) < 0.2:
            continue
        data.iat[r, data.columns.get_loc(f["salaried"])] = str(int(after))
        label([r], "plausible_but_wrong", f["salaried"], [before], [int(after)])
    if f["wage"] and f["day_status"]:
        casual = data[f["day_status"]].astype("string").fillna("").str.strip().isin(["41", "42", "51"]).to_numpy() & (pd.to_numeric(data[f["wage"]], errors="coerce") > 0).to_numpy()
        for r in pick(casual, plan.per_type):
            before = float(data.iloc[r][f["wage"]])
            data.iat[r, data.columns.get_loc(f["wage"])] = str(int(before * 10))
            label([r], "casual_wage_x10", f["wage"], [before], [int(before * 10)])
    codes = sorted(set(occupation[occupation.str.fullmatch(r"\d{3}")]))
    for r in pick(occupation.str.fullmatch(r"\d{3}").fillna(False).to_numpy() & worker, plan.per_type):
        original = occupation.iloc[r]
        options = [c for c in codes if c[0] != original[0]]
        new = options[int(rng.integers(len(options)))]
        data.iat[r, data.columns.get_loc(f["occupation"])] = new
        label([r], "occupation_miscode", f["occupation"], [original], [new])
    hours = pd.to_numeric(data[f["hours"]], errors="coerce").to_numpy()
    for r in pick(worker & (hours >= 1) & (hours <= 14), plan.per_type):
        new = hours[r] + 10
        data.iat[r, data.columns.get_loc(f["hours"])] = str(int(new)) if float(new).is_integer() else str(new)
        label([r], "hours_keying", f["hours"], [hours[r]], [new])
    for r in pick(salaried & status.eq("31").to_numpy(), plan.per_type):
        data.iat[r, data.columns.get_loc(f["status"])] = "91"
        label([r], "status_earnings_rule", f["status"], ["31"], ["91"])
    ages = pd.to_numeric(data[f["age"]], errors="coerce").to_numpy()
    for r in pick(worker & (ages >= 15), plan.per_type):
        data.iat[r, data.columns.get_loc(f["age"])] = "3"
        label([r], "age_status_rule", f["age"], [ages[r]], [3])
    # duplicate_person: copy every response field (not identifiers) from another person of the same FSU.
    fsu_key = data["MoSPI_state"].astype(str) + "|" + data["MoSPI_sector"].astype(str) + "|" + data["MoSPI_fsu"].astype(str)
    response = [f["status"], f["age"], f["occupation"], f["salaried"], f["self_employed"], f["hours"]]
    targets = pick(np.ones(len(data), dtype=bool), plan.per_type)
    for r in targets:
        donors = np.flatnonzero((fsu_key == fsu_key.iloc[r]).to_numpy() & ~used)
        donors = donors[donors != r]
        if not len(donors):
            continue
        d = int(donors[int(rng.integers(len(donors)))])
        changed = False
        for column in response:
            position = data.columns.get_loc(column)
            changed |= str(data.iat[r, position]) != str(data.iat[d, position])
            data.iat[r, position] = data.iat[d, position]
        if changed:  # identical answers already: nothing was injected, so no label
            label([r], "duplicate_person", "all response fields", [ids.iloc[d]], ["copied"])
    # copied household: each person of household B takes the answers of the same-position person of household A (same FSU).
    response_all = [c for c in (f["status"], f["age"], f["occupation"], f["salaried"], f["self_employed"], f["hours"]) if c]
    household = data["MoSPI_record_key"].astype(str)
    copied = 0
    for key in rng.permutation(fsu_key[allowed & ~used].unique()):
        if copied >= plan.copied_households:
            break
        members = data.index[(fsu_key == key).to_numpy() & allowed & ~used]
        households = household.loc[members].unique()
        if len(households) < 2:
            continue
        source_rows = members[household.loc[members].eq(households[0]).to_numpy()]
        target_rows = members[household.loc[members].eq(households[1]).to_numpy()]
        pairs = list(zip(target_rows, source_rows))
        if len(pairs) < 2:
            continue
        for target, source in pairs:
            for column in response_all:
                data.iat[target, data.columns.get_loc(column)] = data.iat[source, data.columns.get_loc(column)]
            used[target] = True
        labels.append({"source_observation_id": households[1], "error_type": "copied_household", "level": "household", "field": "all response fields",
                       "original": "", "injected": f"copied from {households[0]}; FSU {key}"})
        labels.append({"source_observation_id": key, "error_type": "copied_household", "level": "group", "field": "all response fields",
                       "original": "", "injected": f"household {households[1]} copies {households[0]}"})
        copied += 1
    # group-level fabrication
    fsu_sizes = fsu_key[allowed & ~used].value_counts()
    fsus = rng.choice(fsu_sizes[fsu_sizes >= 15].index.to_numpy(), size=min(plan.fabricated_fsus, int((fsu_sizes >= 15).sum())), replace=False)
    for key in fsus:
        rows = np.flatnonzero((fsu_key == key).to_numpy() & ~used)
        for r in rows:
            if np.isfinite(ages[r]) and ages[r] >= 5:
                data.iat[r, data.columns.get_loc(f["age"])] = str(int(5 * round(ages[r] / 5)))
        earners = rows[salaried[rows]]
        if len(earners):
            data.iloc[earners, data.columns.get_loc(f["salaried"])] = "15000"
        used[rows] = True
        labels.append({"source_observation_id": key, "error_type": "fsu_fabrication", "level": "group", "field": "age, salaried earnings",
                       "original": "", "injected": f"{len(rows)} persons"})
    return data, pd.DataFrame(labels)


def inject_paradata(households: pd.DataFrame, release: str, plan: InjectionPlan, excluded_fsus: set[str]) -> tuple[pd.DataFrame, list[dict]]:
    """FSU-level fieldwork variants on the household file: short interviews and one-day completion."""
    contract = next(c for c in CONTRACTS.values() if (c.release, c.observation) == (release, "first_visit"))
    duration, date = contract.household_fields["survey_duration"], contract.household_fields["survey_date"]
    rng = np.random.default_rng(plan.seed + 7)
    data = households.copy()
    key = data["MoSPI_state"].astype(str) + "|" + data["MoSPI_sector"].astype(str) + "|" + data["MoSPI_fsu"].astype(str)
    candidates = [k for k in key.value_counts()[lambda s: s >= 6].index if k not in excluded_fsus]
    chosen = rng.choice(np.array(candidates, dtype=object), size=min(2 * plan.paradata_fsus, len(candidates)), replace=False) if candidates else []
    labels = []
    for number, fsu in enumerate(chosen):
        rows = key.eq(fsu)
        if number % 2 == 0:
            minutes = pd.to_numeric(data.loc[rows, duration], errors="coerce")
            data.loc[rows, duration] = (minutes / 3).round().clip(lower=5).astype("Int64").astype(str)
            labels.append({"source_observation_id": fsu, "error_type": "fsu_short_interviews", "level": "group", "field": duration, "original": "", "injected": "duration / 3"})
        else:
            first = str(data.loc[rows, date].iloc[0])
            data.loc[rows, date] = first
            labels.append({"source_observation_id": fsu, "error_type": "fsu_one_day", "level": "group", "field": date, "original": "", "injected": f"all on {first}"})
    return data, labels


def write_injected(source: Path, destination: Path, release: str, plan: InjectionPlan, *, states: tuple[str, ...], months: tuple[int, ...] | None = None,
                   inject_months: tuple[int, ...] | None = None, inject_errors: bool = True) -> tuple[Path, pd.DataFrame]:
    """Write a State (and month) subset of a prepared delivery, with injected errors and their labels.

    The household file of the same preparation run is subset alongside, so the
    household rules and FSU paradata checks run on the evaluation copy.
    """
    from survey_rules.schema import canonicalise
    meta = json.loads((source.parent / "run_metadata.json").read_text(encoding="utf-8"))
    frame = canonicalise(pd.read_parquet(source))
    keep = frame["MoSPI_state"].astype(str).isin(states)
    if months is not None:
        keep &= pd.to_numeric(frame["MoSPI_month"], errors="coerce").isin(months)
    frame = frame.loc[keep].reset_index(drop=True)
    households = None
    if (source.parent / "prepared_households.parquet").is_file():
        households = canonicalise(pd.read_parquet(source.parent / "prepared_households.parquet"))
        households = households.loc[households["MoSPI_record_key"].isin(set(frame["MoSPI_record_key"]))].reset_index(drop=True)
    labels = pd.DataFrame(columns=["source_observation_id", "error_type", "level", "field", "original", "injected"])
    if inject_errors:
        eligible = pd.to_numeric(frame["MoSPI_month"], errors="coerce").isin(inject_months) if inject_months else None
        frame, labels = inject(frame, release, plan, eligible)
        if households is not None:
            touched = set(labels.loc[labels.level.eq("group"), "source_observation_id"])
            households, paradata = inject_paradata(households, release, plan, touched)
            labels = pd.concat([labels, pd.DataFrame(paradata)], ignore_index=True)
    destination.mkdir(parents=True, exist_ok=False)
    frame.to_parquet(destination / "prepared_persons.parquet", index=False)
    if households is not None:
        households.to_parquet(destination / "prepared_households.parquet", index=False)
    run_id = destination.name
    (destination / "run_metadata.json").write_text(json.dumps({**meta, "run_id": run_id, "evaluation_subset_of": meta["run_id"], "evaluation_states": list(states),
                                                              "evaluation_months": list(months) if months else None, "evaluation_injected": inject_errors, "catalogue_version": CATALOGUE_VERSION,
                                                              "injection_plan": plan.__dict__ if inject_errors else None}, indent=2), encoding="utf-8")
    labels.to_parquet(destination / "injection_labels.parquet", index=False)
    return destination / "prepared_persons.parquet", labels
