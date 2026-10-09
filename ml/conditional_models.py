"""Expected-value (conditional) models trained on earlier periods (plan W3.5).

Question answered: "is this value plausible for a person with these
characteristics?"  For each target the model predicts the value from
non-target characteristics (age, sex, education, activity status,
occupation group, industry division, State/UT, sector; hours where the
target is not hours).  Identifiers and survey weights are never features.

Training scheme (brief Feature 2: models built from historical data and
applied to new data)
    For a record of period p, the model is trained only on records of
    *strictly earlier* periods of the same design period (the de-duplicated
    axis of survey_rules.period_index; nothing crosses the January-2025
    redesign).  A record's own period, and therefore any current-round
    error, never trains the model that scores it.  Where no earlier period
    exists (the first period of a design), the model falls back to the
    in-round, FSU-grouped two-fold cross-fit and says so.

Evidence
    A held-out calibration set (20% of the training FSUs, by stable hash)
    gives the distribution of out-of-sample residuals, kept per State
    (Mondrian calibration, v2.1) where the State has at least
    ``conformal_group_minimum`` residuals and national otherwise.  For a scored record
    with residual r the tail probability is the split-conformal p-value
    ``(#calibration |residual| >= |r| + 1) / (n_cal + 1)``, and the usual
    range for similar people is prediction + [5th, 95th] percentile of the
    calibration residuals (back-transformed for log targets).  These are
    calibrated to the training periods; drift between periods makes them
    approximate, which the evaluation stage must check (§12.5 calibration).

Populations (questionnaire applicability, survey_rules.plfs)
    Earnings and wages are modelled on the log scale among applicable,
    strictly positive values (an applicable 0 or a net loss is a genuine
    answer that a log model cannot represent: reported as not modelled).
    Day-7 hours are modelled on the natural scale among applicable workers.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.preprocessing import OrdinalEncoder

from survey_rules import APPLICABLE, applicability_series, status_concept

from .config import CONDITIONAL_FEATURE_SPEC_VERSION, ML_METHOD_VERSION, Parameters, RANDOM_SEED


@dataclass(frozen=True)
class TargetSpec:
    name: str
    value_column: str          # column in the ML base table
    log_scale: bool
    numeric_features: tuple[str, ...]
    categorical_features: tuple[str, ...]


COMMON_CATEGORICAL = ("sex", "education", "cws_status", "occupation_major_group", "industry_division", "state", "sector")
TARGETS: tuple[TargetSpec, ...] = (
    TargetSpec("cws_earnings_salaried", "earnings_salaried", True, ("age", "day7_hours"), COMMON_CATEGORICAL),
    TargetSpec("cws_earnings_self_employed", "earnings_self_employed", True, ("age", "day7_hours"), COMMON_CATEGORICAL),
    TargetSpec("day7_casual_wage", "casual_wage", True, ("age", "day7_hours"),
               ("sex", "education", "day7_activity1_status", "day7_activity1_industry", "state", "sector")),
    TargetSpec("day7_total_hours", "day7_hours", False, ("age",), COMMON_CATEGORICAL),
)

OUTPUT_COLUMNS = (
    "source_observation_id", "record_id", "release", "observation_type", "design_period", "visit", "month", "period_index",
    "preprocessing_run_id", "method", "method_version", "feature_spec_version", "target", "observed_value", "target_applicability",
    "predicted_value", "usual_range_low", "usual_range_high", "log_residual", "residual", "observed_to_estimate_ratio",
    "raw_model_score", "model_tail_p", "evidence_rank", "training_scheme", "training_periods", "model_id", "training_fold",
    "model_iterations", "assessability_status", "assessability_reason", "evidence_statement", "decision_path", "source_reference_metadata",
)


def _hash(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:16], 16)


def _fsu_key(frame: pd.DataFrame) -> pd.Series:
    return frame["state"].astype(str) + "|" + frame["sector"].astype(str) + "|" + frame["fsu"].astype(str)


def _features(frame: pd.DataFrame, spec: TargetSpec) -> pd.DataFrame:
    result = pd.DataFrame(index=frame.index)
    for column in spec.numeric_features:
        result[column] = pd.to_numeric(frame[column], errors="coerce") if column in frame else np.nan
    for column in spec.categorical_features:
        result[column] = frame[column].astype("string").fillna("").replace("", "<MISSING>") if column in frame else "<MISSING>"
    return result


def _eligible(frame: pd.DataFrame, spec: TargetSpec) -> tuple[pd.Series, pd.Series, pd.Series]:
    """(numeric value, applicability label, eligible-for-model mask)."""
    value = pd.to_numeric(frame[spec.value_column], errors="coerce") if spec.value_column in frame else pd.Series(np.nan, index=frame.index)
    status_column = status_concept(spec.name)
    status = frame[status_column].astype("string") if status_column in frame else pd.Series("", index=frame.index, dtype="string")
    applicability = applicability_series(spec.name, status)
    finite = np.isfinite(value.to_numpy(dtype=float))
    ok = frame["prepared_ready"].astype(bool).to_numpy() & applicability.eq(APPLICABLE).to_numpy() & finite
    if spec.log_scale:
        ok &= value.gt(0).to_numpy()
    return value, applicability, pd.Series(ok, index=frame.index)


class _Model:
    """One fitted expected-value model with its conformal calibration."""

    def __init__(self, spec: TargetSpec, parameters: Parameters, seed: int) -> None:
        self.spec, self.parameters, self.seed = spec, parameters, seed

    def _matrix(self, features: pd.DataFrame) -> np.ndarray:
        categorical = list(self.spec.categorical_features)
        coded = self.encoder.transform(features[categorical])
        coded[coded < 0] = np.nan  # unseen category -> missing, never a new category
        return np.hstack([features[list(self.spec.numeric_features)].to_numpy(dtype=float), coded])

    def _transform(self, value: np.ndarray) -> np.ndarray:
        return np.log(value) if self.spec.log_scale else value

    def fit(self, features: pd.DataFrame, value: np.ndarray, groups: pd.Series, ids: pd.Series) -> "_Model":
        calibration = groups.map(lambda g: _hash("cal|" + g) % 5 == 0).to_numpy()   # 20% of FSUs held out
        if calibration.all() or not calibration.any():
            calibration = np.arange(len(value)) % 5 == 0
        train_index = np.flatnonzero(~calibration)
        if len(train_index) > self.parameters.maximum_training_rows:
            ranks = np.array([_hash(str(i)) for i in ids.iloc[train_index]])
            train_index = train_index[np.argsort(ranks, kind="mergesort")[:self.parameters.maximum_training_rows]]
        categorical = list(self.spec.categorical_features)
        self.encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1, encoded_missing_value=-1, dtype=np.float64)
        self.encoder.fit(features.iloc[train_index][categorical])
        mask = [False] * len(self.spec.numeric_features) + [True] * len(categorical)
        self.model = HistGradientBoostingRegressor(
            max_iter=self.parameters.conditional_max_iterations, learning_rate=self.parameters.conditional_learning_rate,
            max_leaf_nodes=31, min_samples_leaf=20, l2_regularization=1.0, categorical_features=mask,
            early_stopping=True, validation_fraction=0.1, n_iter_no_change=20, random_state=self.seed,
        ).fit(self._matrix(features.iloc[train_index]), self._transform(value[train_index]))
        cal_index = np.flatnonzero(calibration)
        residual = self._transform(value[cal_index]) - self.model.predict(self._matrix(features.iloc[cal_index]))
        self.calibration_abs = np.sort(np.abs(residual))
        # Mondrian (State-conditional) calibration: split-conformal p-values are calibrated only on
        # average over the calibration set; States whose residuals are wider or narrower than the
        # national mix would otherwise be over- or under-flagged.
        self.group_calibration: dict[str, np.ndarray] = {}
        minimum = self.parameters.conformal_group_minimum
        if minimum and "state" in features:
            states = features["state"].iloc[cal_index].astype(str).to_numpy()
            for state in np.unique(states):
                chosen = np.abs(residual[states == state])
                if len(chosen) >= minimum:
                    self.group_calibration[state] = np.sort(chosen)
        self.residual_quantiles = np.quantile(residual, [0.05, 0.95]) if len(residual) else np.array([np.nan, np.nan])
        self.n_train, self.n_calibration = len(train_index), len(cal_index)
        return self

    def score(self, features: pd.DataFrame, value: np.ndarray) -> dict[str, np.ndarray]:
        predicted = self.model.predict(self._matrix(features))
        residual = self._transform(value) - predicted
        p = self._tail_p(np.abs(residual), self.calibration_abs)
        calibrated_by = np.full(len(residual), "NATIONAL", dtype=object)
        if self.group_calibration and "state" in features:
            states = features["state"].astype(str).to_numpy()
            for state, reference in self.group_calibration.items():
                rows = states == state
                if rows.any():
                    p[rows] = self._tail_p(np.abs(residual[rows]), reference)
                    calibrated_by[rows] = "STATE"
        low, high = predicted + self.residual_quantiles[0], predicted + self.residual_quantiles[1]
        back = np.exp if self.spec.log_scale else (lambda x: x)
        return {"predicted": back(predicted), "low": back(low), "high": back(high), "residual": residual, "p": p, "calibrated_by": calibrated_by}

    @staticmethod
    def _tail_p(absolute: np.ndarray, reference: np.ndarray) -> np.ndarray:
        n = len(reference)
        at_least = n - np.searchsorted(reference, absolute, side="left")
        return (at_least + 1.0) / (n + 1.0)


def _empty(base: pd.DataFrame, spec: TargetSpec, period: pd.Series) -> pd.DataFrame:
    output = base[["source_observation_id", "record_id", "release", "observation_type", "design_period", "visit", "month", "preprocessing_run_id"]].copy()
    output["period_index"] = period.to_numpy(dtype=float)
    output["method"] = "gradient_boosted_conditional_model"
    output["method_version"] = ML_METHOD_VERSION
    output["feature_spec_version"] = CONDITIONAL_FEATURE_SPEC_VERSION
    output["target"] = spec.name
    for column in ("predicted_value", "usual_range_low", "usual_range_high", "log_residual", "residual", "observed_to_estimate_ratio",
                   "raw_model_score", "model_tail_p", "evidence_rank", "model_iterations"):
        output[column] = np.nan
    for column in ("training_scheme", "training_periods", "model_id", "evidence_statement"):
        output[column] = ""
    output["training_fold"] = pd.NA
    output["assessability_status"] = "NOT_ASSESSABLE"
    output["decision_path"] = "VALUE_CHECK"
    output["source_reference_metadata"] = ("trained on strictly earlier periods of the same design period; 20% of training FSUs held out for "
                                           "split-conformal calibration within State (national below the minimum); in-round FSU-grouped cross-fit only where no earlier period exists")
    return output


def run_conditional_models(base: pd.DataFrame, parameters: Parameters, history: pd.DataFrame | None = None) -> tuple[pd.DataFrame, list[dict]]:
    """Score every record of ``base`` for every target.  Returns (long evidence table, model registry entries).

    ``base`` and ``history`` carry ``period_index``; ``history`` holds earlier
    periods of the same design period (de-duplicated by the caller) and may
    include ``base`` itself — only strictly earlier periods are ever used.
    """
    period = pd.to_numeric(base["period_index"], errors="coerce")
    pool = history if history is not None and len(history) else base
    pool_period = pd.to_numeric(pool["period_index"], errors="coerce")
    first_visit = base["observation_type"].astype(str).eq("first_visit")
    tables, registry = [], []
    for spec in TARGETS:
        output = _empty(base, spec, period)
        value, applicability, eligible = _eligible(base, spec)
        output["observed_value"] = value.to_numpy(dtype=float)
        output["target_applicability"] = applicability.to_numpy()
        ready = base["prepared_ready"].astype(bool)
        reason = pd.Series("TARGET_UNAVAILABLE_FOR_RELEASE_OBSERVATION", index=base.index, dtype="string")
        has_target = spec.value_column in base and pd.to_numeric(base[spec.value_column], errors="coerce").notna().any()
        if has_target:
            reason[:] = "PREPARED_RECORD_NOT_READY"
            reason[ready & ~applicability.eq(APPLICABLE)] = "TARGET_NOT_APPLICABLE_FOR_STATUS"
            finite = np.isfinite(value.to_numpy(dtype=float))
            reason[ready & applicability.eq(APPLICABLE) & ~finite] = "TARGET_MISSING_OR_NON_NUMERIC"
            if spec.log_scale:
                reason[ready & applicability.eq(APPLICABLE) & finite & ~value.gt(0)] = "APPLICABLE_ZERO_OR_NEGATIVE_NOT_MODELLED"
            reason[eligible & ~first_visit] = "CONDITIONAL_CONTEXT_UNAVAILABLE_FOR_OBSERVATION"
        eligible &= first_visit
        reason[eligible] = "INSUFFICIENT_TRAINING_POPULATION"
        output["assessability_reason"] = reason
        if not eligible.any():
            tables.append(output)
            continue
        features = _features(base, spec)
        pool_value, _, pool_eligible = _eligible(pool, spec)
        pool_features = _features(pool, spec)
        pool_groups = _fsu_key(pool)
        for scored_period in sorted(period[eligible].dropna().unique()):
            rows = eligible & period.eq(scored_period)
            train = pool_eligible & pool_period.lt(scored_period)
            if int(train.sum()) >= parameters.minimum_model_population:
                model = _Model(spec, parameters, RANDOM_SEED + int(scored_period)).fit(
                    pool_features.loc[train], pool_value[train].to_numpy(dtype=float), pool_groups[train], pool.loc[train, "source_observation_id"])
                scored = model.score(features.loc[rows], value[rows].to_numpy(dtype=float))
                periods = sorted(int(p) for p in pool_period[train].unique())
                model_id = f"cm_{spec.name}_p{int(scored_period)}_" + hashlib.sha256("|".join(sorted(pool.loc[train, "source_observation_id"].astype(str))).encode()).hexdigest()[:12]
                _write(output, rows, spec, scored, "TRAINED_ON_EARLIER_PERIODS", ",".join(map(str, periods)), model_id, model.model.n_iter_, pd.NA)
                registry.append({"model_id": model_id, "target": spec.name, "scored_period": int(scored_period), "training_scheme": "TRAINED_ON_EARLIER_PERIODS",
                                 "training_periods": periods, "training_rows": model.n_train, "calibration_rows": model.n_calibration,
                                 "iterations": int(model.model.n_iter_), "residual_q05_q95": [float(x) for x in model.residual_quantiles],
                                 "states_calibrated_separately": len(model.group_calibration),
                                 "scored_records_state_calibrated": int((scored["calibrated_by"] == "STATE").sum()),
                                 "scored_records": int(rows.sum()), "seed": RANDOM_SEED + int(scored_period)})
            else:
                _cross_fit(output, base, features, value, rows, spec, parameters, registry, int(scored_period))
        assessed = output["assessability_status"].eq("ASSESSABLE")
        # Kept for the pre-redesign (A0) evaluation baseline only.
        output.loc[assessed, "evidence_rank"] = output.loc[assessed, "raw_model_score"].rank(method="average", pct=True)
        tables.append(output)
    result = pd.concat(tables, ignore_index=True)
    return result.loc[:, list(OUTPUT_COLUMNS)], registry


def _write(output: pd.DataFrame, rows: pd.Series, spec: TargetSpec, scored: dict[str, np.ndarray], scheme: str, periods: str, model_id: str,
           iterations: int, fold: object) -> None:
    index = output.index[rows.to_numpy()]
    output.loc[index, "predicted_value"] = scored["predicted"]
    output.loc[index, "usual_range_low"] = scored["low"]
    output.loc[index, "usual_range_high"] = scored["high"]
    output.loc[index, "residual"] = scored["residual"]
    if spec.log_scale:
        output.loc[index, "log_residual"] = scored["residual"]
        output.loc[index, "observed_to_estimate_ratio"] = np.exp(scored["residual"])
    output.loc[index, "raw_model_score"] = np.abs(scored["residual"])
    output.loc[index, "model_tail_p"] = scored["p"]
    output.loc[index, "training_scheme"] = scheme
    output.loc[index, "training_periods"] = periods
    output.loc[index, "model_id"] = model_id
    output.loc[index, "model_iterations"] = int(iterations)
    output.loc[index, "training_fold"] = fold
    output.loc[index, "assessability_status"] = "ASSESSABLE"
    output.loc[index, "assessability_reason"] = pd.NA
    output.loc[index, "evidence_statement"] = "Reported value compared with the model estimate for people with the same characteristics."


def _cross_fit(output: pd.DataFrame, base: pd.DataFrame, features: pd.DataFrame, value: pd.Series, rows: pd.Series, spec: TargetSpec,
               parameters: Parameters, registry: list[dict], scored_period: int) -> None:
    """Fallback for the first period of a design: FSU-grouped two-fold cross-fit within the period."""
    folds = _fsu_key(base).map(lambda key: _hash(key) % parameters.conditional_folds)
    for fold in range(parameters.conditional_folds):
        score_rows = rows & folds.eq(fold)
        train_rows = rows & ~folds.eq(fold)
        if int(score_rows.sum()) == 0 or int(train_rows.sum()) < parameters.minimum_model_population:
            continue
        model = _Model(spec, parameters, RANDOM_SEED + 1000 + fold).fit(features.loc[train_rows], value[train_rows].to_numpy(dtype=float), _fsu_key(base)[train_rows],
                                                                        base.loc[train_rows, "source_observation_id"])
        scored = model.score(features.loc[score_rows], value[score_rows].to_numpy(dtype=float))
        model_id = f"cm_{spec.name}_p{scored_period}_crossfit{fold}"
        _write(output, score_rows, spec, scored, "IN_ROUND_CROSS_FIT_NO_EARLIER_PERIOD", str(scored_period), model_id, model.model.n_iter_, fold)
        registry.append({"model_id": model_id, "target": spec.name, "scored_period": scored_period, "training_scheme": "IN_ROUND_CROSS_FIT_NO_EARLIER_PERIOD",
                         "training_periods": [scored_period], "training_rows": model.n_train, "calibration_rows": model.n_calibration,
                         "iterations": int(model.model.n_iter_), "residual_q05_q95": [float(x) for x in model.residual_quantiles],
                         "states_calibrated_separately": len(model.group_calibration),
                         "scored_records_state_calibrated": int((scored["calibrated_by"] == "STATE").sum()),
                         "scored_records": int(score_rows.sum()), "seed": RANDOM_SEED + 1000 + fold})
