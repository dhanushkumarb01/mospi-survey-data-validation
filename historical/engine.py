"""Historical evidence across survey periods, inside one design period.

Record level
    Each applicable earnings/hours/wage value of the *target* release is
    compared with the same comparison cell (State/UT x sector x activity
    status [x occupation group or industry division]) reported in strictly
    *preceding* periods of the same design period: up to four quarters before
    2025, up to three months in 2025.  No record is linked across releases
    and nothing crosses the January-2025 redesign.

    The reference never contains the record itself or any record of the
    current period, so it is out-of-sample: the tail probabilities
    ``(#reference >= x + 1) / (n + 1)`` are finite-sample (conformal)
    probabilities, valid when the record is exchangeable with the earlier
    records of its cell.  Earnings are nominal rupees (no deflator has been
    approved), so a modest upward drift over a year is expected.

    Pre-2025, a second comparison with the *same quarter one year earlier*
    is shown where the de-duplicated axis has it (Q5/Q6 of calendar 2024
    against Jul-Sep / Oct-Dec 2023).  The same month one year earlier is not
    available for 2025 (it lies across the redesign; needs 2026 data).

    The pre-2025 releases overlap: Calendar-2024 Q3/Q4 are the same records as
    2023-24 Q3/Q4.  Periods are therefore placed on one de-duplicated quarter
    axis (survey_rules.period_index) and each period is taken from one release
    only, so no record is ever compared with itself.

Aggregate level
    Weighted current-weekly-status indicators (LFPR, WPR, UR for ages 15+,
    weighted median salaried earnings among applicable earners, weighted mean
    day-7 hours among workers) by sector for the nation, each State/UT and each
    district, per period, with the documented final weight and a design-based
    standard error (FSU as PSU within strata; survey_rules.variance).  A
    period-on-period change is screened against the changes of the *other
    domains in the same period* (robust z) and must also exceed three
    design-based standard errors of the change.  This is screening of
    first-visit records, not an official estimate (urban quarterly estimates
    also use revisits).
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from peer_groups.config import SOURCE_PROFILES
from preprocessing.config import CONTRACTS
from survey_rules import APPLICABLE, WEIGHT_FIELDS, applicability_series, final_quarterly_weight, period_index, period_label, status_concept
from survey_rules.schema import SchemaError, read_parquet
from survey_rules.variance import median_estimate, ratio_estimate

from .config import (HISTORICAL_METHOD_VERSION, KNOWN_EVENTS_PATH, MINIMUM_INDICATOR_AGE, RECORD_TARGETS, TARGET_LEVELS,
                     UNEMPLOYED_CODES, WORKER_CODES, HistoricalParameters)

READY = "ready_for_downstream_preparation_only"
CELL_CONCEPTS = ("state", "sector", "cws_status", "occupation_major_group", "industry_division", "day7_activity1_status", "day7_activity1_industry")


class HistoricalFailure(RuntimeError):
    """Unsafe or incompatible historical inputs."""


@dataclass(frozen=True)
class RunConfig:
    target_prepared_persons: Path
    reference_prepared_persons: tuple[Path, ...]
    output_root: Path
    run_id: str | None = None
    parameters: HistoricalParameters = field(default_factory=HistoricalParameters)


def _clean(values: pd.Series) -> pd.Series:
    return values.astype("string").fillna("").str.strip()


def _metadata(path: Path) -> dict[str, object]:
    file = path.parent / "run_metadata.json"
    if not file.is_file():
        raise HistoricalFailure(f"Prepared input must have adjacent run_metadata.json: {file}")
    return json.loads(file.read_text(encoding="utf-8"))


def load_release(path: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    """Read the documented fields of one prepared-person delivery into a common schema.

    Every column below is REQUIRED (plan W0.2): an absent column raises
    instead of becoming blank.  A blank-filled column once produced an
    all-"not assessable" historical run that looked like a success.
    """
    meta = _metadata(path)
    key = (str(meta["release"]), str(meta["observation"]))
    profile, weights = SOURCE_PROFILES.get(key), WEIGHT_FIELDS.get(key)
    contract = next((c for c in CONTRACTS.values() if (c.release, c.observation) == key), None)
    if profile is None or weights is None or contract is None:
        raise HistoricalFailure(f"No documented field mapping for {key}")
    columns = {
        "MoSPI_record_key": "record_key", "MoSPI_source_row": "source_row", "MoSPI_release": "release", "MoSPI_observation": "observation_type",
        "MoSPI_design_period": "design_period", "MoSPI_state": "state", "MoSPI_sector": "sector", "MoSPI_prepared_status": "prepared_status",
        "MoSPI_stratum": "stratum", "MoSPI_fsu": "fsu", "MoSPI_quarter": "quarter",
        profile.person_serial_column: "serial", contract.person_fields["age"]: "age", contract.person_fields["district"]: "district",
    }
    if str(meta["design_period"]) == "post_2025":
        columns["MoSPI_month"] = "month"
    for concept, column in profile.context_columns.items():
        if concept in ("cws_status", "day7_activity1_status"):
            columns[column] = concept
        elif concept in ("occupation_major_group", "industry_division", "day7_activity1_industry"):
            columns[column] = f"raw_{concept}"
    for target, column in profile.target_columns.items():
        columns[column] = target
    for concept, column in weights.items():
        if column:
            columns[column] = f"w_{concept}"
    try:
        frame = read_parquet(path, columns=list(columns)).rename(columns=columns)
    except SchemaError as error:
        raise HistoricalFailure(f"Prepared input {path} cannot supply the documented historical fields: {error}") from error
    if "month" not in frame:
        frame["month"] = ""  # pre-2025: the design has no month axis (by design, not missing data)
    if "day7_activity1_status" not in frame:
        frame["day7_activity1_status"] = ""  # observation route without day-wise activity (revisit): wage not applicable
    for name in ("record_key", "release", "observation_type", "design_period", "state", "sector", "stratum", "fsu", "serial", "cws_status",
                 "day7_activity1_status", "district", "quarter", "month", "prepared_status"):
        frame[name] = _clean(frame[name])
    for name in ("release", "observation_type", "design_period"):
        if frame[name].eq("").any():
            raise HistoricalFailure(f"Prepared input {path} has blank {name} values; refusing to build historical evidence.")
    fallback = _clean(frame["source_row"].astype("string"))
    frame["source_observation_id"] = frame["record_key"].str.cat(frame["serial"].mask(frame["serial"].eq(""), fallback), sep="|person=")
    blank = pd.Series("", index=frame.index, dtype="string")
    occupation = _clean(frame["raw_occupation_major_group"]) if "raw_occupation_major_group" in frame else blank
    industry = _clean(frame["raw_industry_division"]) if "raw_industry_division" in frame else blank
    day_industry = _clean(frame["raw_day7_activity1_industry"]) if "raw_day7_activity1_industry" in frame else blank
    frame["occupation_major_group"] = occupation.where(occupation.str.fullmatch(r"\d{3}"), "").str.slice(0, 1)
    frame["industry_division"] = industry.where(industry.str.fullmatch(r"\d{4,5}"), "").str.slice(0, 2)
    frame["day7_activity1_industry"] = day_industry.where(day_industry.str.fullmatch(r"\d{1,2}"), "").str.zfill(2).where(day_industry.str.fullmatch(r"\d{1,2}"), "")
    frame["period_index"] = [period_index(r, q, m) for r, q, m in zip(frame["release"], frame["quarter"], frame["month"])]
    if frame["period_index"].isna().all():
        raise HistoricalFailure(f"Prepared input {path} has no recognised survey period; refusing to build historical evidence.")
    frame["age"] = pd.to_numeric(frame["age"], errors="coerce")
    for target in RECORD_TARGETS:
        frame[target] = pd.to_numeric(frame[target], errors="coerce") if target in frame else np.nan
        frame[f"{target}__applicable"] = applicability_series(target, frame[status_concept(target)]).eq(APPLICABLE).to_numpy()
    nss = frame["w_nss"] if "w_nss" in frame and frame["w_nss"].astype(str).str.strip().ne("").any() else None
    nsc = frame["w_nsc"] if "w_nsc" in frame else None
    frame["final_weight"] = final_quarterly_weight(str(meta["release"]), frame["w_mult"], nss, nsc)
    frame["ready"] = frame["prepared_status"].eq(READY)
    return frame, meta


def deduplicate_periods(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """One copy of each period: the first supplied release that contains it."""
    taken: set[int] = set()
    parts = []
    for frame in frames:
        periods = set(frame["period_index"].dropna().astype(int)) - taken
        parts.append(frame[frame["period_index"].isin(periods)])
        taken |= periods
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _position(values: np.ndarray, reference: np.ndarray) -> np.ndarray:
    ordered = np.sort(reference)
    below = np.searchsorted(ordered, values, side="left")
    equal = np.searchsorted(ordered, values, side="right") - below
    return (below + 0.5 * equal) / len(ordered)


def tail_probabilities(values: np.ndarray, reference: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Finite-sample tail probabilities of ``values`` against an out-of-sample reference.

    upper = (#reference >= x + 1)/(n + 1); lower = (#reference <= x + 1)/(n + 1);
    two-sided = min(1, 2*min(upper, lower)).
    """
    ordered = np.sort(np.asarray(reference, dtype=float))
    n = len(ordered)
    greater_equal = n - np.searchsorted(ordered, values, side="left")
    less_equal = np.searchsorted(ordered, values, side="right")
    upper = (greater_equal + 1.0) / (n + 1.0)
    lower = (less_equal + 1.0) / (n + 1.0)
    return upper, lower, np.minimum(1.0, 2.0 * np.minimum(upper, lower))


def record_evidence(target: pd.DataFrame, pool: pd.DataFrame, parameters: HistoricalParameters) -> pd.DataFrame:
    """Past-period comparison for every target record and target variable."""
    target = target.reset_index(drop=True)
    outputs = []
    design = str(target["design_period"].iloc[0]) if len(target) else ""
    window = parameters.window(design)
    lag = parameters.same_season_lag(design)
    for variable in RECORD_TARGETS:
        out = target[["source_observation_id", "release", "observation_type", "design_period", "period_index"]].copy()
        out["target_variable"] = variable
        out["observed_value"] = target[variable].to_numpy()
        out["assessability_status"] = "NOT_ASSESSABLE"
        out["assessability_reason"] = "TARGET_UNAVAILABLE_FOR_RELEASE_OBSERVATION" if target[variable].isna().all() else "INSUFFICIENT_HISTORICAL_REFERENCE"
        applicable = target[f"{variable}__applicable"].to_numpy(dtype=bool)
        finite = np.isfinite(target[variable].to_numpy(dtype=float))
        ready = target["ready"].to_numpy(dtype=bool)
        out.loc[~ready, "assessability_reason"] = "PREPARED_RECORD_NOT_READY"
        out.loc[ready & ~applicable, "assessability_reason"] = "TARGET_NOT_APPLICABLE_FOR_STATUS"
        out.loc[ready & applicable & ~finite & target[variable].notna().any(), "assessability_reason"] = "TARGET_MISSING_OR_NON_NUMERIC"
        earliest = pool["period_index"].dropna().min() if len(pool) else np.nan
        period_values = target["period_index"].to_numpy(dtype=float)
        first = period_values == earliest
        out.loc[ready & applicable & finite & first, "assessability_reason"] = np.where(
            (design == "post_2025") & (period_values[ready & applicable & finite & first] == 1),
            "DESIGN_BREAK_NO_COMPARABLE_EARLIER_PERIOD", "NO_EARLIER_PERIOD_SUPPLIED")
        eligible = pd.Series(ready & applicable & finite & ~first, index=target.index)
        reference_pool = pool[pool[f"{variable}__applicable"] & np.isfinite(pool[variable]) & pool["ready"]]
        levels = TARGET_LEVELS[variable]
        size = len(out)
        numeric = ("reference_size", "quantile_0_05", "quantile_0_25", "reference_median", "quantile_0_75", "quantile_0_95", "historical_percentile",
                   "upper_tail_p", "lower_tail_p", "two_sided_tail_p",
                   "same_season_reference_size", "same_season_median", "same_season_quantile_0_05", "same_season_quantile_0_95", "same_season_two_sided_tail_p")
        res = {name: np.full(size, np.nan) for name in numeric}
        text = {name: np.full(size, None, dtype=object) for name in ("distribution_position", "comparison_dimensions", "comparison_values", "reference_periods", "same_season_period")}
        level_used = np.full(size, -1)
        remaining = eligible.to_numpy().copy()
        values_all = target[variable].to_numpy(dtype=float)
        for level_number, dims in enumerate(levels):
            if not remaining.any():
                break
            ref = reference_pool[reference_pool[list(dims)].ne("").all(axis=1)]
            by_cell = {key: grp[variable].to_numpy(dtype=float) for key, grp in ref.groupby(list(dims) + ["period_index"], sort=False)}
            mask = remaining & target[list(dims)].ne("").all(axis=1).to_numpy()
            work = target.loc[mask, list(dims) + ["period_index"]]
            selected = np.flatnonzero(mask)  # once per level; per-group recomputation was quadratic
            for key, positions in work.groupby(list(dims) + ["period_index"], sort=False).indices.items():
                *cell, period = key
                rows = selected[positions]
                periods = [int(period) - k for k in range(1, window + 1) if int(period) - k >= 1]
                used = [p for p in periods if (*cell, p) in by_cell]
                if not used:
                    continue
                reference = np.concatenate([by_cell[(*cell, p)] for p in used])
                if len(reference) < parameters.minimum_reference_size:
                    continue
                values = values_all[rows]
                q = np.quantile(reference, [parameters.lower_tail_quantile, .25, .5, .75, parameters.upper_tail_quantile])
                res["reference_size"][rows] = len(reference)
                for name, value in zip(("quantile_0_05", "quantile_0_25", "reference_median", "quantile_0_75", "quantile_0_95"), q):
                    res[name][rows] = value
                res["historical_percentile"][rows] = _position(values, reference)
                upper, lower, two_sided = tail_probabilities(values, reference)
                res["upper_tail_p"][rows], res["lower_tail_p"][rows], res["two_sided_tail_p"][rows] = upper, lower, two_sided
                text["distribution_position"][rows] = np.select([values < q[0], values > q[4]], ["LOWER_TAIL", "UPPER_TAIL"], "CENTRAL_REFERENCE_RANGE")
                text["comparison_dimensions"][rows] = json.dumps(list(dims))
                text["comparison_values"][rows] = json.dumps(dict(zip(dims, map(str, cell))), sort_keys=True)
                text["reference_periods"][rows] = " to ".join(dict.fromkeys([period_label(design, min(used)), period_label(design, max(used))]))
                if lag is not None and (*cell, int(period) - lag) in by_cell:
                    season = by_cell[(*cell, int(period) - lag)]
                    if len(season) >= parameters.minimum_reference_size:
                        sq = np.quantile(season, [parameters.lower_tail_quantile, .5, parameters.upper_tail_quantile])
                        res["same_season_reference_size"][rows] = len(season)
                        res["same_season_quantile_0_05"][rows], res["same_season_median"][rows], res["same_season_quantile_0_95"][rows] = sq
                        res["same_season_two_sided_tail_p"][rows] = tail_probabilities(values, season)[2]
                        text["same_season_period"][rows] = period_label(design, int(period) - lag)
                level_used[rows] = level_number
                remaining[rows] = False
        assessed = level_used >= 0
        for name, array in res.items():
            out[name] = array
        # Kept for the A0 (pre-redesign) evaluation baseline; the decision path uses two_sided_tail_p.
        out["historical_score"] = np.abs(2 * res["historical_percentile"] - 1)
        out["tail_direction"] = pd.Series(np.where(res["upper_tail_p"] < res["lower_tail_p"], "HIGH", np.where(res["upper_tail_p"] > res["lower_tail_p"], "LOW", "CENTRE")),
                                          index=out.index, dtype="string").where(assessed)
        for name, array in text.items():
            out[name] = pd.Series(array, index=out.index, dtype="string")
        out["same_season_status"] = pd.Series(np.where(~assessed, pd.NA, np.where(np.isfinite(res["same_season_two_sided_tail_p"]), "ASSESSABLE",
                                                       "SAME_SEASON_REFERENCE_UNAVAILABLE" if lag is not None else "SAME_MONTH_PREVIOUS_YEAR_ACROSS_DESIGN_BREAK")),
                                              index=out.index, dtype="string")
        out["comparison_level"] = pd.array(np.where(assessed, level_used, -1), dtype="Int64")
        out.loc[~assessed, "comparison_level"] = pd.NA
        out.loc[assessed, "assessability_status"] = "ASSESSABLE"
        out.loc[assessed, "assessability_reason"] = pd.NA
        out["period_label"] = [period_label(design, int(p)) if pd.notna(p) else "" for p in out["period_index"]]
        out["tail_probability_convention"] = "FINITE_SAMPLE_OUT_OF_SAMPLE_REFERENCE"
        out["method_version"] = HISTORICAL_METHOD_VERSION
        outputs.append(out)
    return pd.concat(outputs, ignore_index=True)


INDICATORS = {
    "lfpr_cws_15plus": "Labour force participation rate (CWS, age 15+)",
    "wpr_cws_15plus": "Worker population ratio (CWS, age 15+)",
    "ur_cws_15plus": "Unemployment rate (CWS, age 15+)",
    "median_salaried_earnings": "Median monthly salaried earnings of salaried workers (₹)",
    "mean_day7_hours_workers": "Mean hours worked on day 7 by workers",
}


def _srs_se_prop(p_value: float, n_value: int) -> float:
    return float(np.sqrt(p_value * (1 - p_value) / n_value)) if n_value > 0 and np.isfinite(p_value) else np.nan


def _js_distance(left: np.ndarray, right: np.ndarray) -> float:
    left, right = left / left.sum(), right / right.sum()
    middle = (left + right) / 2
    with np.errstate(divide="ignore", invalid="ignore"):
        kl = lambda a: float(np.where(a > 0, a * np.log2(a / middle), 0.0).sum())  # noqa: E731
    return float(np.sqrt(max(0.0, (kl(left) + kl(right)) / 2)))


def load_known_events(path: Path = KNOWN_EVENTS_PATH) -> list[dict]:
    if not Path(path).is_file():
        return []
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    events = document.get("events") or []
    for event in events:
        for required in ("id", "design_period", "period_index", "indicators", "source", "approved_by"):
            if not event.get(required):
                raise HistoricalFailure(f"Known event {event.get('id')} lacks {required}; every event needs a source and an approver.")
    return events


def aggregate_indicators(pool: pd.DataFrame, parameters: HistoricalParameters, known_events: list[dict] | None = None) -> pd.DataFrame:
    """Weighted domain-period indicators with design-based SEs, and screening of change."""
    data = pool[pool["ready"] & pool["final_weight"].notna() & pool["period_index"].notna()].copy()
    data["period_index"] = data["period_index"].astype(int)
    status = data["cws_status"]
    data["_worker"] = status.isin(WORKER_CODES).astype(float)
    data["_unemployed"] = status.isin(UNEMPLOYED_CODES).astype(float)
    data["_lf"] = data["_worker"] + data["_unemployed"]
    data["_adult"] = data["age"].ge(MINIMUM_INDICATOR_AGE)
    # PSU = FSU within stratum (strata are nested within State x sector).
    data["_stratum"] = data["state"] + "|" + data["sector"] + "|" + data["stratum"]
    data["_psu"] = data["_stratum"] + "|" + data["fsu"]
    rows = []
    earnings_by_domain: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}
    levels = {"national": ["sector"], "state": ["state", "sector"], "district": ["state", "district", "sector"]}
    design = str(data["design_period"].iloc[0]) if len(data) else ""
    for level, keys in levels.items():
        for key, grp in data.groupby(keys + ["period_index"], sort=True):
            key = key if isinstance(key, tuple) else (key,)
            domain = dict(zip(keys, map(str, key[:-1])))
            period = int(key[-1])
            adult = grp[grp["_adult"]]
            w = adult["final_weight"].to_numpy(dtype=float)
            h, i = adult["_stratum"].to_numpy(), adult["_psu"].to_numpy()
            ones = np.ones(len(adult))
            lfpr = ratio_estimate(adult["_lf"].to_numpy(), ones, w, h, i)
            wpr = ratio_estimate(adult["_worker"].to_numpy(), ones, w, h, i)
            ur = ratio_estimate(adult["_unemployed"].to_numpy(), adult["_lf"].to_numpy(), w, h, i)
            earners = grp[grp["cws_earnings_salaried__applicable"] & grp["cws_earnings_salaried"].gt(0)]
            workers = grp[grp["day7_total_hours__applicable"] & grp["day7_total_hours"].notna()]
            n_adult, n_lf = len(adult), int(adult["_lf"].sum())
            earn = earners["cws_earnings_salaried"].to_numpy(dtype=float)
            earn_w = earners["final_weight"].to_numpy(dtype=float)
            if len(earners) >= parameters.minimum_domain_earners:
                median = median_estimate(earn, earn_w, earners["_stratum"].to_numpy(), earners["_psu"].to_numpy())
                earnings_by_domain[(level, *key)] = (earn, earn_w)
            else:
                median = {"estimate": np.nan, "design_se": np.nan, "psus": 0}
            hours = ratio_estimate(workers["day7_total_hours"].to_numpy(dtype=float), np.ones(len(workers)), workers["final_weight"].to_numpy(dtype=float),
                                   workers["_stratum"].to_numpy(), workers["_psu"].to_numpy()) if len(workers) else {"estimate": np.nan, "design_se": np.nan, "psus": 0}
            estimates = {"lfpr_cws_15plus": lfpr, "wpr_cws_15plus": wpr, "ur_cws_15plus": ur, "median_salaried_earnings": median, "mean_day7_hours_workers": hours}
            srs = {
                "lfpr_cws_15plus": _srs_se_prop(lfpr["estimate"], n_adult), "wpr_cws_15plus": _srs_se_prop(wpr["estimate"], n_adult),
                "ur_cws_15plus": _srs_se_prop(ur["estimate"], n_lf),
                "median_salaried_earnings": float(1.2533 * (np.subtract(*np.quantile(earn, [.75, .25])) / 1.349) / np.sqrt(len(earn))) if len(earn) >= parameters.minimum_domain_earners else np.nan,
                "mean_day7_hours_workers": float(np.std(workers["day7_total_hours"], ddof=1) / np.sqrt(len(workers))) if len(workers) > 1 else np.nan,
            }
            for indicator, estimate in estimates.items():
                rows.append({"level": level, **{k: domain.get(k, "") for k in ("state", "district", "sector")}, "design_period": design,
                             "period_index": period, "period_label": period_label(design, period), "indicator": indicator,
                             "indicator_label": INDICATORS[indicator], "value": estimate["estimate"], "design_standard_error": estimate["design_se"],
                             "psus": int(estimate["psus"]), "srs_standard_error": srs[indicator],
                             "persons_15plus": int(len(adult)), "salaried_earners": int(len(earners)), "workers": int(len(workers))})
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    table["design_effect"] = (table["design_standard_error"] / table["srs_standard_error"]) ** 2
    domain_cols = ["level", "state", "district", "sector", "indicator"]
    table = table.sort_values(domain_cols + ["period_index"], kind="mergesort").reset_index(drop=True)
    previous = table.groupby(domain_cols, sort=False).shift(1)
    consecutive = previous["period_index"].eq(table["period_index"] - 1)
    table["previous_value"] = previous["value"].where(consecutive)
    table["change"] = table["value"] - table["previous_value"]
    size = np.where(table["indicator"].eq("median_salaried_earnings"), table["salaried_earners"], table["persons_15plus"])
    prev_size = np.where(table["indicator"].eq("median_salaried_earnings"), previous["salaried_earners"], previous["persons_15plus"])
    minimum = np.where(table["indicator"].eq("median_salaried_earnings"), parameters.minimum_domain_earners, parameters.minimum_domain_persons)
    enough = (size >= minimum) & (pd.Series(prev_size).fillna(0).to_numpy() >= minimum)
    table["change_status"] = "NOT_ASSESSABLE"
    earliest = table["period_index"].min()
    table["change_reason"] = np.where(table["period_index"].eq(earliest),
                                      np.where((design == "post_2025") & table["period_index"].eq(1), "DESIGN_BREAK_NO_COMPARABLE_EARLIER_PERIOD", "NO_EARLIER_PERIOD_SUPPLIED"),
                                      np.where(~consecutive, "PREVIOUS_PERIOD_MISSING", np.where(~enough, "DOMAIN_SAMPLE_TOO_SMALL", np.where(table["change"].isna(), "INDICATOR_UNDEFINED", ""))))
    table["robust_z"] = np.nan
    assessable = table["change_reason"].eq("")
    for _, index in table[assessable].groupby(["level", "indicator", "period_index", "sector"]).groups.items():
        changes = table.loc[index, "change"]
        median = changes.median()
        mad = (changes - median).abs().median()
        if len(changes) >= 5 and mad > 0:
            table.loc[index, "robust_z"] = 0.6745 * (changes - median) / mad
            table.loc[index, "change_status"] = "ASSESSABLE"
        else:
            table.loc[index, "change_reason"] = "TOO_FEW_COMPARABLE_DOMAINS"
    table.loc[table["change_status"].eq("ASSESSABLE"), "change_reason"] = pd.NA
    table.loc[table["change_reason"].eq(""), "change_reason"] = pd.NA
    previous_design_se = table.groupby(domain_cols, sort=False)["design_standard_error"].shift(1).where(consecutive)
    previous_srs_se = table.groupby(domain_cols, sort=False)["srs_standard_error"].shift(1).where(consecutive)
    # Independent samples in the two periods (first-visit FSUs are not revisited).
    table["change_over_design_se"] = table["change"] / np.sqrt(table["design_standard_error"] ** 2 + previous_design_se ** 2)
    table["change_over_srs_se"] = table["change"] / np.sqrt(table["srs_standard_error"] ** 2 + previous_srs_se ** 2)
    # Same season one year earlier (pre-2025 only; shown, not screened).
    lag = parameters.same_season_lag(design)
    table["same_season_previous_value"] = np.nan
    if lag is not None:
        lookup = table.set_index(domain_cols + ["period_index"])["value"]
        keys = pd.MultiIndex.from_frame(table[domain_cols].assign(period_index=table["period_index"] - lag))
        table["same_season_previous_value"] = lookup.reindex(keys).to_numpy()
    table["same_season_change"] = table["value"] - table["same_season_previous_value"]
    # Distribution drift of salaried earnings (Jensen-Shannon distance over the
    # deciles of the two periods pooled), descriptive only.
    table["earnings_distribution_js_distance"] = np.nan
    median_rows = table.index[table["indicator"].eq("median_salaried_earnings") & consecutive]
    for index in median_rows:
        row = table.loc[index]
        current = earnings_by_domain.get((row["level"], *_domain_key(row), int(row["period_index"])))
        earlier = earnings_by_domain.get((row["level"], *_domain_key(row), int(row["period_index"]) - 1))
        if current is None or earlier is None:
            continue
        edges = np.unique(np.quantile(np.concatenate([current[0], earlier[0]]), np.linspace(0, 1, 11)))
        if len(edges) < 3:
            continue
        hist_now = np.histogram(current[0], bins=edges, weights=current[1])[0]
        hist_then = np.histogram(earlier[0], bins=edges, weights=earlier[1])[0]
        table.loc[index, "earnings_distribution_js_distance"] = _js_distance(hist_now.astype(float), hist_then.astype(float))
    table["known_event_id"] = pd.Series(pd.NA, index=table.index, dtype="string")
    for event in known_events or []:
        match = table["design_period"].eq(str(event["design_period"])) & table["period_index"].eq(int(event["period_index"])) & table["indicator"].isin(event["indicators"])
        if event.get("state"):
            match &= table["state"].eq(str(event["state"]))
        table.loc[match, "known_event_id"] = str(event["id"])
    screened = table["robust_z"].abs().ge(parameters.notable_robust_z) & table["change_over_design_se"].abs().ge(parameters.notable_change_over_se)
    table["expected_change_known_event"] = screened & table["known_event_id"].notna()
    table["notable_change"] = screened & table["known_event_id"].isna()
    table["se_method"] = "taylor_linearisation_fsu_psu_within_strata_with_replacement; median: woodruff"
    table["method_version"] = HISTORICAL_METHOD_VERSION
    return table


def _domain_key(row: pd.Series) -> tuple[str, ...]:
    if row["level"] == "national":
        return (str(row["sector"]),)
    if row["level"] == "state":
        return (str(row["state"]), str(row["sector"]))
    return (str(row["state"]), str(row["district"]), str(row["sector"]))


def reference_snapshot(pool: pd.DataFrame) -> pd.DataFrame:
    """The frozen reference used by this run: every applicable value per variable, cell and period."""
    parts = []
    for variable in RECORD_TARGETS:
        usable = pool[pool[f"{variable}__applicable"] & np.isfinite(pool[variable]) & pool["ready"]]
        part = usable[["release", "design_period", "period_index", *CELL_CONCEPTS]].copy()
        part["target_variable"] = variable
        part["value"] = usable[variable].to_numpy(dtype=float)
        parts.append(part)
    snapshot = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    return snapshot.sort_values(["target_variable", "period_index", *CELL_CONCEPTS, "value"], kind="mergesort", ignore_index=True)


def _frame_hash(frame: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(frame, index=False).to_numpy().tobytes()).hexdigest()


class HistoricalEngine:
    def __init__(self, config: RunConfig) -> None:
        self.config = replace(config, target_prepared_persons=Path(config.target_prepared_persons),
                              reference_prepared_persons=tuple(Path(p) for p in config.reference_prepared_persons), output_root=Path(config.output_root))

    def run(self) -> Path:
        started = time.perf_counter()
        target, target_meta = load_release(self.config.target_prepared_persons)
        design = str(target_meta["design_period"])
        frames, reference_meta = [], []
        for path in self.config.reference_prepared_persons:
            frame, meta = load_release(path)
            if str(meta["design_period"]) != design:
                raise HistoricalFailure(f"Reference {path} is design period {meta['design_period']}; target is {design}. The January-2025 break is never crossed.")
            if str(meta["observation"]) != str(target_meta["observation"]):
                raise HistoricalFailure("Historical references must be the same observation route (first visit vs revisit).")
            frames.append(frame); reference_meta.append(meta)
        if not any(str(m["run_id"]) == str(target_meta["run_id"]) for m in reference_meta):
            frames.append(target); reference_meta.append(target_meta)
        pool = deduplicate_periods(frames)
        evidence = record_evidence(target, pool, self.config.parameters)
        known_events = load_known_events()
        aggregates = aggregate_indicators(pool, self.config.parameters, known_events)
        snapshot = reference_snapshot(pool)
        run_id = self.config.run_id or str(uuid.uuid4())
        destination = self.config.output_root / f"{target_meta['release']}_{target_meta['observation']}_{run_id}"
        destination.mkdir(parents=True, exist_ok=False)
        evidence.to_parquet(destination / "historical_record_evidence.parquet", index=False)
        aggregates.to_parquet(destination / "aggregate_indicators.parquet", index=False)
        snapshot.to_parquet(destination / "reference_snapshot.parquet", index=False)
        periods = sorted(int(p) for p in pool["period_index"].dropna().unique())
        snapshot_record = {"file": "reference_snapshot.parquet", "content_sha256": _frame_hash(snapshot), "rows": int(len(snapshot)),
                           "periods": [period_label(design, p) for p in periods],
                           "source_preprocessing_runs": [{"release": m["release"], "run_id": m["run_id"]} for m in reference_meta]}
        report = {
            "records": int(evidence["source_observation_id"].nunique()),
            "record_evidence": {t: {str(k): int(v) for k, v in evidence[evidence.target_variable.eq(t)].assessability_reason.fillna("ASSESSABLE").value_counts().items()} for t in RECORD_TARGETS},
            "same_season": {t: {str(k): int(v) for k, v in evidence[evidence.target_variable.eq(t)].same_season_status.fillna("NOT_ASSESSED").value_counts().items()} for t in RECORD_TARGETS},
            "periods_in_pool": [period_label(design, p) for p in periods],
            "aggregate_rows": int(len(aggregates)),
            "aggregate_notable_changes": int(aggregates["notable_change"].sum()) if len(aggregates) else 0,
            "aggregate_expected_changes_known_events": int(aggregates["expected_change_known_event"].sum()) if len(aggregates) else 0,
            "aggregate_change_status": {str(k): int(v) for k, v in aggregates["change_reason"].fillna("ASSESSABLE").value_counts().items()} if len(aggregates) else {},
            "median_design_effect": {str(k): float(v) for k, v in aggregates.groupby("indicator")["design_effect"].median().items()} if len(aggregates) else {},
            "known_events_loaded": len(known_events),
            "reference_snapshot": snapshot_record,
            "runtime_seconds": round(time.perf_counter() - started, 1),
            "limitations": [
                "Comparison of each value with past-period peers; nominal rupees are not deflated (no price index has been approved by HSD).",
                "Aggregate indicators use first-visit records only and are screening values, not official PLFS estimates.",
                "Design-based standard errors use Taylor linearisation with FSU as PSU within strata (with-replacement approximation; median by Woodruff's method).",
                "Post-2025 history is limited to earlier 2025 months; January 2025 has no comparable earlier period and same-month-previous-year needs 2026 data.",
            ],
        }
        metadata = {"run_id": run_id, "release": target_meta["release"], "observation": target_meta["observation"], "design_period": design,
                    "input_preprocessing_run_id": target_meta["run_id"], "historical_method_version": HISTORICAL_METHOD_VERSION,
                    "reference_preprocessing_runs": [{"release": m["release"], "run_id": m["run_id"]} for m in reference_meta],
                    "reference_snapshot": snapshot_record,
                    "parameters": self.config.parameters.__dict__,
                    "output_files": ["historical_record_evidence.parquet", "aggregate_indicators.parquet", "reference_snapshot.parquet",
                                     "historical_report.json", "run_metadata.json"]}
        (destination / "historical_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (destination / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return destination
