"""Conservative, blocked exact response-pattern evidence."""
from __future__ import annotations

import pandas as pd

from .config import ML_METHOD_VERSION, Parameters, SIMILARITY_FEATURE_SPEC_VERSION


SIGNATURE_COLUMNS = ("age", "sex", "education", "cws_status", "occupation", "industry", "day7_hours", "earnings_salaried", "earnings_self_employed")


def response_signature(values: pd.DataFrame, minimum_present: int) -> tuple[pd.Series, pd.Series]:
    """Hash non-identifying values only; insufficient rows receive no signature."""
    clean = values.loc[:, SIGNATURE_COLUMNS].astype("string").fillna("").apply(lambda col: col.str.strip())
    present = clean.ne("").sum(axis=1)
    material = clean.mask(clean.eq(""), "<MISSING>")
    # Pandas hashes rows column-by-column in C rather than constructing one
    # Python/JSON object per person. This is deterministic for the versioned
    # ordered field list and makes exact-pattern blocking feasible at PLFS
    # scale. Match grouping still uses all signature fields' fixed order.
    signature = pd.util.hash_pandas_object(material, index=False, categorize=False).map(lambda value: f"{value:016x}").astype("string")
    return signature.mask(present.lt(minimum_present)), present.astype("Int64")


def run_similarity(base: pd.DataFrame, parameters: Parameters) -> pd.DataFrame:
    output = base[["source_observation_id", "record_id", "release", "observation_type", "design_period", "visit", "month", "preprocessing_run_id"]].copy()
    output["method"] = "blocked_exact_response_pattern"
    output["method_version"] = ML_METHOD_VERSION
    output["feature_spec_version"] = SIMILARITY_FEATURE_SPEC_VERSION
    output["peer_group_id"] = pd.NA
    output["assessability_status"] = "NOT_ASSESSABLE"
    output["assessability_reason"] = "PREPARED_RECORD_NOT_READY"
    output["signature_hash"] = pd.NA
    output["signature_present_field_count"] = pd.NA
    output["matched_source_observation_id"] = pd.NA
    output["match_count"] = 0
    output["raw_model_score"] = pd.NA
    output["evidence_rank"] = pd.NA
    output["evidence_statement"] = ""
    output["blocking_specification"] = "release, observation, design_period, visit, month, state, sector, FSU; signature excludes all identifiers"
    output["source_reference_metadata"] = "exact_signature_only; high_similarity_not_implemented"
    signature, present = response_signature(base, parameters.similarity_minimum_present_fields)
    output["signature_hash"] = signature
    output["signature_present_field_count"] = present
    ready = base["prepared_ready"] & signature.notna()
    output.loc[base["prepared_ready"] & signature.isna(), "assessability_reason"] = "INSUFFICIENT_RESPONSE_FIELDS_FOR_SIGNATURE"
    output.loc[ready, "assessability_status"] = "ASSESSABLE"
    output.loc[ready, "assessability_reason"] = pd.NA
    blocks = base[["release", "observation_type", "design_period", "visit", "month", "state", "sector", "fsu"]].astype("string").fillna("")
    block_key = blocks.agg("|".join, axis=1)
    work = pd.DataFrame({"index": base.index, "block": block_key, "signature": signature, "source": base["source_observation_id"]})
    work = work.loc[ready].sort_values(["block", "signature", "source"], kind="mergesort")
    for _, group in work.groupby(["block", "signature"], sort=False, dropna=False):
        if len(group) < 2:
            continue
        indexes = group["index"].to_numpy()
        sources = group["source"].astype(str).tolist()
        for position, index in enumerate(indexes):
            output.loc[index, "matched_source_observation_id"] = sources[1] if position == 0 else sources[0]
            output.loc[index, "match_count"] = len(group) - 1
            output.loc[index, "raw_model_score"] = len(group) - 1
            output.loc[index, "evidence_statement"] = "Repeated/highly similar response pattern requiring verification."
    return output
