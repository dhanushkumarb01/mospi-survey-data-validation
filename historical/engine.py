"""Historical evidence across survey periods, inside one design period.

Record level
    Each applicable earnings/hours value of the *target* release is compared
    with the same comparison cell (State/UT x sector x activity status [x
    occupation group or industry division]) reported in strictly *preceding*
    periods of the same design period: up to four quarters before 2025, up to
    three months in 2025.  No record is linked across releases and nothing
    crosses the January-2025 redesign.

    The pre-2025 releases overlap: Calendar-2024 Q3/Q4 are the same records as
    2023-24 Q3/Q4.  Periods are therefore placed on one de-duplicated quarter
    axis (survey_rules.period_index) and each period is taken from one release
    only, so no record is ever compared with itself.

Aggregate level
    Weighted current-weekly-status indicators (LFPR, WPR, UR for ages 15+,
    weighted median salaried earnings among applicable earners, weighted mean
    day-7 hours among workers) are produced by sector for the nation, each
    State/UT and each district, per period, with the documented quarterly
    final weight.  A period-on-period change is screened against the changes
    of the *other domains in the same period* (robust z).  This is descriptive
    screening of first-visit records: it is not an official estimate (urban
    quarterly estimates also use revisits) and has no design-based standard
    error.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import pandas as pd

from peer_groups.config import SOURCE_PROFILES
from preprocessing.config import CONTRACTS
from survey_rules import APPLICABLE, WEIGHT_FIELDS, applicability_series, final_quarterly_weight, period_index, period_label

from .config import (EARNINGS_LEVELS, HISTORICAL_METHOD_VERSION, HOURS_LEVELS, MINIMUM_INDICATOR_AGE, RECORD_TARGETS,
                     UNEMPLOYED_CODES, WORKER_CODES, HistoricalParameters)

READY = "ready_for_downstream_preparation_only"


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
    """Read the documented fields of one prepared-person delivery into a common schema."""
    meta = _metadata(path)
    key = (str(meta["release"]), str(meta["observation"]))
    profile, weights = SOURCE_PROFILES.get(key), WEIGHT_FIELDS.get(key)
    contract = next((c for c in CONTRACTS.values() if (c.release, c.observation) == key), None)
    if profile is None or weights is None or contract is None:
        raise HistoricalFailure(f"No documented field mapping for {key}")
    columns = {
        "MoSPI_record_key": "record_key", "MoSPI_source_row": "source_row", "MoSPI_release": "release", "MoSPI_observation": "observation_type",
        "MoSPI_design_period": "design_period", "MoSPI_state": "state", "MoSPI_sector": "sector", "MoSPI_prepared_status": "prepared_status",
        profile.person_serial_column: "serial", profile.context_columns["cws_status"]: "cws_status", contract.person_fields["age"]: "age",
        contract.person_fields["district"]: "district",
    }
    for optional, name in (("MoSPI_quarter", "quarter"), ("MoSPI_month", "month")):
        columns[optional] = name
    for concept in ("occupation_major_group", "industry_division"):
        if concept in profile.context_columns:
            columns[profile.context_columns[concept]] = f"raw_{concept}"
    for target, column in profile.target_columns.items():
        columns[column] = target
    for concept, column in weights.items():
        if column:
            columns[column] = f"w_{concept}"
    import pyarrow.parquet as pq
    available = set(pq.ParquetFile(path).schema_arrow.names)
    frame = pd.read_parquet(path, columns=[c for c in columns if c in available]).rename(columns=columns)
    for name in set(columns.values()) - set(frame.columns):
        frame[name] = ""
    for name in ("record_key", "release", "observation_type", "design_period", "state", "sector", "serial", "cws_status", "district", "quarter", "month", "prepared_status"):
        frame[name] = _clean(frame[name])
    fallback = _clean(frame["source_row"].astype("string"))
    frame["source_observation_id"] = frame["record_key"].str.cat(frame["serial"].mask(frame["serial"].eq(""), fallback), sep="|person=")
    occupation = _clean(frame["raw_occupation_major_group"]) if "raw_occupation_major_group" in frame else pd.Series("", index=frame.index)
    industry = _clean(frame["raw_industry_division"]) if "raw_industry_division" in frame else pd.Series("", index=frame.index)
    frame["occupation_major_group"] = occupation.where(occupation.str.fullmatch(r"\d{3}"), "").str.slice(0, 1)
    frame["industry_division"] = industry.where(industry.str.fullmatch(r"\d{4,5}"), "").str.slice(0, 2)
    frame["period_index"] = [period_index(r, q, m) for r, q, m in zip(frame["release"], frame["quarter"], frame["month"])]
    frame["age"] = pd.to_numeric(frame["age"], errors="coerce")
    for target in RECORD_TARGETS:
        frame[target] = pd.to_numeric(frame[target], errors="coerce") if target in frame else np.nan
        frame[f"{target}__applicable"] = applicability_series(target, frame["cws_status"]).eq(APPLICABLE).to_numpy()
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


def record_evidence(target: pd.DataFrame, pool: pd.DataFrame, parameters: HistoricalParameters) -> pd.DataFrame:
    """Past-period comparison for every target record and target variable."""
    target = target.reset_index(drop=True)
    outputs = []
    design = str(target["design_period"].iloc[0]) if len(target) else ""
    window = parameters.window(design)
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
        out.loc[ready & ~applicable, "assessability_reason"] = "TARGET_NOT_APPLICABLE_FOR_CWS_STATUS"
        out.loc[ready & applicable & ~finite & target[variable].notna().any(), "assessability_reason"] = "TARGET_MISSING_OR_NON_NUMERIC"
        earliest = pool["period_index"].dropna().min() if len(pool) else np.nan
        period_values = target["period_index"].to_numpy(dtype=float)
        first = period_values == earliest
        out.loc[ready & applicable & finite & first, "assessability_reason"] = np.where(
            (design == "post_2025") & (period_values[ready & applicable & finite & first] == 1),
            "DESIGN_BREAK_NO_COMPARABLE_EARLIER_PERIOD", "NO_EARLIER_PERIOD_SUPPLIED")
        eligible = pd.Series(ready & applicable & finite & ~first, index=target.index)
        reference_pool = pool[pool[f"{variable}__applicable"] & np.isfinite(pool[variable]) & pool["ready"]]
        levels = EARNINGS_LEVELS if variable.startswith("cws_earnings") else HOURS_LEVELS
        size = len(out)
        res = {name: np.full(size, np.nan) for name in ("reference_size", "quantile_0_05", "quantile_0_25", "reference_median", "quantile_0_75", "quantile_0_95", "historical_percentile")}
        text = {name: np.full(size, None, dtype=object) for name in ("distribution_position", "comparison_dimensions", "comparison_values", "reference_periods")}
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
                text["distribution_position"][rows] = np.select([values < q[0], values > q[4]], ["LOWER_TAIL", "UPPER_TAIL"], "CENTRAL_REFERENCE_RANGE")
                text["comparison_dimensions"][rows] = json.dumps(list(dims))
                text["comparison_values"][rows] = json.dumps(dict(zip(dims, map(str, cell))), sort_keys=True)
                text["reference_periods"][rows] = " to ".join(dict.fromkeys([period_label(design, min(used)), period_label(design, max(used))]))
                level_used[rows] = level_number
                remaining[rows] = False
        assessed = level_used >= 0
        for name, array in res.items():
            out[name] = array
        out["historical_score"] = np.abs(2 * res["historical_percentile"] - 1)
        for name, array in text.items():
            out[name] = pd.Series(array, index=out.index, dtype="string")
        out["comparison_level"] = pd.array(np.where(assessed, level_used, -1), dtype="Int64")
        out.loc[~assessed, "comparison_level"] = pd.NA
        out.loc[assessed, "assessability_status"] = "ASSESSABLE"
        out.loc[assessed, "assessability_reason"] = pd.NA
        out["period_label"] = [period_label(design, int(p)) if pd.notna(p) else "" for p in out["period_index"]]
        out["method_version"] = HISTORICAL_METHOD_VERSION
        outputs.append(out)
    return pd.concat(outputs, ignore_index=True)


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    if len(values) == 0:
        return np.nan
    order = np.argsort(values, kind="mergesort")
    v, w = values[order], weights[order]
    cumulative = np.cumsum(w)
    return float(v[np.searchsorted(cumulative, 0.5 * cumulative[-1])])


INDICATORS = {
    "lfpr_cws_15plus": "Labour force participation rate (CWS, age 15+)",
    "wpr_cws_15plus": "Worker population ratio (CWS, age 15+)",
    "ur_cws_15plus": "Unemployment rate (CWS, age 15+)",
    "median_salaried_earnings": "Median monthly salaried earnings of salaried workers (₹)",
    "mean_day7_hours_workers": "Mean hours worked on day 7 by workers",
}


def aggregate_indicators(pool: pd.DataFrame, parameters: HistoricalParameters) -> pd.DataFrame:
    """Weighted domain-period indicators and robust screening of period-on-period change."""
    data = pool[pool["ready"] & pool["final_weight"].notna() & pool["period_index"].notna()].copy()
    data["period_index"] = data["period_index"].astype(int)
    status = data["cws_status"]
    data["_worker"] = status.isin(WORKER_CODES)
    data["_unemployed"] = status.isin(UNEMPLOYED_CODES)
    data["_adult"] = data["age"].ge(MINIMUM_INDICATOR_AGE)
    rows = []
    levels = {"national": ["sector"], "state": ["state", "sector"], "district": ["state", "district", "sector"]}
    design = str(data["design_period"].iloc[0]) if len(data) else ""
    for level, keys in levels.items():
        for key, grp in data.groupby(keys + ["period_index"], sort=True):
            key = key if isinstance(key, tuple) else (key,)
            domain = dict(zip(keys, map(str, key[:-1])))
            period = int(key[-1])
            adult = grp[grp["_adult"]]
            w = adult["final_weight"].to_numpy(dtype=float)
            population = w.sum()
            lf = w[(adult["_worker"] | adult["_unemployed"]).to_numpy()].sum()
            workers_w = w[adult["_worker"].to_numpy()].sum()
            earners = grp[grp["cws_earnings_salaried__applicable"] & grp["cws_earnings_salaried"].gt(0)]
            workers = grp[grp["day7_total_hours__applicable"] & grp["day7_total_hours"].notna()]
            n_adult, n_lf = len(adult), int((adult["_worker"] | adult["_unemployed"]).sum())
            earn = earners["cws_earnings_salaried"].to_numpy(dtype=float)
            hours = workers["day7_total_hours"].to_numpy(dtype=float)

            def _se_prop(p_value: float, n_value: int) -> float:
                return float(np.sqrt(p_value * (1 - p_value) / n_value)) if n_value > 0 and np.isfinite(p_value) else np.nan
            values = {
                "lfpr_cws_15plus": lf / population if population > 0 else np.nan,
                "wpr_cws_15plus": workers_w / population if population > 0 else np.nan,
                "ur_cws_15plus": (lf - workers_w) / lf if lf > 0 else np.nan,
                "median_salaried_earnings": _weighted_median(earners["cws_earnings_salaried"].to_numpy(dtype=float), earners["final_weight"].to_numpy(dtype=float)) if len(earners) >= parameters.minimum_domain_earners else np.nan,
                "mean_day7_hours_workers": float(np.average(workers["day7_total_hours"], weights=workers["final_weight"])) if len(workers) and workers["final_weight"].sum() > 0 else np.nan,
            }
            # Simple-random-sampling standard errors (design effect ignored, so they
            # understate the true sampling error); used only to stop small domains'
            # noise from being screened as unusual change.
            se = {
                "lfpr_cws_15plus": _se_prop(values["lfpr_cws_15plus"], n_adult),
                "wpr_cws_15plus": _se_prop(values["wpr_cws_15plus"], n_adult),
                "ur_cws_15plus": _se_prop(values["ur_cws_15plus"], n_lf),
                "median_salaried_earnings": float(1.2533 * (np.subtract(*np.quantile(earn, [.75, .25])) / 1.349) / np.sqrt(len(earn))) if len(earn) >= parameters.minimum_domain_earners else np.nan,
                "mean_day7_hours_workers": float(np.std(hours, ddof=1) / np.sqrt(len(hours))) if len(hours) > 1 else np.nan,
            }
            for indicator, value in values.items():
                rows.append({"level": level, "srs_standard_error": se[indicator], **{k: domain.get(k, "") for k in ("state", "district", "sector")}, "design_period": design,
                             "period_index": period, "period_label": period_label(design, period), "indicator": indicator,
                             "indicator_label": INDICATORS[indicator], "value": value,
                             "persons_15plus": int(len(adult)), "salaried_earners": int(len(earners)), "workers": int(len(workers))})
    table = pd.DataFrame(rows)
    if table.empty:
        return table
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
    previous_se = table.groupby(domain_cols, sort=False)["srs_standard_error"].shift(1).where(consecutive)
    table["change_over_srs_se"] = table["change"] / np.sqrt(table["srs_standard_error"] ** 2 + previous_se ** 2)
    table["notable_change"] = table["robust_z"].abs().ge(parameters.notable_robust_z) & table["change_over_srs_se"].abs().ge(parameters.notable_change_over_se)
    table["method_version"] = HISTORICAL_METHOD_VERSION
    return table


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
        aggregates = aggregate_indicators(pool, self.config.parameters)
        run_id = self.config.run_id or str(uuid.uuid4())
        destination = self.config.output_root / f"{target_meta['release']}_{target_meta['observation']}_{run_id}"
        destination.mkdir(parents=True, exist_ok=False)
        evidence.to_parquet(destination / "historical_record_evidence.parquet", index=False)
        aggregates.to_parquet(destination / "aggregate_indicators.parquet", index=False)
        periods = sorted(int(p) for p in pool["period_index"].dropna().unique())
        report = {
            "records": int(evidence["source_observation_id"].nunique()),
            "record_evidence": {t: {str(k): int(v) for k, v in evidence[evidence.target_variable.eq(t)].assessability_reason.fillna("ASSESSABLE").value_counts().items()} for t in RECORD_TARGETS},
            "periods_in_pool": [period_label(design, p) for p in periods],
            "aggregate_rows": int(len(aggregates)),
            "aggregate_notable_changes": int(aggregates["notable_change"].sum()) if len(aggregates) else 0,
            "aggregate_change_status": {str(k): int(v) for k, v in aggregates["change_reason"].fillna("ASSESSABLE").value_counts().items()} if len(aggregates) else {},
            "runtime_seconds": round(time.perf_counter() - started, 1),
            "limitations": [
                "Unweighted comparison of each value with past-period peers; nominal rupees are not deflated (no price index is supplied).",
                "Aggregate indicators use first-visit records only and are screening values, not official PLFS estimates; no design-based standard errors are computed.",
                "Post-2025 history is limited to earlier 2025 months; January 2025 has no comparable earlier period.",
            ],
        }
        metadata = {"run_id": run_id, "release": target_meta["release"], "observation": target_meta["observation"], "design_period": design,
                    "input_preprocessing_run_id": target_meta["run_id"], "historical_method_version": HISTORICAL_METHOD_VERSION,
                    "reference_preprocessing_runs": [{"release": m["release"], "run_id": m["run_id"]} for m in reference_meta],
                    "parameters": self.config.parameters.__dict__,
                    "output_files": ["historical_record_evidence.parquet", "aggregate_indicators.parquet", "historical_report.json", "run_metadata.json"]}
        (destination / "historical_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (destination / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return destination
