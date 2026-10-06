from __future__ import annotations

import json

import pandas as pd

from ml.config import Parameters
from ml.engine import MLEngine, MLFailure, RunConfig


def _prepared_rows(count: int = 40) -> list[dict[str, object]]:
    return [{
        "MoSPI_source_row": i + 2, "MoSPI_record_key": f"q|1|h{i}", "MoSPI_release": "2024", "MoSPI_observation": "first_visit", "MoSPI_design_period": "pre_2025", "MoSPI_visit": "V1", "MoSPI_state": "01", "MoSPI_sector": "1", "MoSPI_fsu": "100", "MoSPI_prepared_status": "ready_for_downstream_preparation_only",
        "Person_Serial_No": "1", "Age": str(20 + i % 30), "Sex": "1", "General_Education_Level": "07", "CWS_Status_Code": "11", "Principal_Occupation_Code": "522", "Principal_Industry_Code": "4711", "Day7_Total_Hours": str(7 + i % 3), "CWS_Earnings_Salaried": str(100 + i), "CWS_Earnings_SelfEmployed": "0",
    } for i in range(count)]


def _write_contract(tmp_path):
    prepared_dir = tmp_path / "prepared"; prepared_dir.mkdir()
    prepared = prepared_dir / "prepared_persons.parquet"; pd.DataFrame(_prepared_rows()).to_parquet(prepared, index=False)
    metadata = {"run_id": "prepared-run", "release": "2024", "observation": "first_visit", "design_period": "pre_2025"}
    (prepared_dir / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    peer = tmp_path / "peer"; peer.mkdir()
    source_ids = [f"q|1|h{i}|person=1" for i in range(40)]
    assignments = pd.DataFrame({"source_observation_id": source_ids, "target_variable": "day7_total_hours", "peer_group_id": "pg-one", "peer_group_size": 40, "assessability_status": "ASSESSABLE", "not_assessable_reason": pd.NA, "reference_run_id": "prepared-run", "specification_version": "plfs-peer-groups-v1.0", "release": "2024", "observation": "first_visit", "design_period": "pre_2025", "visit": "V1", "month": ""})
    assignments.to_parquet(peer / "peer_group_assignments.parquet", index=False)
    assignments.iloc[:1].to_parquet(peer / "peer_group_references.parquet", index=False)
    (peer / "run_metadata.json").write_text(json.dumps({**metadata, "run_id": "peer-run", "input_preprocessing_run_id": "prepared-run", "specification_version": "plfs-peer-groups-v1.0"}), encoding="utf-8")
    return prepared, peer


def test_engine_preserves_provenance_and_is_reproducible(tmp_path) -> None:
    prepared, peer = _write_contract(tmp_path)
    parameters = Parameters(minimum_model_population=10, maximum_training_rows=20, isolation_trees=10, isolation_max_samples=10, lof_minimum_population=10, lof_neighbors=5, conditional_max_iterations=8)
    first = MLEngine(RunConfig(prepared, peer, tmp_path / "runs", "one", parameters)).run()
    second = MLEngine(RunConfig(prepared, peer, tmp_path / "runs", "two", parameters)).run()
    for file in ("isolation_forest_evidence.parquet", "lof_evidence.parquet", "conditional_model_evidence.parquet", "similarity_evidence.parquet"):
        left, right = pd.read_parquet(first / file), pd.read_parquet(second / file)
        pd.testing.assert_frame_equal(left.drop(columns=[c for c in left if c == "training_fold"], errors="ignore"), right.drop(columns=[c for c in right if c == "training_fold"], errors="ignore"))
        assert set(left.release) == {"2024"}
        assert set(left.preprocessing_run_id) == {"prepared-run"}


def test_engine_rejects_peer_provenance_mismatch(tmp_path) -> None:
    prepared, peer = _write_contract(tmp_path)
    metadata_path = peer / "run_metadata.json"; metadata = json.loads(metadata_path.read_text()); metadata["input_preprocessing_run_id"] = "wrong"; metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    try:
        MLEngine(RunConfig(prepared, peer, tmp_path / "runs")).run()
    except MLFailure as error:
        assert "built from" in str(error)
    else:
        raise AssertionError("Expected provenance rejection")
