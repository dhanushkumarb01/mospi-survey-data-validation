"""Peer-scoped Local Outlier Factor evidence using issued peer assignments.

LOF compares a point's local reachability density with its neighbours'.  It
is undefined when a neighbourhood is made of identical points: their
k-distance is 0, their density is infinite, and any nearby point receives an
arbitrarily large score (the audit found 14,087 scores above 10^6).  PLFS
answers are heavily discrete (whole hours, rounded earnings), so identical
vectors are common and legitimate.

V1.1 therefore fits each peer group on its *distinct* feature vectors.  Every
fitted point then has a positive k-distance and the factor stays a finite
density ratio (≈1 for ordinary points).  A group with too few distinct
vectors to define a neighbourhood is NOT_ASSESSABLE rather than scored.
Identical answers are never in themselves treated as unusual.

``evidence_rank`` is the empirical percentile of the factor among all
assessable records of the run, so a group does not automatically contribute
its own "top 5%" regardless of how ordinary its members are.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import RobustScaler

from .config import LOF_FEATURE_SPEC_VERSION, LOF_REFERENCE_TARGET, ML_METHOD_VERSION, Parameters


def build_lof_features(values: pd.DataFrame) -> pd.DataFrame:
    """Small numeric feature space; no identifiers, weights, or encoding order."""
    result = pd.DataFrame(index=values.index)
    result["age"] = pd.to_numeric(values["age"], errors="coerce")
    result["day7_hours"] = pd.to_numeric(values["day7_hours"], errors="coerce")
    result["earnings_salaried_log1p"] = np.log1p(pd.to_numeric(values["earnings_salaried"], errors="coerce").clip(lower=0))
    result["earnings_self_employed_log1p"] = np.log1p(pd.to_numeric(values["earnings_self_employed"], errors="coerce").clip(lower=0))
    return result


def _sample_group(index: pd.Index, identifiers: pd.Series, maximum: int) -> pd.Index:
    if len(index) <= maximum:
        return index
    ranks = identifiers.loc[index].astype(str).map(lambda text: int(hashlib.sha256(text.encode()).hexdigest()[:16], 16))
    return ranks.sort_values(kind="mergesort").index[:maximum]


def run_peer_lof(base: pd.DataFrame, assignments: pd.DataFrame, parameters: Parameters) -> pd.DataFrame:
    peer = assignments[["source_observation_id", "peer_group_id", "peer_group_size", "assessability_status", "not_assessable_reason", "reference_run_id", "specification_version"]].rename(
        columns={"assessability_status": "peer_assessability_status", "not_assessable_reason": "peer_not_assessable_reason"}
    )
    output = base[["source_observation_id", "record_id", "release", "observation_type", "design_period", "visit", "month", "preprocessing_run_id"]].merge(
        peer, on="source_observation_id", how="left", validate="one_to_one",
    )
    output["method"] = "peer_scoped_lof"
    output["method_version"] = ML_METHOD_VERSION
    output["feature_spec_version"] = LOF_FEATURE_SPEC_VERSION
    output["peer_reference_target"] = LOF_REFERENCE_TARGET
    output["assessability_status"] = "NOT_ASSESSABLE"
    output["assessability_reason"] = "TARGET_UNAVAILABLE_FOR_RELEASE_OBSERVATION"
    output["raw_model_score"] = np.nan
    output["evidence_rank"] = np.nan
    output["lof_distinct_reference_points"] = pd.array([pd.NA] * len(output), dtype="Int64")
    output["evidence_statement"] = ""
    output["source_reference_metadata"] = "existing_peer_groups; fitted on distinct feature vectors"
    if assignments.empty:
        output["lof_reference_population_size"] = pd.array([pd.NA] * len(output), dtype="Int64")
        return output.drop(columns=["peer_assessability_status", "peer_not_assessable_reason"])
    peer_ready = output["peer_assessability_status"].eq("ASSESSABLE") & output["peer_group_id"].notna()
    output.loc[output["peer_assessability_status"].notna() & ~peer_ready, "assessability_reason"] = "PEER_" + output["peer_not_assessable_reason"].fillna("NOT_ASSESSABLE").astype(str)
    features = build_lof_features(base).set_index(base["source_observation_id"])
    valid = np.isfinite(features.to_numpy(dtype=float)).all(axis=1)
    feature_valid = pd.Series(valid, index=base["source_observation_id"])
    output["_valid"] = output["source_observation_id"].map(feature_valid).fillna(False).astype(bool)
    output.loc[peer_ready & ~output["_valid"], "assessability_reason"] = "MISSING_OR_NON_NUMERIC_LOF_FEATURE"
    eligible = output.loc[peer_ready & output["_valid"]].copy()
    for _, rows in eligible.groupby("peer_group_id", sort=True):
        population = rows.index
        if len(rows) < parameters.lof_minimum_population:
            output.loc[population, "assessability_reason"] = "INSUFFICIENT_VALID_PEER_FEATURE_POPULATION"
            continue
        train_index = _sample_group(population, output["source_observation_id"], parameters.lof_maximum_reference_rows)
        matrix = features.reindex(output.loc[population, "source_observation_id"]).to_numpy(dtype=float)
        train_positions = pd.Index(population).get_indexer(train_index)
        scaler = RobustScaler().fit(matrix[train_positions])
        scaled = scaler.transform(matrix)
        distinct = np.unique(scaled[train_positions], axis=0)
        output.loc[population, "lof_distinct_reference_points"] = len(distinct)
        # k stays fixed: with k close to the number of distinct points every
        # neighbourhood is "everyone" and the factor cannot discriminate.
        if len(distinct) <= max(parameters.lof_minimum_distinct_points, parameters.lof_neighbors):
            output.loc[population, "assessability_reason"] = "INSUFFICIENT_DISTINCT_PEER_VALUES"
            continue
        neighbours = parameters.lof_neighbors
        model = LocalOutlierFactor(n_neighbors=neighbours, novelty=True, n_jobs=1).fit(distinct)
        scores = -model.score_samples(scaled)
        if not np.isfinite(scores).all():
            output.loc[population, "assessability_reason"] = "LOF_NOT_FINITE"
            continue
        output.loc[population, "raw_model_score"] = scores
        output.loc[population, "assessability_status"] = "ASSESSABLE"
        output.loc[population, "assessability_reason"] = pd.NA
        output.loc[population, "evidence_statement"] = "Local unusualness within the comparable peer population."
    assessed = output["assessability_status"].eq("ASSESSABLE")
    output.loc[assessed, "evidence_rank"] = output.loc[assessed, "raw_model_score"].rank(method="average", pct=True)
    output["lof_reference_population_size"] = output["peer_group_id"].map(eligible.groupby("peer_group_id").size()).astype("Int64")
    output.drop(columns=["peer_assessability_status", "peer_not_assessable_reason", "_valid"], inplace=True)
    return output
