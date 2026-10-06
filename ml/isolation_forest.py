"""Deterministic, release-bounded Isolation Forest evidence."""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from survey_rules import APPLICABLE, applicability_series

from .config import IF_FEATURE_SPEC_VERSION, ML_METHOD_VERSION, Parameters, RANDOM_SEED


def stable_sample_mask(ids: pd.Series, maximum: int) -> pd.Series:
    """Select a stable, input-order-independent reference subset."""
    if len(ids) <= maximum:
        return pd.Series(True, index=ids.index)
    ranks = ids.astype(str).map(lambda value: int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:16], 16))
    return ranks.rank(method="first").le(maximum)


def build_if_features(values: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Return V1 features; callers have already excluded identifiers/weights.

    Age is binned to avoid treating known PLFS age heaping as a raw continuous
    anomaly. NIC/NCO are coarsened before one-hot encoding.
    """
    result = pd.DataFrame(index=values.index)
    age = pd.to_numeric(values["age"], errors="coerce")
    result["age_band_5_year"] = np.floor(age / 5).clip(0, 23).astype("Float64")
    targets = {"day7_hours": "day7_total_hours", "earnings_salaried": "cws_earnings_salaried", "earnings_self_employed": "cws_earnings_self_employed"}
    status = values["cws_status"].astype("string") if "cws_status" in values else pd.Series("", index=values.index, dtype="string")
    for column, target in targets.items():
        numeric = pd.to_numeric(values[column], errors="coerce")
        # A questionnaire placeholder (item not asked for this activity status)
        # is missing information, not a reported 0 (survey_rules.plfs).
        numeric = numeric.where(applicability_series(target, status).eq(APPLICABLE).to_numpy())
        result[column] = np.log1p(numeric.clip(lower=0)).astype("Float64")
    for column in ("sex", "education", "cws_status", "occupation_major_group", "industry_division"):
        result[column] = values[column].astype("string").fillna("").replace("", "<MISSING>")
    numerical = ["age_band_5_year", "day7_hours", "earnings_salaried", "earnings_self_employed"]
    categorical = ["sex", "education", "cws_status", "occupation_major_group", "industry_division"]
    return result, numerical, categorical


def run_isolation_forest(base: pd.DataFrame, parameters: Parameters) -> pd.DataFrame:
    """Score one already provenance-homogeneous release/observation input."""
    output = base[["source_observation_id", "record_id", "release", "observation_type", "design_period", "visit", "month", "preprocessing_run_id"]].copy()
    output["method"] = "isolation_forest"
    output["method_version"] = ML_METHOD_VERSION
    output["feature_spec_version"] = IF_FEATURE_SPEC_VERSION
    output["peer_group_id"] = pd.NA
    output["assessability_status"] = "NOT_ASSESSABLE"
    output["assessability_reason"] = "PREPARED_RECORD_NOT_READY"
    output["raw_model_score"] = np.nan
    output["evidence_rank"] = np.nan
    output["evidence_statement"] = ""
    output["source_reference_metadata"] = "release_bounded_unsupervised_population"
    features, numerical, categorical = build_if_features(base)
    # Revisit records legitimately lack day-7 hours. Do not turn a wholly
    # unavailable field into a constant median-imputed pseudo-feature.
    numerical = [column for column in numerical if features[column].notna().any()]
    output["effective_feature_columns"] = ",".join([*numerical, *categorical])
    ready = base["prepared_ready"] & pd.to_numeric(base["age"], errors="coerce").notna() & base["cws_status"].ne("")
    output.loc[base["prepared_ready"] & ~ready, "assessability_reason"] = "MISSING_REQUIRED_ML_FEATURE"
    if int(ready.sum()) < parameters.minimum_model_population:
        output.loc[ready, "assessability_reason"] = "INSUFFICIENT_RELEASE_BOUNDARY_REFERENCE_POPULATION"
        return output
    reference = stable_sample_mask(base.loc[ready, "source_observation_id"], parameters.isolation_max_training_rows)
    reference_index = reference.index[reference]
    transformer = ColumnTransformer([
        ("numeric", Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=True))]), numerical),
        ("categorical", Pipeline([("impute", SimpleImputer(strategy="most_frequent")), ("one_hot", OneHotEncoder(handle_unknown="ignore", min_frequency=2, sparse_output=False, dtype=np.float32))]), categorical),
    ], sparse_threshold=0)
    matrix = transformer.fit_transform(features.loc[reference_index])
    model = IsolationForest(
        n_estimators=parameters.isolation_trees,
        max_samples=min(parameters.isolation_max_samples, len(reference_index)),
        random_state=RANDOM_SEED,
        n_jobs=1,
        contamination="auto",
    ).fit(matrix)
    assessed_index = base.index[ready]
    # Batch scoring avoids a dense full-file materialisation on the 2025 run.
    scores: list[pd.Series] = []
    for indexes in np.array_split(assessed_index.to_numpy(), max(1, int(np.ceil(len(assessed_index) / 100_000)))):
        if len(indexes):
            scores.append(pd.Series(-model.score_samples(transformer.transform(features.loc[indexes])), index=indexes))
    score = pd.concat(scores).sort_index() if scores else pd.Series(dtype=float)
    output.loc[score.index, "raw_model_score"] = score
    output.loc[score.index, "evidence_rank"] = score.rank(method="average", pct=True)
    output.loc[score.index, "assessability_status"] = "ASSESSABLE"
    output.loc[score.index, "assessability_reason"] = pd.NA
    output.loc[score.index, "evidence_statement"] = "Unusual multivariate response pattern."
    return output
