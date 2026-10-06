import pandas as pd
import json

from fusion.config import FusionParameters
from fusion.engine import FusionEngine, FusionFailure, RunConfig
from fusion.evidence_card import build_evidence_card
from fusion.fusion import combine_risk
from fusion.influence import calculate_influence


def test_available_sources_are_reweighted_and_missing_is_not_zero():
    risk, overridden = combine_risk({"statistical": .8, "contextual": None, "ml": .4, "historical": None}, {"statistical": .3, "contextual": .2, "ml": .3, "historical": .2}, .995)
    assert risk == .6 and not overridden


def test_extreme_source_override_and_no_evidence():
    risk, overridden = combine_risk({"statistical": .997, "contextual": .1, "ml": .1, "historical": None}, {"statistical": .3, "contextual": .2, "ml": .3, "historical": .2}, .995)
    assert risk == .997 and overridden
    assert combine_risk({"statistical": None}, {"statistical": 1}, .995) == (None, False)


def _shares(rows):
    from fusion.influence import domain_shares
    return domain_shares(pd.DataFrame(rows, columns=["source_observation_id", "target_variable", "observed_value", "peer_median", "final_weight", "domain", "applicable"]))


def test_influence_keeps_missing_and_zero_distinct():
    shares = _shares([
        ("a", "cws_earnings_salaried", 100.0, 100.0, 2.0, "d", True),   # equals its peer median: zero, not missing
        ("b", "cws_earnings_salaried", 300.0, 100.0, 3.0, "d", True),
        ("c", "cws_earnings_salaried", 200.0, None, None, "d", True),    # no weight / no anticipated value
    ])
    output = calculate_influence(pd.DataFrame({"source_observation_id": ["a", "b", "c"], "final_weight": [2.0, 3.0, None]}), shares)
    assert output.influence_status.tolist() == ["ASSESSABLE", "ASSESSABLE", "NOT_ASSESSABLE"]
    assert output.influence_score.iloc[0] == 0.0 and output.influence_score.iloc[1] > 0
    assert pd.isna(output.influence_score.iloc[2])


def test_influence_is_unit_free_and_never_mixes_rupees_with_hours():
    """Audit H2: V1 took max |deviation| across rupees and hours. V2 shares do not depend on the unit."""
    rows = [("a", "cws_earnings_salaried", 30000.0, 15000.0, 1.0, "d", True), ("b", "cws_earnings_salaried", 15000.0, 15000.0, 1.0, "d", True),
            ("a", "day7_total_hours", 8.0, 8.0, 1.0, "d", True), ("b", "day7_total_hours", 16.0, 8.0, 1.0, "d", True)]
    rupees = _shares(rows).set_index(["source_observation_id", "target_variable"]).local_score
    paise = _shares([(i, t, y * (100 if t.startswith("cws") else 1), m * (100 if t.startswith("cws") else 1), w, d, a) for i, t, y, m, w, d, a in rows]
                    ).set_index(["source_observation_id", "target_variable"]).local_score
    assert rupees.equals(paise)
    assert rupees[("a", "cws_earnings_salaried")] == rupees[("b", "day7_total_hours")] == 15000 / 45000


def test_placeholders_do_not_enter_domain_totals():
    shares = _shares([("a", "cws_earnings_salaried", 100.0, 50.0, 1.0, "d", True), ("z", "cws_earnings_salaried", 0.0, None, 99.0, "d", False)])
    assert shares.domain_total.dropna().iloc[0] == 100.0


def _cases(**overrides):
    base = {"source_observation_id": ["r1", "r2", "r3", "r4"], "statistical_raw_score": [.1, .2, .3, .4], "statistical_status": "ASSESSABLE",
            "contextual_raw_score": [.1, .2, .3, .4], "contextual_status": "ASSESSABLE", "ml_raw_score": [.1, .2, .3, .4], "ml_status": "ASSESSABLE",
            "historical_raw_score": [None] * 4, "historical_status": "NOT_ASSESSABLE", "influence_score": [.5, .5, .5, .5], "rule_error_count": [0, 0, 0, 0]}
    base.update(overrides)
    return pd.DataFrame(base)


def test_fsu_evidence_never_changes_record_risk_or_override():
    """Audit H3: 1,974 records reached top risk through their FSU alone in V1."""
    engine = FusionEngine(RunConfig("p", "s", "c", "m", "o"))
    plain = engine.fuse(_cases())
    with_group = engine.fuse(_cases(pattern_raw_score=[1.0, 1.0, 1.0, 1.0], pattern_status="ASSESSABLE"))
    assert plain.risk_score.tolist() == with_group.risk_score.tolist()
    assert not with_group.override_applied.any()


def test_documented_rule_breach_is_reviewed_first():
    fused = FusionEngine(RunConfig("p", "s", "c", "m", "o")).fuse(_cases(rule_error_count=[0, 1, 0, 0]))
    assert fused.loc[1, "priority_score"] == 1.0 and fused.loc[1, "priority_band"] == "CRITICAL"


def test_parameters_reject_invalid_weight_contract():
    try:
        FusionParameters(source_weights={"statistical": 1})
    except ValueError:
        return
    raise AssertionError("Expected source weight validation failure")


def test_incompatible_preprocessing_provenance_is_rejected(tmp_path):
    prepared = tmp_path / "prepared_persons.parquet"; prepared.touch()
    (tmp_path / "run_metadata.json").write_text(json.dumps({"run_id":"prep_a","release":"2024","observation":"first_visit","design_period":"pre_2025"}))
    runs = []
    for name in ("stat", "context", "ml"):
        directory = tmp_path / name; directory.mkdir(); runs.append(directory)
        (directory / "run_metadata.json").write_text(json.dumps({"run_id":name,"release":"2024","observation":"first_visit","design_period":"pre_2025","input_preprocessing_run_id":"wrong_prep"}))
    engine = FusionEngine(RunConfig(prepared, runs[0], runs[1], runs[2], tmp_path / "out"))
    try:
        engine._validate()
    except FusionFailure as error:
        assert "incompatible runs" in str(error)
        return
    raise AssertionError("Expected strict provenance failure")


def test_evidence_card_uses_fixed_stored_values_and_disclaimer():
    row = pd.Series({"case_id":"case_1","source_observation_id":"source_1","release":"2024","observation_type":"first_visit","design_period":"pre_2025","visit":"V1","month":"","state":"01","sector":"1","stratum":"01","fsu":"100","priority_score":.4,"priority_rank":.8,"priority_band":"MEDIUM","risk_score":.5,"influence_score":.8,"override_applied":False,"statistical_status":"ASSESSABLE","statistical_rank":.9,"statistical_statement":"Stored statistic.","contextual_status":"NOT_ASSESSABLE","contextual_rank":None,"contextual_statement":"Unavailable.","ml_status":"ASSESSABLE","ml_rank":.7,"ml_statement":"Stored ML statement.","pattern_status":"NOT_AVAILABLE","pattern_rank":None,"pattern_statement":"Not supplied.","provenance_json":"{}"})
    card = build_evidence_card(row)
    assert card["evidence"][0]["statement"] == "Stored statistic."
    assert "not a determination" in card["disclaimer"]
