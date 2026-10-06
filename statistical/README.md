# PLFS Statistical Evidence Layer

This package is Stage 3 of MoSPI.  It measures how unusual each approved numerical response is relative to the peer population assigned by `peer_groups`; it does **not** declare a response erroneous, fraudulent, fabricated, invalid, or in need of automatic correction.

## V1 scope

Only these target variables are calculated:

| Target | Availability |
|---|---|
| `cws_earnings_salaried` | first visit and 2023-24 revisit |
| `cws_earnings_self_employed` | first visit and 2023-24 revisit |
| `day7_total_hours` | first visit only |

The package has no contextual probability model, ML detector, influence/weight feature, priority score, final flag, or supervisor workflow. Survey weights are never used to transform a response or as a predictor.

## Run

Run a normal first-visit release from the repository root:

```powershell
python -m statistical.cli `
  --prepared-persons preprocessing/runs/2025_first_visit_final_2025_first/prepared_persons.parquet `
  --peer-group-run peer_groups/runs/2025_first_visit_2025_first_v1 `
  --output-root statistical/runs --run-id 2025_first_v1
```

For the only supplied valid linked panel path, generate the companion revisit table from the 2023–24 first-visit run:

```powershell
python -m statistical.cli `
  --prepared-persons preprocessing/runs/2023_24_first_visit_final_2023_24_first/prepared_persons.parquet `
  --peer-group-run peer_groups/runs/2023_24_first_visit_2023_24_first_v1 `
  --revisit-prepared-persons preprocessing/runs/2023_24_revisit_final_2023_24_revisit/prepared_persons.parquet `
  --revisit-peer-group-run peer_groups/runs/2023_24_revisit_2023_24_revisit_v1 `
  --output-root statistical/runs --run-id 2023_24_first_v1
```

Tail quantiles and the minimum linked-change reference size are versioned, reproducible working parameters (`0.05`, `0.95`, and `30` by default), not claims of scientifically optimal error thresholds.

## Outputs

Each immutable run directory contains:

- `statistical_evidence.parquet`: one row for every peer-group assignment, including not-assessable rows;
- `revisit_statistical_evidence.parquet`: only when linked 2023–24 inputs are explicitly provided; one row for every revisit assignment, including structural non-links;
- `statistical_report.json` and `.md`: counts, coverage, distribution summaries, warnings, and runtime;
- `run_metadata.json`: input provenance, method/specification versions, parameters, and output list.

An `UPPER_TAIL` value means it is above the configured upper reference quantile in its assigned peer population. It is statistical evidence only; it is not an error conclusion.

## Tests

```powershell
python -m pytest -q statistical/tests preprocessing/tests peer_groups/tests
```

The controlled tests cover tie-stable percentiles, known quantiles/MAD values, zero-MAD behavior, missing targets, deterministic repeats, valid linked revisits, unmatched revisits, and the non-availability of revisit hours.
