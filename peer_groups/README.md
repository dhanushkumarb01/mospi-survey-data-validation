# PLFS peer-group engine

This package constructs comparable reference populations from one prepared
PLFS persons dataset.  It does not calculate anomaly scores, percentiles,
dispersion statistics, probability, ML output, or priorities.

The V1 specifications, source mappings, boundaries, and backoff rules are
documented in [DESIGN.md](DESIGN.md).  The input must be a
`prepared_persons.parquet` file created by the adjacent preprocessing run and
must retain its adjacent `run_metadata.json`.

Run from the project root:

```powershell
python -m peer_groups.cli --prepared-persons preprocessing\runs\2025_first_visit_final_2025_first\prepared_persons.parquet --output-root peer_groups\runs --run-id 2025_first_v1
```

`--minimum-group-size` defaults to 30 and is deliberately configurable.  Each
run writes immutable Parquet assignment/reference tables, a JSON and Markdown
report, and run metadata.  The assignment table includes every person-target
combination, including explicit `NOT_ASSESSABLE` rows.
