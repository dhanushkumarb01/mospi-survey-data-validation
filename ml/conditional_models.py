"""Leakage-controlled, cross-fitted conditional model for salaried earnings.

Population (PLFS Vol. I §3.6.17, §3.6.19): Block 6 item 9 is asked only of
persons whose current weekly status is 31, 71 or 72.  Everyone else carries a
questionnaire placeholder 0, which is *not* an earnings value and must never
enter the target.  An applicable 0 is a genuine answer (no salaried work in
the preceding calendar month); it is kept out of the log-scale model and
reported as not assessable here rather than being forced into a ratio.

The model is a gradient-boosted regression of log(earnings) on non-target
characteristics, including State/UT and sector.  ``exp(prediction)`` is a
central (geometric-mean-type) value for people with the same characteristics;
it is a *model estimate*, not the observed median of any group.  The evidence
is the size of the log ratio between the reported value and that estimate.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.preprocessing import OrdinalEncoder

from survey_rules import APPLICABLE, applicability_series

from .config import CONDITIONAL_FEATURE_SPEC_VERSION, CONDITIONAL_TARGET, ML_METHOD_VERSION, Parameters, RANDOM_SEED

NUMERIC = ["age", "day7_hours"]
CATEGORICAL = ["sex", "education", "cws_status", "occupation_major_group", "industry_division", "state", "sector"]


def build_conditional_features(values: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Predictors for salaried earnings; the earnings target is never a predictor."""
    result = pd.DataFrame(index=values.index)
    for column in NUMERIC:
        result[column] = pd.to_numeric(values[column], errors="coerce") if column in values else np.nan
    for column in CATEGORICAL:
        result[column] = values[column].astype("string").fillna("").replace("", "<MISSING>") if column in values else "<MISSING>"
    return result, list(NUMERIC), list(CATEGORICAL)


def _fold(identifier: str, folds: int) -> int:
    return int(hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:16], 16) % folds


def _fold_keys(base: pd.DataFrame) -> pd.Series:
    """Cross-fit by FSU so members of one household/FSU never train their own prediction."""
    if {"state", "sector", "fsu"}.issubset(base.columns):
        return base["state"].astype(str) + "|" + base["sector"].astype(str) + "|" + base["fsu"].astype(str)
    return base["source_observation_id"].astype(str)


def run_conditional_models(base: pd.DataFrame, parameters: Parameters) -> pd.DataFrame:
    output = base[["source_observation_id", "record_id", "release", "observation_type", "design_period", "visit", "month", "preprocessing_run_id"]].copy()
    output["method"] = "gradient_boosted_conditional_model"
    output["method_version"] = ML_METHOD_VERSION
    output["feature_spec_version"] = CONDITIONAL_FEATURE_SPEC_VERSION
    output["target"] = CONDITIONAL_TARGET
    target = pd.to_numeric(base["earnings_salaried"], errors="coerce")
    output["observed_value"] = target
    output["target_applicability"] = applicability_series(CONDITIONAL_TARGET, base["cws_status"].astype("string")).to_numpy()
    for column in ("predicted_value", "log_residual", "observed_to_estimate_ratio", "raw_model_score", "evidence_rank"):
        output[column] = np.nan
    output["training_fold"] = pd.NA
    output["assessability_status"] = "NOT_ASSESSABLE"
    output["assessability_reason"] = "TARGET_UNAVAILABLE_FOR_RELEASE_OBSERVATION"
    output["evidence_statement"] = ""
    output["source_reference_metadata"] = "applicable_positive_salaried_earners; release_observation_design_visit_month boundary; FSU-grouped two-fold cross-fit"

    first_visit = base["observation_type"].astype(str).eq("first_visit")
    ready = base["prepared_ready"].astype(bool) & first_visit
    applicable = output["target_applicability"].eq(APPLICABLE)
    finite = np.isfinite(target.to_numpy(dtype=float))
    positive = finite & target.gt(0).to_numpy()
    output.loc[base["prepared_ready"].astype(bool) & ~first_visit, "assessability_reason"] = "CONDITIONAL_TARGET_OR_CONTEXT_UNAVAILABLE_FOR_OBSERVATION"
    output.loc[ready & ~applicable, "assessability_reason"] = "TARGET_NOT_APPLICABLE_FOR_CWS_STATUS"
    output.loc[ready & applicable & ~finite, "assessability_reason"] = "TARGET_MISSING_OR_NON_NUMERIC"
    output.loc[ready & applicable & finite & ~positive, "assessability_reason"] = "APPLICABLE_ZERO_EARNINGS_NOT_MODELLED"
    eligible = ready & applicable & pd.Series(positive, index=base.index)
    if int(eligible.sum()) < max(parameters.minimum_model_population, parameters.conditional_folds * 2):
        output.loc[eligible, "assessability_reason"] = "INSUFFICIENT_RELEASE_BOUNDARY_REFERENCE_POPULATION"
        return output

    features, numeric, categorical = build_conditional_features(base)
    log_target = np.log(target.where(eligible))
    output["training_fold"] = _fold_keys(base).map(lambda value: _fold(value, parameters.conditional_folds))
    for fold in range(parameters.conditional_folds):
        prediction_mask = eligible & output["training_fold"].eq(fold)
        training_mask = eligible & ~output["training_fold"].eq(fold)
        if int(prediction_mask.sum()) == 0 or int(training_mask.sum()) < parameters.minimum_model_population:
            output.loc[prediction_mask, "assessability_reason"] = "INSUFFICIENT_OUT_OF_FOLD_REFERENCE_POPULATION"
            continue
        training_ids = base.loc[training_mask, "source_observation_id"].astype(str)
        if len(training_ids) > parameters.maximum_training_rows:
            ranks = training_ids.map(lambda value: int(hashlib.sha256(value.encode()).hexdigest()[:16], 16))
            training_index = ranks.sort_values(kind="mergesort").index[:parameters.maximum_training_rows]
        else:
            training_index = base.index[training_mask]
        encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1, encoded_missing_value=-1, dtype=np.float64)
        encoder.fit(features.loc[training_index, categorical])

        def matrix(index: pd.Index) -> np.ndarray:
            coded = encoder.transform(features.loc[index, categorical])
            coded[coded < 0] = np.nan  # unseen category -> treated as missing, never as a new category
            return np.hstack([features.loc[index, numeric].to_numpy(dtype=float), coded])

        categorical_mask = [False] * len(numeric) + [True] * len(categorical)
        model = HistGradientBoostingRegressor(
            max_iter=parameters.conditional_max_iterations, learning_rate=parameters.conditional_learning_rate,
            max_leaf_nodes=31, min_samples_leaf=20, l2_regularization=1.0, categorical_features=categorical_mask,
            early_stopping=True, validation_fraction=0.1, n_iter_no_change=20, random_state=RANDOM_SEED + fold,
        ).fit(matrix(training_index), log_target.loc[training_index].to_numpy(dtype=float))
        prediction_index = base.index[prediction_mask]
        predicted_log = model.predict(matrix(prediction_index))
        residual = log_target.loc[prediction_index].to_numpy(dtype=float) - predicted_log
        output.loc[prediction_index, "predicted_value"] = np.exp(predicted_log)
        output.loc[prediction_index, "log_residual"] = residual
        output.loc[prediction_index, "observed_to_estimate_ratio"] = np.exp(residual)
        output.loc[prediction_index, "raw_model_score"] = np.abs(residual)
        output.loc[prediction_index, "assessability_status"] = "ASSESSABLE"
        output.loc[prediction_index, "assessability_reason"] = pd.NA
        output.loc[prediction_index, "model_iterations"] = int(model.n_iter_)
        output.loc[prediction_index, "evidence_statement"] = "Reported salaried earnings differ from the model estimate for people with the same characteristics."
    assessed = output["assessability_status"].eq("ASSESSABLE")
    output.loc[assessed, "evidence_rank"] = output.loc[assessed, "raw_model_score"].rank(method="average", pct=True)
    return output
