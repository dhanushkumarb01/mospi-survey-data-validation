from __future__ import annotations

from ml.config import Parameters
from ml.similarity import response_signature, run_similarity
from .test_isolation_forest import _base


def test_signature_excludes_identifiers_and_blocking_prevents_cross_fsu_match() -> None:
    base = _base(3)
    signature_columns = ["age", "sex", "education", "cws_status", "occupation", "industry", "day7_hours", "earnings_salaried", "earnings_self_employed"]
    base.loc[1:, signature_columns] = base.loc[0, signature_columns].to_numpy()
    base.loc[1, ["source_observation_id", "record_id"]] = ["different", "different-household"]
    base.loc[2, "fsu"] = "different-fsu"
    signature, _ = response_signature(base, 6)
    assert signature.iloc[0] == signature.iloc[1] == signature.iloc[2]
    evidence = run_similarity(base, Parameters(similarity_minimum_present_fields=6))
    assert evidence.loc[0, "matched_source_observation_id"] == "different"
    assert evidence.loc[2, "matched_source_observation_id"] is None or str(evidence.loc[2, "matched_source_observation_id"]) == "<NA>"
    assert "Repeated/highly similar response pattern requiring verification." in set(evidence.evidence_statement)


def test_insufficient_signature_is_not_assessable() -> None:
    base = _base(2)
    base.loc[:, ["education", "occupation", "industry", "day7_hours", "earnings_salaried", "earnings_self_employed"]] = ""
    evidence = run_similarity(base, Parameters(similarity_minimum_present_fields=6))
    assert set(evidence.assessability_reason) == {"INSUFFICIENT_RESPONSE_FIELDS_FOR_SIGNATURE"}
