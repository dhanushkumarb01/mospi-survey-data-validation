from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from contextual.engine import ContextualEngine, ContextualFailure, RunConfig, conditional_surprisal
from peer_groups.engine import PeerGroupEngine, RunConfig as PeerRunConfig


def _row(index: int, occupation: object = "611", **updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "MoSPI_source_row": index + 2,
        "MoSPI_record_key": f"h-{index}",
        "MoSPI_release": "2024",
        "MoSPI_observation": "first_visit",
        "MoSPI_design_period": "pre_2025",
        "MoSPI_visit": "V1",
        "MoSPI_prepared_status": "ready_for_downstream_preparation_only",
        "MoSPI_state": "01",
        "MoSPI_sector": "1",
        "Person_Serial_No": "1",
        "CWS_Status_Code": "11",
        "General_Education_Level": "07",
        "Principal_Occupation_Code": occupation,
        "Principal_Industry_Code": "01124",
        "CWS_Earnings_Salaried": "100",
        "CWS_Earnings_SelfEmployed": "0",
        "Day7_Total_Hours": "8",
    }
    row.update(updates)
    return row


def _write_prepared(tmp_path: Path, rows: list[dict[str, object]], *, release: str = "2024", design_period: str = "pre_2025") -> Path:
    directory = tmp_path / "prepared"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "prepared_persons.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    (directory / "run_metadata.json").write_text(json.dumps({"run_id": "prepared-run", "release": release, "observation": "first_visit", "design_period": design_period}), encoding="utf-8")
    return path


def _peer(tmp_path: Path, prepared: Path, minimum: int = 3, run_id: str = "peer") -> Path:
    return PeerGroupEngine(PeerRunConfig(prepared, tmp_path / "peer", run_id=run_id, minimum_group_size=minimum)).run()


def _contextual(tmp_path: Path, prepared: Path, peer: Path, run_id: str = "context") -> Path:
    return ContextualEngine(RunConfig(prepared, peer, tmp_path / "context", run_id)).run()


def _evidence(destination: Path) -> pd.DataFrame:
    return pd.read_parquet(destination / "contextual_evidence.parquet")


def test_conditional_frequency_reference_count_surprisal_and_statement(tmp_path: Path) -> None:
    prepared = _write_prepared(tmp_path, [_row(0, "611"), _row(1, "611"), _row(2, "611"), _row(3, "522")])
    destination = _contextual(tmp_path, prepared, _peer(tmp_path, prepared))
    evidence = _evidence(destination)
    detail = evidence[evidence.observed_value.eq("611")]
    assert set(detail.contextual_assessability_status) == {"ASSESSABLE"}
    assert set(detail.reference_count) == {4}
    assert set(detail.category_count) == {3}
    assert set(detail.conditional_frequency) == {0.75}
    assert all(math.isclose(value, -math.log(.75)) for value in detail.surprisal)
    assert set(detail.category_parent_value) == {"6"}
    assert set(detail.category_parent_count) == {3}
    assert set(detail.frequency_statement) == {"This response occurs in 3 of 4 comparable observations with a valid three-digit occupation code."}


def test_zero_and_near_zero_surprisal_are_safe_and_unsmoothed() -> None:
    assert conditional_surprisal(0) is None
    assert conditional_surprisal(None) is None
    assert math.isclose(conditional_surprisal(1 / 30) or 0, math.log(30))


def test_sparse_reference_missing_context_and_blank_target_are_not_assessed(tmp_path: Path) -> None:
    prepared = _write_prepared(tmp_path, [_row(0, "611"), _row(1, "522"), _row(2, ""), _row(3, "")])
    sparse = _evidence(_contextual(tmp_path, prepared, _peer(tmp_path, prepared, run_id="sparse"), "sparse"))
    assert set(sparse.loc[sparse.observed_value.notna(), "contextual_assessability_reason"]) == {"INSUFFICIENT_REFERENCE_SIZE"}
    assert set(sparse.loc[sparse.observed_value_raw.isna(), "contextual_assessability_reason"]) == {"TARGET_MISSING_OR_NOT_APPLICABILITY_UNRESOLVED"}

    rows = [_row(index, "611") for index in range(3)] + [_row(3, "522", CWS_Status_Code="")]
    missing_context_prepared = _write_prepared(tmp_path / "missing", rows)
    missing_context = _evidence(_contextual(tmp_path / "missing", missing_context_prepared, _peer(tmp_path / "missing", missing_context_prepared), "missing"))
    assert missing_context.loc[missing_context.observed_value.eq("522"), "contextual_assessability_reason"].iloc[0] == "MISSING_CONTEXT"


def test_target_leakage_and_provenance_mismatch_are_rejected(tmp_path: Path) -> None:
    prepared = _write_prepared(tmp_path, [_row(i) for i in range(3)])
    peer = _peer(tmp_path, prepared)
    references_path = peer / "peer_group_references.parquet"
    references = pd.read_parquet(references_path)
    references.loc[:, "grouping_dimensions"] = '["Principal_Occupation_Code"]'
    references.to_parquet(references_path, index=False)
    with pytest.raises(ContextualFailure, match="leak"):
        _contextual(tmp_path, prepared, peer, "leak")

    clean_prepared = _write_prepared(tmp_path / "provenance", [_row(i) for i in range(3)])
    clean_peer = _peer(tmp_path / "provenance", clean_prepared)
    metadata_path = clean_prepared.parent / "run_metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["run_id"] = "different-run"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ContextualFailure, match="not built"):
        _contextual(tmp_path / "provenance", clean_prepared, clean_peer, "bad-provenance")


def test_month_and_visit_boundaries_are_preserved_and_execution_is_deterministic(tmp_path: Path) -> None:
    rows: list[dict[str, object]] = []
    for month in ("1", "2"):
        for visit in ("V1", "V2"):
            for number in range(3):
                rows.append({
                    "MoSPI_source_row": len(rows) + 2, "MoSPI_record_key": f"{month}-{visit}-{number}",
                    "MoSPI_release": "2025", "MoSPI_observation": "first_visit", "MoSPI_design_period": "post_2025",
                    "MoSPI_visit": visit, "MoSPI_month": month, "MoSPI_prepared_status": "ready_for_downstream_preparation_only",
                    "MoSPI_state": "01", "MoSPI_sector": "1", "srl": "1", "acws": "11", "gedu_lvl": "07",
                    "ocu_pas": "611", "ind_pas": "01124", "ern_reg": "100", "ern_self": "0", "hr7": "8",
                })
    prepared = _write_prepared(tmp_path, rows, release="2025", design_period="post_2025")
    peer = _peer(tmp_path, prepared)
    first = _evidence(_contextual(tmp_path, prepared, peer, "one"))
    second = _evidence(_contextual(tmp_path, prepared, peer, "two"))
    assert first.groupby(["month", "visit"]).peer_group_id.first().nunique() == 4
    compare = ["source_observation_id", "month", "visit", "peer_group_id", "context_values", "reference_count", "category_count", "conditional_frequency", "surprisal", "contextual_assessability_status"]
    pd.testing.assert_frame_equal(first[compare], second[compare])


def test_output_uses_response_frequency_language_not_error_probability(tmp_path: Path) -> None:
    prepared = _write_prepared(tmp_path, [_row(i) for i in range(3)])
    destination = _contextual(tmp_path, prepared, _peer(tmp_path, prepared))
    text = (destination / "contextual_report.md").read_text(encoding="utf-8").lower()
    assert "probability of error" not in text
    assert "chance of error" not in text
    assert "conditional frequency" in text
