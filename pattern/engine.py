"""Release-aware aggregate Pattern evidence engine.

The engine intentionally constructs a compact, dedicated FSU reference: other
valid records in the same release/observation/design-period/visit/month and
state/sector/stratum cell.  Existing peer groups cannot be reused safely here:
they are person-level, target-specific behavioural references and deliberately
exclude FSU, whereas Pattern needs leave-FSU-out group distributions.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
import gc
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from peer_groups.config import SOURCE_PROFILES
from survey_rules import APPLICABLE, applicability_series
from preprocessing.config import CONTRACTS

from .config import PATTERN_METHOD_VERSION, PATTERN_SPECIFICATION_VERSION, READY_STATUS, PatternParameters
from .reporting import utc_now, write_json, write_markdown_report


class PatternFailure(RuntimeError):
    """Raised where release/provenance contracts do not establish safe input."""


@dataclass(frozen=True)
class RunConfig:
    prepared_person_path: Path
    output_root: Path
    run_id: str | None = None
    parameters: PatternParameters = PatternParameters()
    revisit_prepared_person_path: Path | None = None
    revisit_statistical_run_path: Path | None = None


COMMON_COLUMNS = (
    "evidence_id", "pattern_component", "group_level", "group_id", "fsu", "state", "sector", "stratum",
    "release", "observation_type", "design_period", "visit", "month", "period", "variable",
    "reference_definition", "n", "reference_n", "raw_metric", "evidence_score", "evidence_rank",
    "assessability_status", "assessability_reason", "evidence_statement", "method_id", "method_version",
    "preprocessing_run_id", "pattern_run_id", "details_json", "p_value", "q_value", "notable",
    "p_value_unadjusted", "dispersion_factor",
)
P_FLOOR = 1e-300


def _clean(values: pd.Series) -> pd.Series:
    return values.astype("string").fillna("").str.strip()


def _numeric(values: pd.Series) -> pd.Series:
    result = pd.to_numeric(values, errors="coerce")
    return result.where(np.isfinite(result))


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _eid(component: str, identity: dict[str, object]) -> str:
    return "pat_" + hashlib.sha256((component + "|" + _canonical(identity)).encode()).hexdigest()[:24]


def _js_distance(left: np.ndarray, right: np.ndarray) -> float:
    """Square-root Jensen-Shannon divergence, stable when a category is absent."""
    midpoint = (left + right) / 2
    with np.errstate(divide="ignore", invalid="ignore"):
        kl_left = np.where(left > 0, left * np.log2(left / midpoint), 0.0).sum()
        kl_right = np.where(right > 0, right * np.log2(right / midpoint), 0.0).sum()
    return float(math.sqrt(max(0.0, (kl_left + kl_right) / 2)))


def g_test_p_value(observed: np.ndarray, reference_counts: np.ndarray) -> tuple[float, float]:
    """Goodness-of-fit G-test of FSU counts against leave-FSU-out proportions.

    Reference proportions get a +0.5 per-category continuity so a category
    absent from the reference does not give an infinite statistic.  Williams'
    correction improves the chi-square approximation for small FSUs; with the
    FSU minimum of 10 the p-value is still approximate (documented).
    Returns (p_value, G).
    """
    observed = np.asarray(observed, dtype=float); reference_counts = np.asarray(reference_counts, dtype=float)
    k = len(observed); n = observed.sum()
    if k < 2 or n <= 0:
        return 1.0, 0.0
    q = (reference_counts + 0.5) / (reference_counts.sum() + 0.5 * k)
    expected = n * q
    with np.errstate(divide="ignore", invalid="ignore"):
        g = 2.0 * np.where(observed > 0, observed * np.log(observed / expected), 0.0).sum()
    williams = 1.0 + (k * k - 1.0) / (6.0 * n * (k - 1.0))
    return float(stats.chi2.sf(max(g, 0.0) / williams, k - 1)), float(g)


ONE_SIDED = {"reduced_variance_concentration", "digit_heaping"}
CHI2_1_MEDIAN = 0.454936423119572


def overdispersion_adjust(p_values: pd.Series, *, one_sided: bool) -> tuple[pd.Series, float]:
    """Quasi-likelihood correction for clustering of answers within FSUs.

    The G-test, Mann-Whitney and binomial tests treat people as independent,
    but survey answers are clustered: people in one FSU resemble each other,
    so genuine between-FSU variation exceeds what those tests expect.  The
    first controlled evaluation showed the consequence: 15.8% (2024) and 54%
    (2025) of clean FSUs were "notable".  Each p-value is converted to its
    1-df chi-square equivalent; the dispersion factor phi is the median of
    those statistics over all FSUs divided by the null median (0.455), floored
    at 1; statistics are divided by phi before p-values are recomputed.  This
    assumes most FSUs are ordinary (standard quasi-likelihood practice).
    """
    from scipy import stats as _stats
    p = p_values.clip(lower=P_FLOOR, upper=1.0)
    if one_sided:
        z = pd.Series(_stats.norm.isf(p), index=p.index)
        # Under no difference z is N(0,1), so z^2 among z > 0 is still chi-square(1).
        upper = z[z > 0]
        phi = max(1.0, float(np.median(np.square(upper))) / CHI2_1_MEDIAN) if len(upper) >= 10 else 1.0
        return pd.Series(_stats.norm.sf(z / np.sqrt(phi)), index=p.index), phi
    chi = pd.Series(_stats.chi2.isf(p, 1), index=p.index)
    phi = max(1.0, float(np.median(chi)) / CHI2_1_MEDIAN) if len(chi) >= 10 else 1.0
    return pd.Series(_stats.chi2.sf(chi / phi, 1), index=p.index), phi


def benjamini_hochberg(p_values: pd.Series) -> pd.Series:
    """BH false-discovery-rate adjusted q-values (NaN preserved)."""
    p = pd.to_numeric(p_values, errors="coerce")
    valid = p.dropna()
    q = pd.Series(np.nan, index=p.index)
    if valid.empty:
        return q
    order = valid.sort_values(kind="mergesort")
    m = len(order)
    adjusted = (order * m / np.arange(1, m + 1)).iloc[::-1].cummin().iloc[::-1].clip(upper=1.0)
    q.loc[adjusted.index] = adjusted.to_numpy()
    return q


class PatternEngine:
    def __init__(self, config: RunConfig) -> None:
        self.config = replace(
            config, prepared_person_path=Path(config.prepared_person_path), output_root=Path(config.output_root),
            revisit_prepared_person_path=Path(config.revisit_prepared_person_path) if config.revisit_prepared_person_path else None,
            revisit_statistical_run_path=Path(config.revisit_statistical_run_path) if config.revisit_statistical_run_path else None,
        )
        if bool(self.config.revisit_prepared_person_path) != bool(self.config.revisit_statistical_run_path):
            raise ValueError("Both revisit_prepared_person_path and revisit_statistical_run_path are required together")

    @staticmethod
    def _metadata(path: Path) -> dict[str, object]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise PatternFailure(f"Prepared input must have adjacent run_metadata.json: {path}") from error
        except json.JSONDecodeError as error:
            raise PatternFailure(f"Invalid metadata JSON: {path}") from error

    def _validate(self) -> tuple[dict[str, object], object, object]:
        if not self.config.prepared_person_path.is_file():
            raise PatternFailure(f"Prepared person input does not exist: {self.config.prepared_person_path}")
        metadata = self._metadata(self.config.prepared_person_path.parent / "run_metadata.json")
        for key in ("run_id", "release", "observation", "design_period"):
            if not str(metadata.get(key, "")):
                raise PatternFailure(f"Preprocessing metadata lacks {key}")
        profile_key = (str(metadata["release"]), str(metadata["observation"]))
        if profile_key not in SOURCE_PROFILES:
            raise PatternFailure(f"No Pattern source mapping for release/observation {profile_key}")
        contract = next((item for item in CONTRACTS.values() if item.release == profile_key[0] and item.observation == profile_key[1]), None)
        if contract is None:
            raise PatternFailure(f"No preparation contract for {profile_key}")
        return metadata, SOURCE_PROFILES[profile_key], contract

    @staticmethod
    def _target_columns(profile, contract) -> dict[str, str | None]:
        fields = dict(profile.target_columns)
        fields["age"] = contract.person_fields["age"]
        fields["cws_status"] = profile.context_columns["cws_status"]
        fields["principal_occupation_major_group"] = profile.context_columns.get("occupation_major_group")
        fields["principal_industry_division"] = profile.context_columns.get("industry_division")
        return fields

    def _base(self, metadata: dict[str, object], profile, contract, path: Path | None = None) -> pd.DataFrame:
        path = path or self.config.prepared_person_path
        targets = self._target_columns(profile, contract)
        required = {
            "MoSPI_record_key", "MoSPI_source_row", "MoSPI_release", "MoSPI_observation", "MoSPI_design_period",
            "MoSPI_visit", "MoSPI_state", "MoSPI_sector", "MoSPI_stratum", "MoSPI_fsu", "MoSPI_prepared_status",
            "MoSPI_quarter", profile.person_serial_column,
            *(column for column in targets.values() if column),
        }
        if str(metadata["release"]) == "2025":
            required.add("MoSPI_month")
        try:
            source = pd.read_parquet(path, columns=sorted(required))
        except Exception as error:
            raise PatternFailure(f"Could not read Pattern input contract: {error}") from error
        for field, expected in (("MoSPI_release", metadata["release"]), ("MoSPI_observation", metadata["observation"]), ("MoSPI_design_period", metadata["design_period"])):
            values = set(_clean(source[field]).unique())
            if values != {str(expected)}:
                raise PatternFailure(f"Prepared input has mixed or unexpected {field}: {sorted(values)}")
        serial = _clean(source[profile.person_serial_column])
        output = pd.DataFrame({
            "source_observation_id": _clean(source["MoSPI_record_key"]).str.cat(serial.mask(serial.eq(""), _clean(source["MoSPI_source_row"])), sep="|person="),
            "release": _clean(source["MoSPI_release"]), "observation_type": _clean(source["MoSPI_observation"]),
            "design_period": _clean(source["MoSPI_design_period"]), "visit": _clean(source["MoSPI_visit"]),
            "month": _clean(source["MoSPI_month"]) if "MoSPI_month" in source else "",
            "quarter": _clean(source["MoSPI_quarter"]), "state": _clean(source["MoSPI_state"]),
            "sector": _clean(source["MoSPI_sector"]), "stratum": _clean(source["MoSPI_stratum"]),
            "fsu": _clean(source["MoSPI_fsu"]), "ready": _clean(source["MoSPI_prepared_status"]).eq(READY_STATUS),
        })
        if output["source_observation_id"].duplicated().any():
            raise PatternFailure("Prepared input cannot provide unique source observation IDs")
        for target, column in targets.items():
            if not column:
                output[target] = pd.NA
                continue
            raw = _clean(source[column])
            if target == "principal_occupation_major_group":
                output[target] = raw.where(raw.str.fullmatch(r"\d{3}"), "").str.slice(0, 1)
            elif target == "principal_industry_division":
                output[target] = raw.where(raw.str.fullmatch(r"\d{4,5}"), "").str.slice(0, 2)
            elif target in self.config.parameters.numerical_targets:
                output[target] = _numeric(raw)
            else:
                output[target] = raw
        return output

    @staticmethod
    def _boundary_columns() -> list[str]:
        return ["release", "observation_type", "design_period", "visit", "month", "state", "sector", "stratum"]

    def _group_frame(self, base: pd.DataFrame) -> pd.DataFrame:
        valid = base["ready"] & base[["state", "sector", "stratum", "fsu"]].ne("").all(axis=1)
        return base.loc[valid].copy()

    def _row(self, *, component: str, base: dict[str, object], variable: str, n: int = 0, reference_n: int = 0,
             raw_metric: float | None = None, score: float | None = None, rank: float | None = None,
             status: str = "NOT_ASSESSABLE", reason: str | None = None, statement: str = "", details: object | None = None,
             period: str = "", group_level: str = "FSU", p_value: float | None = None) -> dict[str, object]:
        identity = {"group": base["group_id"], "variable": variable, "period": period, "component": component}
        if p_value is not None and score is None:
            score = float(-math.log10(max(p_value, P_FLOOR)))
        return {
            "evidence_id": _eid(component, identity), "pattern_component": component, "group_level": group_level,
            "group_id": base["group_id"], "fsu": base.get("fsu", pd.NA), "state": base.get("state", pd.NA),
            "sector": base.get("sector", pd.NA), "stratum": base.get("stratum", pd.NA),
            "release": base["release"], "observation_type": base["observation_type"], "design_period": base["design_period"],
            "visit": base["visit"], "month": base["month"], "period": period, "variable": variable,
            "reference_definition": "leave-FSU-out; release/observation/design/visit/month/state/sector/stratum",
            "n": int(n), "reference_n": int(reference_n), "raw_metric": raw_metric, "evidence_score": score,
            "evidence_rank": rank, "assessability_status": status, "assessability_reason": reason,
            "evidence_statement": statement, "method_id": component, "method_version": PATTERN_METHOD_VERSION,
            "preprocessing_run_id": self.preprocessing_run_id, "pattern_run_id": self.pattern_run_id,
            "details_json": _canonical(details or {}), "p_value": p_value, "q_value": None, "notable": False,
        }

    @staticmethod
    def _fsu_identity(frame: pd.DataFrame) -> pd.DataFrame:
        keys = PatternEngine._boundary_columns() + ["fsu"]
        output = frame[keys].drop_duplicates().copy()
        output["group_id"] = output.apply(lambda row: "fsu_" + hashlib.sha256(_canonical(row.to_dict()).encode()).hexdigest()[:24], axis=1)
        return output

    @staticmethod
    def _base_dict(row) -> dict[str, object]:
        return {key: getattr(row, key) for key in ("group_id", "fsu", "state", "sector", "stratum", "release", "observation_type", "design_period", "visit", "month")}

    @staticmethod
    def _values(frame: pd.DataFrame, variable: str) -> pd.Series:
        """Numeric values with questionnaire placeholders removed (survey_rules.plfs).

        Earnings and day-7 hours are compared only among persons for whom the
        item applies; otherwise an FSU "earnings distribution" mostly measures
        how many non-earners it has (audit H5).  Composition is examined
        separately through the activity-status mix.
        """
        values = _numeric(frame[variable])
        if variable in ("cws_earnings_salaried", "cws_earnings_self_employed", "day7_total_hours") and "cws_status" in frame:
            values = values.where(applicability_series(variable, frame["cws_status"]).eq(APPLICABLE).to_numpy())
        return values

    def _cells(self, frame: pd.DataFrame, values: pd.Series, categorical: bool = False):
        boundary = self._boundary_columns()
        work = frame[boundary + ["fsu"]].copy()
        work["_value"] = values.to_numpy()
        valid = work["_value"].astype(str).ne("") if categorical else pd.to_numeric(work["_value"], errors="coerce").notna()
        work = work.loc[valid]
        sizes = work.groupby(boundary + ["fsu"], observed=True).size()
        cells = {tuple(key if isinstance(key, tuple) else (key,)): (cell["_value"].to_numpy(), cell["fsu"].astype(str).to_numpy())
                 for key, cell in work.groupby(boundary, observed=True, sort=False)}
        return work, sizes, cells

    def _gate(self, component, base, variable, n, reference_n, minimum):
        if n == 0:
            return self._row(component=component, base=base, variable=variable, reason="ZERO_VALID_OBSERVATIONS")
        if n < minimum:
            return self._row(component=component, base=base, variable=variable, n=n, reference_n=reference_n, reason="PATTERN_GROUP_BELOW_MINIMUM")
        if reference_n < self.config.parameters.minimum_reference_population:
            return self._row(component=component, base=base, variable=variable, n=n, reference_n=reference_n, reason="REFERENCE_GROUP_BELOW_MINIMUM")
        return None

    def _locate(self, item, sizes, cells):
        cell_key = tuple(getattr(item, col) for col in self._boundary_columns())
        n = int(sizes.get(cell_key + (item.fsu,), 0))
        cell = cells.get(cell_key)
        reference_n = int(len(cell[0]) - n) if cell is not None else 0
        return n, reference_n, cell

    def _distribution(self, frame: pd.DataFrame) -> pd.DataFrame:
        """FSU vs leave-FSU-out reference: G-test (categorical) or Mann-Whitney (numeric).

        The score is -log10(p).  Unlike a raw distance, a p-value accounts for
        the FSU's size, so a small FSU is not ranked as unusual merely because
        a few people make its proportions noisy (audit H6).
        """
        rows: list[dict[str, object]] = []
        identities = self._fsu_identity(frame)
        boundary = self._boundary_columns()
        for variable in (*self.config.parameters.categorical_targets, *self.config.parameters.numerical_targets):
            if variable not in frame:
                continue
            categorical = variable in self.config.parameters.categorical_targets
            values = _clean(frame[variable]) if categorical else self._values(frame, variable)
            work, sizes, cells = self._cells(frame, values, categorical)
            if categorical:
                # Count once per cell and FSU; per-FSU scanning of the whole cell was quadratic.
                work = work.assign(_value=work["_value"].astype(str))
                fsu_counts = work.groupby(boundary + ["fsu", "_value"], observed=True).size()
                cell_counts = work.groupby(boundary + ["_value"], observed=True).size()
                cell_categories = {key: sorted(group.index.get_level_values("_value")) for key, group in cell_counts.groupby(level=list(range(len(boundary))))}
            for item in identities.itertuples(index=False):
                base = self._base_dict(item)
                n, reference_n, cell = self._locate(item, sizes, cells)
                gated = self._gate("fsu_distribution_shift", base, variable, n, reference_n, self.config.parameters.minimum_fsu_population)
                if gated:
                    rows.append(gated); continue
                cell_values, cell_fsus = cell
                if not categorical:
                    own = cell_values[cell_fsus == str(item.fsu)]
                    ref = cell_values[cell_fsus != str(item.fsu)]
                if categorical:
                    cell_key = tuple(getattr(item, col) for col in boundary)
                    categories = cell_categories[cell_key]
                    totals = np.array([cell_counts.get(cell_key + (c,), 0) for c in categories], dtype=float)
                    own_counts = np.array([fsu_counts.get(cell_key + (str(item.fsu), c), 0) for c in categories], dtype=float)
                    ref_counts = totals - own_counts
                    keep = (own_counts + ref_counts) > 0
                    categories = [c for c, k in zip(categories, keep) if k]; own_counts, ref_counts = own_counts[keep], ref_counts[keep]
                    p_value, g = g_test_p_value(own_counts, ref_counts)
                    p_own, p_ref = own_counts / n, ref_counts / reference_n
                    largest = int(np.argmax(np.abs(p_own - p_ref)))
                    metric = _js_distance(p_own, p_ref)
                    details = {"test": "G-test (Williams-corrected, chi-square approximation)", "G": g, "categories": categories,
                               "fsu_proportions": p_own.tolist(), "reference_proportions": p_ref.tolist(),
                               "largest_difference_category": categories[largest], "jensen_shannon_distance": metric}
                    statement = (f"FSU {item.fsu}: the mix of {variable} differs from comparable FSUs; the largest difference is for "
                                 f"{categories[largest]} ({p_own[largest]:.0%} in this FSU vs {p_ref[largest]:.0%} in comparable FSUs).")
                else:
                    own_f, ref_f = own.astype(float), ref.astype(float)
                    if np.unique(np.concatenate([own_f, ref_f])).size < 2:
                        rows.append(self._row(component="fsu_distribution_shift", base=base, variable=variable, n=n, reference_n=reference_n,
                                              reason="NO_VARIATION_IN_CELL")); continue
                    p_value = float(stats.mannwhitneyu(own_f, ref_f, alternative="two-sided", method="asymptotic").pvalue)
                    own_med, ref_med = float(np.median(own_f)), float(np.median(ref_f))
                    direction = "higher" if own_med > ref_med else "lower" if own_med < ref_med else None
                    metric = abs(own_med - ref_med)
                    details = {"test": "Mann-Whitney U (two-sided, asymptotic)", "fsu_median": own_med, "reference_median": ref_med,
                               "fsu_q25": float(np.quantile(own_f, .25)), "fsu_q75": float(np.quantile(own_f, .75)),
                               "reference_q25": float(np.quantile(ref_f, .25)), "reference_q75": float(np.quantile(ref_f, .75)),
                               "direction_of_medians": direction or "equal",
                               "population": "all persons" if variable == "age" else "persons for whom the item applies"}
                    statement = (f"FSU {item.fsu}: the typical {variable} is {direction} than in comparable FSUs (median {own_med:g} vs {ref_med:g})."
                                 if direction else f"FSU {item.fsu}: the distribution of {variable} differs from comparable FSUs although the medians are equal ({own_med:g}).")
                rows.append(self._row(component="fsu_distribution_shift", base=base, variable=variable, n=n, reference_n=reference_n,
                                      raw_metric=float(metric), status="ASSESSABLE", statement=statement, details=details, p_value=p_value))
        return self._rank(pd.DataFrame(rows))

    def _concentration(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Lower variation: one-sided, location-free binomial test of spread.

        Replaces the V1 IQR rank, whose tie handling counted ties 1.5 times and
        produced positions above 1 and negative scores (audit M1/M2).  The
        expected share under "no difference" is the empirical share of
        reference values inside [Q25, Q75], so ties are handled exactly.
        """
        rows: list[dict[str, object]] = []
        identities = self._fsu_identity(frame)
        for variable in self.config.parameters.numerical_targets:
            if variable not in frame:
                continue
            _, sizes, cells = self._cells(frame, self._values(frame, variable))
            for item in identities.itertuples(index=False):
                base = self._base_dict(item)
                n, reference_n, cell = self._locate(item, sizes, cells)
                gated = self._gate("reduced_variance_concentration", base, variable, n, reference_n, self.config.parameters.minimum_fsu_population)
                if gated:
                    rows.append(gated); continue
                own = cell[0][cell[1] == str(item.fsu)].astype(float)
                ref = cell[0][cell[1] != str(item.fsu)].astype(float)
                q25, q75 = np.quantile(ref, [.25, .75])
                half_width = float(q75 - q25) / 2.0
                if half_width <= 0:
                    rows.append(self._row(component="reduced_variance_concentration", base=base, variable=variable, n=n, reference_n=reference_n,
                                          reason="REFERENCE_HAS_NO_SPREAD", details={"reference_q25": float(q25), "reference_q75": float(q75)})); continue
                # Location-free: a window of half the reference IQR either side of
                # each group's own median.  Under equal spread the FSU share inside
                # its window matches the reference share inside the reference's.
                expected = float((np.abs(ref - np.median(ref)) <= half_width).mean())
                inside = int((np.abs(own - np.median(own)) <= half_width).sum())
                share = inside / n
                if expected >= 1.0:
                    rows.append(self._row(component="reduced_variance_concentration", base=base, variable=variable, n=n, reference_n=reference_n,
                                          reason="REFERENCE_HAS_NO_SPREAD", details={"reference_q25": float(q25), "reference_q75": float(q75)})); continue
                p_value = float(stats.binom.sf(inside - 1, n, expected))
                statement = (f"FSU {item.fsu}: {share:.0%} of {variable} values lie close to the FSU's own typical value (within half the usual spread of comparable FSUs), compared with {expected:.0%} in comparable FSUs; values vary less than usual."
                             if share > expected else f"FSU {item.fsu}: {variable} values do not vary less than in comparable FSUs.")
                rows.append(self._row(component="reduced_variance_concentration", base=base, variable=variable, n=n, reference_n=reference_n,
                                      raw_metric=share, status="ASSESSABLE", statement=statement, p_value=p_value,
                                      details={"test": "one-sided binomial: share within ±(reference IQR/2) of own median greater than reference share",
                                               "fsu_share_close_to_own_median": share, "expected_share": expected, "inside": inside,
                                               "window_half_width": half_width, "fsu_median": float(np.median(own)), "reference_median": float(np.median(ref)),
                                               "fsu_iqr": float(np.quantile(own, .75) - np.quantile(own, .25)), "reference_iqr": float(q75 - q25),
                                               "approximation": "centring on the FSU's own median makes small-FSU p-values slightly optimistic"}))
        return self._rank(pd.DataFrame(rows))

    def _heaping(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Age heaping: one-sided binomial test of the share of values ending in 0 or 5.

        Terminal-digit preference for 0/5 is the established age-heaping signal
        (Whipple/Myers family).  Rupee earnings and day-7 hours are not tested:
        earnings are routinely reported in round amounts and hours (0-24) are
        not a terminal-digit measure (audit H4/H5).  A statement says "higher"
        only when the FSU share exceeds the reference share.
        """
        rows = []
        identities = self._fsu_identity(frame)
        for variable in self.config.parameters.heaping_targets:
            if variable not in frame:
                continue
            value = _numeric(frame[variable])
            integer = value.where(value.notna() & np.isclose(value.fillna(0.5), np.round(value.fillna(0.5))))
            preferred = pd.Series(np.where(integer.notna(), (np.abs(np.round(integer.fillna(1))) % 5 == 0).astype(float), np.nan), index=frame.index)
            _, sizes, cells = self._cells(frame, preferred)
            for item in identities.itertuples(index=False):
                base = self._base_dict(item)
                n, reference_n, cell = self._locate(item, sizes, cells)
                gated = self._gate("digit_heaping", base, variable, n, reference_n, self.config.parameters.minimum_valid_target_population)
                if gated:
                    rows.append(gated); continue
                own = cell[0][cell[1] == str(item.fsu)].astype(float)
                ref = cell[0][cell[1] != str(item.fsu)].astype(float)
                k, expected = int(own.sum()), float(ref.mean())
                share = k / n
                p_value = float(stats.binom.sf(k - 1, n, expected)) if 0 < expected < 1 else 1.0
                higher = share > expected
                statement = (f"FSU {item.fsu}: {share:.0%} of reported {variable} values end in 0 or 5, compared with {expected:.0%} in comparable FSUs."
                             + ("" if higher else " This is not higher than in comparable FSUs."))
                rows.append(self._row(component="digit_heaping", base=base, variable=variable, n=n, reference_n=reference_n, raw_metric=share,
                                      status="ASSESSABLE", statement=statement, p_value=p_value,
                                      details={"test": "one-sided binomial (share ending in 0 or 5 greater than reference share)",
                                               "fsu_share_ending_0_or_5": share, "reference_share_ending_0_or_5": expected,
                                               "count_ending_0_or_5": k, "direction": "higher" if higher else "not higher"}))
        return self._rank(pd.DataFrame(rows))

    def _temporal(self, frame: pd.DataFrame) -> pd.DataFrame:
        """FSU-level preceding-period comparison (kept for panel deliveries).

        In first-visit files an FSU is observed in a single quarter/month, so no
        FSU history exists; such rows are explicitly FSU_OBSERVED_IN_ONE_PERIOD_ONLY
        (audit: 0 of 63,745 rows assessable).  Aggregate temporal drift is
        produced by the separate ``historical`` layer.
        """
        rows = []
        time_col = "month" if frame.design_period.eq("post_2025").any() else "quarter"
        group_cols = ["release", "observation_type", "design_period", "visit", "state", "sector", "stratum", "fsu", time_col]
        for variable in self.config.parameters.temporal_targets:
            if variable not in frame:
                continue
            work = frame.copy()
            if variable == "cws_status":
                values = _clean(work[variable]); eligible = values.ne(""); work["_metric"] = (values == "1").astype(float)
                metric_name = "cws_status_code_1_proportion"
            else:
                work["_metric"] = self._values(work, variable); eligible = work._metric.notna(); metric_name = f"median_{variable}"
            work = work.loc[eligible & work[time_col].ne("")].copy()
            if work.empty:
                continue
            aggregate = work.groupby(group_cols, observed=True)._metric.agg([("current_value", "median"), ("n", "size")]).reset_index()
            for _, series in aggregate.groupby(group_cols[:-1], observed=True, sort=True):
                series = series.assign(_order=pd.to_numeric(series[time_col].astype(str).str.lstrip("Q"), errors="coerce")).sort_values(["_order", time_col], kind="mergesort")
                for position, item in enumerate(series.itertuples(index=False)):
                    base = {"release": item.release, "observation_type": item.observation_type, "design_period": item.design_period, "visit": item.visit,
                            "month": item.month if time_col == "month" else "", "state": item.state, "sector": item.sector, "stratum": item.stratum, "fsu": item.fsu,
                            "group_id": "fsu_" + hashlib.sha256(_canonical({k: getattr(item, k) for k in group_cols[:-1]}).encode()).hexdigest()[:24]}
                    history = series.iloc[:position]
                    period = str(getattr(item, time_col))
                    common = dict(component="temporal_drift", base=base, variable=metric_name, n=int(item.n), period=period, group_level="FSU_TIME")
                    if int(item.n) < self.config.parameters.minimum_temporal_population:
                        rows.append(self._row(**common, reason="PATTERN_GROUP_BELOW_MINIMUM")); continue
                    if len(series) == 1:
                        rows.append(self._row(**common, reason="FSU_OBSERVED_IN_ONE_PERIOD_ONLY")); continue
                    if len(history) < self.config.parameters.minimum_temporal_history:
                        rows.append(self._row(**common, reason="INSUFFICIENT_REFERENCE_HISTORY")); continue
                    baseline = float(history.current_value.median()); changes = history.current_value.diff().dropna()
                    scale = float(changes.abs().median()) if len(changes) else np.nan; change = float(item.current_value - baseline)
                    if not np.isfinite(scale) or scale == 0:
                        rows.append(self._row(**common, raw_metric=change, reason="ZERO_REFERENCE_HISTORY_VARIATION", details={"baseline": baseline})); continue
                    rows.append(self._row(**common, reference_n=len(history), raw_metric=change, score=abs(change) / scale, status="ASSESSABLE",
                                          statement=f"The FSU-level {metric_name} changed by {change:g} relative to its preceding-period baseline.",
                                          details={"baseline": baseline, "historical_change_mad_like_scale": scale, "time_axis": time_col}))
        return self._rank(pd.DataFrame(rows))

    def _revisit(self, frame: pd.DataFrame, metadata: dict[str, object]) -> pd.DataFrame:
        if not self.config.revisit_prepared_person_path:
            # One explicit status row is emitted for this input; no panel data are invented.
            base=self._base_dict(self._fsu_identity(frame).iloc[0]) if not frame.empty else {"group_id":"unavailable","fsu":pd.NA,"state":pd.NA,"sector":pd.NA,"stratum":pd.NA,"release":metadata["release"],"observation_type":metadata["observation"],"design_period":metadata["design_period"],"visit":"","month":""}
            return pd.DataFrame([self._row(component="revisit_transition_patterns",base=base,variable="linked_revisit_transition_rate",reason="REVISIT_DATA_UNAVAILABLE",group_level="FSU")])
        stat_path=self.config.revisit_statistical_run_path / "revisit_statistical_evidence.parquet"
        if not stat_path.is_file(): raise PatternFailure("Revisit statistical run lacks revisit_statistical_evidence.parquet")
        revisit_meta=self._metadata(self.config.revisit_prepared_person_path.parent/"run_metadata.json")
        if (revisit_meta.get("release"),revisit_meta.get("observation")) != ("2023_24","revisit"): raise PatternFailure("Only validated 2023-24 revisit linkage may be used")
        profile=SOURCE_PROFILES[("2023_24","revisit")]; contract=next(v for v in CONTRACTS.values() if v.release=="2023_24" and v.observation=="revisit"); revisit=self._base(revisit_meta,profile,contract,self.config.revisit_prepared_person_path)
        evidence=pd.read_parquet(stat_path,columns=["source_observation_id","target_variable","revisit_comparison_status","revisit_change_distribution_position","reference_run_id"])
        if not evidence.reference_run_id.astype(str).eq(str(revisit_meta["run_id"])).all(): raise PatternFailure("Revisit statistical evidence provenance does not match supplied revisit preparation run")
        joined=evidence.merge(revisit[["source_observation_id","release","observation_type","design_period","visit","month","state","sector","stratum","fsu","ready"]],on="source_observation_id",how="left",validate="many_to_one")
        if joined.fsu.isna().any(): raise PatternFailure("Revisit statistical evidence cannot be mapped to supplied revisit FSU records")
        rows=[]; boundary=self._boundary_columns(); valid=joined.revisit_comparison_status.eq("ASSESSABLE"); joined["transition"] = joined.revisit_change_distribution_position.isin(["LOWER_TAIL","UPPER_TAIL"])
        # Aggregate once, then subtract each FSU from its bounded cell.  The
        # former implementation repeatedly copied the full linked release for
        # every FSU, which is neither memory-bounded nor necessary.
        eligible=joined.loc[valid].copy(); keys=boundary+["target_variable"]
        totals=eligible.groupby(keys,observed=True).transition.agg(total_n="size",total_transition="sum").reset_index()
        groups=eligible.groupby(keys+["fsu"],observed=True).transition.agg(n="size",transition_count="sum").reset_index().merge(totals,on=keys,how="left",validate="many_to_one")
        for item in groups.itertuples(index=False):
            base={col:getattr(item,col) for col in boundary}; fsu=str(item.fsu); target=str(item.target_variable); base["fsu"]=fsu;base["group_id"]="fsu_"+hashlib.sha256(_canonical(base|{"fsu":fsu}).encode()).hexdigest()[:24]
            n=int(item.n); refn=int(item.total_n-item.n)
            if n<self.config.parameters.minimum_revisit_linked_population: rows.append(self._row(component="revisit_transition_patterns",base=base,variable=target,n=n,reference_n=refn,reason="REVISIT_LINKAGE_UNAVAILABLE" if n==0 else "PATTERN_GROUP_BELOW_MINIMUM")); continue
            if refn<self.config.parameters.minimum_reference_population: rows.append(self._row(component="revisit_transition_patterns",base=base,variable=target,n=n,reference_n=refn,reason="REFERENCE_GROUP_BELOW_MINIMUM")); continue
            rate=float(item.transition_count/item.n); rrate=float((item.total_transition-item.transition_count)/refn); pval=float(stats.binomtest(int(item.transition_count),n,min(max(rrate,1e-9),1-1e-9)).pvalue) if 0<rrate<1 else 1.0
            rows.append(self._row(component="revisit_transition_patterns",base=base,variable=target,n=n,reference_n=refn,raw_metric=rate,status="ASSESSABLE",p_value=pval,statement=f"FSU {fsu}: {rate:.0%} of linked revisit changes are in the tails of their comparison group, compared with {rrate:.0%} in comparable FSUs.",details={"transition_count":int(item.transition_count),"transition_rate":rate,"reference_transition_rate":rrate,"transition_definition":"existing_statistical_revisit_change_distribution_position_in_lower_or_upper_tail"}))
        return self._rank(pd.DataFrame(rows))

    @staticmethod
    def _rank(table: pd.DataFrame) -> pd.DataFrame:
        """Percentile rank of the score, plus BH q-values within component/variable.

        ``notable`` (q < 0.05) is the only threshold used for wording; ranks
        order evidence and are never read as probabilities.
        """
        if table.empty: return table
        if "p_value" not in table: table["p_value"] = np.nan
        table["q_value"] = np.nan
        assessable=table.assessability_status.eq("ASSESSABLE") & pd.to_numeric(table.evidence_score,errors="coerce").notna()
        table.loc[assessable,"evidence_rank"]=table.loc[assessable].groupby(["pattern_component","variable"],observed=True).evidence_score.rank(pct=True,method="average")
        with_p = assessable & pd.to_numeric(table.p_value, errors="coerce").notna()
        table["p_value_unadjusted"] = table["p_value"]
        table["dispersion_factor"] = np.nan
        for (component, _), index in table.loc[with_p].groupby(["pattern_component", "variable"], observed=True).groups.items():
            adjusted, phi = overdispersion_adjust(table.loc[index, "p_value"].astype(float), one_sided=component in ONE_SIDED)
            table.loc[index, "p_value"] = adjusted.to_numpy()
            table.loc[index, "dispersion_factor"] = phi
            table.loc[index, "evidence_score"] = -np.log10(adjusted.clip(lower=P_FLOOR)).to_numpy()
            table.loc[index, "q_value"] = benjamini_hochberg(table.loc[index, "p_value"]).to_numpy()
        table.loc[assessable, "evidence_rank"] = table.loc[assessable].groupby(["pattern_component", "variable"], observed=True).evidence_score.rank(pct=True, method="average")
        table["notable"] = pd.to_numeric(table["q_value"], errors="coerce").lt(0.05)
        return table

    def _normalise(self, table: pd.DataFrame) -> pd.DataFrame:
        for column in COMMON_COLUMNS:
            if column not in table: table[column]=pd.NA
        table=table.loc[:,COMMON_COLUMNS].replace([np.inf,-np.inf],np.nan)
        return table.sort_values(["pattern_component","variable","group_id","period","evidence_id"],kind="mergesort",ignore_index=True)

    @staticmethod
    def _summary(table: pd.DataFrame) -> dict[str, object]:
        status=table.assessability_status.eq("ASSESSABLE")
        return {"rows":int(len(table)),"assessable":int(status.sum()),"not_assessable":int((~status).sum()),"not_assessable_reasons":{str(k):int(v) for k,v in table.loc[~status,"assessability_reason"].fillna("UNSPECIFIED").value_counts().sort_index().items()}}

    def run(self) -> Path:
        started=time.perf_counter(); metadata,profile,contract=self._validate(); base=self._group_frame(self._base(metadata,profile,contract)); self.preprocessing_run_id=str(metadata["run_id"]); self.pattern_run_id=self.config.run_id or str(uuid.uuid4())
        destination=self.config.output_root/f"{metadata['release']}_{metadata['observation']}_{self.pattern_run_id}"; destination.mkdir(parents=True,exist_ok=False)
        builders={"fsu_distribution_shift.parquet":self._distribution,"concentration_evidence.parquet":self._concentration,"heaping_evidence.parquet":self._heaping,"temporal_drift.parquet":self._temporal,"revisit_pattern_evidence.parquet":lambda _:self._revisit(base,metadata)}
        summaries={}
        # Persist one component at a time.  Prepared releases are large, and
        # retaining five wide evidence tables while calculating the next one
        # needlessly raises peak memory without improving reproducibility.
        for name,builder in builders.items():
            table=self._normalise(builder(base))
            table.to_parquet(destination/name,index=False)
            summaries[name.removesuffix(".parquet")]=self._summary(table)
            del table
            gc.collect()
        combined=self._normalise(pd.concat([pd.read_parquet(destination/name) for name in builders],ignore_index=True)); combined.to_parquet(destination/"pattern_evidence.parquet",index=False)
        report={"records_processed":int(len(base)),"fsu_groups":int(base[self._boundary_columns()+["fsu"]].drop_duplicates().shape[0]),"runtime_seconds":round(time.perf_counter()-started,3),"components":summaries,"warnings":["Pattern V1 uses dedicated leave-FSU-out stratum references; it does not reinterpret an FSU as an enumerator.","Temporal drift uses preceding-period history inside one prepared release and deliberately does not estimate seasonality or cross the January-2025 structural break.","Revisit patterns aggregate only the existing 2023-24 statistical linked-change tail definition when a matching validated statistical run is supplied."]}
        run_metadata={"run_id":self.pattern_run_id,"processing_timestamp_utc":utc_now(),"software_version":"0.1.0","pattern_method_version":PATTERN_METHOD_VERSION,"pattern_specification_version":PATTERN_SPECIFICATION_VERSION,"input_preprocessing_run_id":self.preprocessing_run_id,"input_prepared_person_path":str(self.config.prepared_person_path),"release":metadata["release"],"observation":metadata["observation"],"design_period":metadata["design_period"],"parameters":self.config.parameters.__dict__,"revisit_prepared_person_path":str(self.config.revisit_prepared_person_path) if self.config.revisit_prepared_person_path else None,"revisit_statistical_run_path":str(self.config.revisit_statistical_run_path) if self.config.revisit_statistical_run_path else None,"output_files":[*builders,"pattern_evidence.parquet","pattern_report.json","pattern_report.md","run_metadata.json"]}
        write_json(destination/"pattern_report.json",report);write_json(destination/"run_metadata.json",run_metadata);write_markdown_report(destination/"pattern_report.md",run_metadata,report)
        return destination
