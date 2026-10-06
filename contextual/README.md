# PLFS Contextual Evidence Layer

This package answers a different question from `statistical/`: how often does the observed occupation response occur among observations in an already-issued contextual reference population? It produces conditional response-frequency evidence; it does not estimate whether a record is erroneous.

V1 supports first-visit `principal_occupation_code` only. It uses the existing `day7_total_hours` peer assignment for the same prepared-person run as its reference population. That existing profile supplies release, observation, design-period, visit and post-2025 month boundaries, plus state, sector, CWS status and (when supported at the selected backoff level) industry division. No peer group is constructed by this package.

Run from the project root:

```powershell
python -m contextual.cli `
  --prepared-persons preprocessing/runs/2025_first_visit_final_2025_first/prepared_persons.parquet `
  --peer-group-run peer_groups/runs/2025_first_visit_2025_first_v1 `
  --output-root contextual/runs --run-id 2025_first_v1
```

Each immutable run writes:

- `contextual_evidence.parquet` — one occupation-evidence row per prepared person, including explicit `NOT_ASSESSABLE` rows;
- `contextual_report.json` and `.md` — coverage, reference counts and warnings;
- `run_metadata.json` — source and peer-run provenance, method and boundary information.

Run the relevant test suite with:

```powershell
python -m pytest -q preprocessing/tests peer_groups/tests statistical/tests contextual/tests
```
