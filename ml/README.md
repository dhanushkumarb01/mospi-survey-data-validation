# PLFS ML evidence layer

This package generates four separate, traceable ML evidence tables from one prepared person run and its matching peer-group run. It produces anomaly evidence only—not error probabilities, labels, corrections, or fused scores.

Run from the project root:

```powershell
python -m ml.cli `
  --prepared-persons preprocessing/runs/2024_first_visit_final_2024_first/prepared_persons.parquet `
  --peer-group-run peer_groups/runs/2024_first_visit_2024_first_v1 `
  --output-root ml/runs --run-id 2024_first_v1
```

Each immutable run writes:

- `isolation_forest_evidence.parquet`
- `lof_evidence.parquet`
- `conditional_model_evidence.parquet`
- `similarity_evidence.parquet`
- `ml_report.json`, `ml_report.md`, and `run_metadata.json`

Run all regression and ML tests with:

```powershell
python -m pytest -q preprocessing/tests peer_groups/tests statistical/tests contextual/tests ml/tests
```

Real-data runs must use the exact matching preprocessing and peer-group run. The engine rejects mismatched release, observation, design period, preprocessing run ID, missing source mappings, or invalid day-7 peer assignments.
