# PLFS preparation layer

This package performs deterministic preparation of the supplied PLFS CSV
deliveries. It is deliberately not a validation/intelligence layer: it does
not score anomalies, infer errors, impute, correct values, or drop records.

Run one documented delivery from the project root, for example:

```powershell
python -m preprocessing.cli --input-root . --output-root preprocessing\runs --contract 2025_first
```

Available contracts are `2023_24_first`, `2023_24_revisit`, `2024_first`, and
`2025_first`. Each creates a new run directory containing:

- `prepared_households.parquet` and `prepared_persons.parquet`, retaining every
  raw column and adding `MoSPI_*` provenance, standardisation, key, design, and
  linkage-status columns;
- `preprocessing_report.json` and `.md`;
- `issue_log.csv`;
- `run_metadata.json`;
- missingness and standardisation summaries.

`MoSPI_record_key` is a deterministic link key, not a new PLFS identifier.
For 2025 it normalises month only for the added key/context columns (`1.0` and
`01` become `1`); the source `month` field remains unchanged.

The contracts hold facts evidenced by the project EDA and release READMEs.
They do not pretend that an unreviewed spreadsheet parse is a semantic
codebook. A complete HSD/NSO-reviewed header whitelist can be supplied on a
contract through `expected_*_headers`; until then the pipeline checks the
documented count and required fields and reports the whitelist dependency as a
warning. Survey weights are retained and tagged only; their values are never
altered or used as features.
