# Pattern V1

This package generates independent FSU/group/temporal Pattern evidence from one prepared PLFS person delivery. It identifies unusual aggregate patterns for review; it does not find errors, fabricate an enumerator identity, correct data, or produce a fused risk score.

Run from the repository root:

```powershell
python -m pattern.cli --prepared-persons preprocessing/runs/2024_first_visit_final_2024_first/prepared_persons.parquet --output-root pattern/runs --run-id 2024_first_v1
```

For the only supplied validated panel route, pass the existing linked statistical run and revisit preparation input when processing the 2023–24 first-visit delivery:

```powershell
python -m pattern.cli --prepared-persons preprocessing/runs/2023_24_first_visit_final_2023_24_first/prepared_persons.parquet --output-root pattern/runs --run-id 2023_24_first_v1 --revisit-prepared-persons preprocessing/runs/2023_24_revisit_final_2023_24_revisit/prepared_persons.parquet --revisit-statistical-run statistical/runs/2023_24_first_visit_post_fix_validation_20260924_2023_24_first_with_revisit
```

Output files are `fsu_distribution_shift.parquet`, `concentration_evidence.parquet`, `heaping_evidence.parquet`, `temporal_drift.parquet`, `revisit_pattern_evidence.parquet`, combined `pattern_evidence.parquet`, a JSON/Markdown report, and metadata. Defaults and methodological limits are in [DESIGN.md](DESIGN.md).

The configurable CLI minimum settings are V1 research operating settings—not official PLFS thresholds or error probabilities.
