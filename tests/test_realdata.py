"""Smoke tests against the stored PLFS runs (plan W0.1).  Opt-in: python -m pytest -m realdata --realdata"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PREPARED = sorted((ROOT / "preprocessing" / "runs").glob("*_final_*/prepared_persons.parquet"))
FUSION_RUNS = sorted(p.parent for p in (ROOT / "fusion" / "runs").glob("*/fused_cases.parquet"))
pytestmark = [pytest.mark.realdata, pytest.mark.skipif(not PREPARED, reason="stored PLFS runs are not present")]


@pytest.mark.parametrize("prepared", PREPARED, ids=lambda p: p.parent.name)
def test_every_loader_reads_stored_legacy_and_current_schemas(prepared):
    from historical.engine import load_release
    from survey_rules.schema import read_parquet, schema_version
    frame = read_parquet(prepared, columns=["MoSPI_record_key", "MoSPI_state", "MoSPI_sector", "MoSPI_prepared_status"])
    assert frame["MoSPI_state"].astype(str).str.strip().ne("").mean() > 0.95
    assert schema_version(prepared) in {"iospi-prepared-1", "mospi-prepared-2"}
    if "revisit" in prepared.parent.name:
        return
    history, _ = load_release(prepared)
    for column in ("state", "sector"):
        assert history[column].ne("").mean() > 0.95, column
    assert history["period_index"].notna().mean() > 0.95 and history["ready"].mean() > 0.95


@pytest.mark.parametrize("run", FUSION_RUNS, ids=lambda p: p.name)
def test_case_page_returns_person_facts_on_stored_fusion_runs(run):
    from fastapi.testclient import TestClient
    import duckdb
    from fusion.api import create_app
    client = TestClient(create_app(ROOT / "fusion" / "runs", project_root=ROOT))
    with duckdb.connect() as connection:
        ids = [r[0] for r in connection.execute("SELECT case_id FROM read_parquet(?) USING SAMPLE 200 ROWS", [str(run / "fused_cases.parquet")]).fetchall()]
    for case_id in random.Random(0).sample(ids, min(10, len(ids))):
        response = client.get(f"/api/cases/{case_id}", params={"run": run.name})
        assert response.status_code == 200, response.text[:300]
        story = response.json()["story"]
        assert story["record"]["title"]
        if not str(case_id).endswith("household"):
            assert story["record"]["person"] or story.get("method") == "lanes"
