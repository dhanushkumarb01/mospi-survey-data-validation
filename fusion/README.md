# Fusion V2 — MoSPI survey data validation workspace

Converts immutable record-level evidence (statistical, contextual, ML, historical, documented integrity rules) into a traceable supervisor worklist, with FSU pattern evidence kept as separate group context. It never declares a response incorrect, never estimates an error probability, never modifies PLFS data and never calls external services. Method: `DESIGN.md`.

## Run

Normally via `python -m pipeline.run --release <r> --suffix v2`. Directly:

```powershell
python -m fusion.cli `
  --prepared-persons preprocessing/runs/2024_first_visit_final_2024_first/prepared_persons.parquet `
  --statistical-run statistical/runs/2024_first_visit_v2 --contextual-run contextual/runs/2024_first_visit_2024_first_v1_final `
  --ml-run ml/runs/2024_first_visit_v2 --pattern-run pattern/runs/2024_first_visit_v2 `
  --historical-run historical/runs/2024_first_visit_v2 --integrity-run integrity/runs/2024_first_visit_v2 `
  --output-root fusion/runs --run-id v2
python -m fusion.serve --fusion-root fusion/runs          # http://127.0.0.1:8000
```

## Supervisor workspace

* **Overview** — what needs attention, priority groups, review progress, highest-priority records by State/UT, FSU alerts, and the honest note that many records receive a place in one ranked list.
* **Cases to review** — priority order; filters; full CSV export (streamed, no truncation).
* **Case page** — why you are seeing it → what looks unusual → evidence (observed / compared with / what it means / why it matters, including earlier periods and documented rules) → summary by source → checklist → importance → decision → next case.
* **Group alerts (FSU)** — FSU evidence, ordered by q-value; never about a person or an enumerator.
* **Area trends** — weighted CWS indicators by area and period with unusual changes (screening values, not official estimates).
* **Reviewed cases**, and a separate **Technical reference** (formulas, coverage, E0–E7 evaluation, integrity rules, online record check, audit resolution, limitations).

Case stories are built by `explain.py` from the stored runs named in each case's provenance; it recomputes nothing. Wording never exceeds the numbers: "above the range covering 9 in 10 comparable records", "model estimate" (never "typical"), FSU wording from q-values.

## API (local)

`/api/runs, /api/labels, /api/summary, /api/overview, /api/cases, /api/cases/{id}, /api/cases/{id}/events (POST), /api/queue/position, /api/reviews, /api/patterns, /api/groups, /api/groups/{fsu}, /api/aggregates, /api/integrity, /api/evaluation, /api/validate/record (POST), /api/export/queue, /api/session`. V1 runs still open (queries use the columns a run has) and are labelled as the earlier method.

## Outputs

`fused_cases.parquet`, `evidence_cards.parquet`, `group_priorities.parquet`, `influence_components.parquet`, `review_audit.sqlite` (append-only), `fusion_report.json/.md`, `run_metadata.json`.
