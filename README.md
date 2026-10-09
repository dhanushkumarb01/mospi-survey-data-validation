# MoSPI — Intelligent Survey Data Validation Platform (PLFS)

A local, open-source evidence and review workspace for validating Periodic Labour Force Survey (PLFS) unit-level data, built in response to the HSD/NSO/MoSPI project brief *"Design and Development of an Intelligent Survey Data Validation Platform using Probabilistic and Machine Learning Techniques"*. It helps an HSD supervisor find records, FSUs and areas that merit attention, and see the stored evidence behind every flag. It never decides that a record is wrong, never corrects a response and never claims an error probability.

> **Naming.** The application presents itself as the MoSPI survey data validation platform; the UI footer carries "Powered by INNODATATICS". Runs stored before the rename hold columns prefixed `iospi_*`; current code writes `MoSPI_*`. Both are read through `survey_rules/schema.py`, which aliases legacy names at read time and never rewrites a stored run.

**Read first:** [docs/10_10_IMPROVEMENT_PLAN.md](docs/10_10_IMPROVEMENT_PLAN.md) — the scientific audit and the specification this version implements, with an implementation-status section at the top. The earlier strict evaluation, [docs/FINAL_EVALUATION_AGAINST_PROBLEM_STATEMENT.md](docs/FINAL_EVALUATION_AGAINST_PROBLEM_STATEMENT.md), describes the superseded V2.0 priority.

## Architecture (V2, current method)

```
stored PLFS releases -> preparation (release contracts, keys, linkage)
  -> integrity rules (person + household; cited; dry-run on every batch)            -> rule findings (always "Check now")
  -> survey-design-aware peer groups (State x sector x status [x occupation/industry], quarter-first pre-2025, month in 2025)
  -> value evidence per variable: current peers (leave-one-out tail probability)
                                  + earlier periods (out-of-sample, same design period; same-season where available)
                                  + expected-value model trained on earlier periods (split-conformal)
  -> coding evidence: smoothed conditional tail probability of the occupation code
  -> FSU patterns + fieldwork paradata + near-duplicate households (combined per FSU, FDR across FSUs) -> group alerts (context only)
  -> area indicators with design-based standard errors                                                 -> area alerts
  -> workload-aware queue: tiers by calibrated thresholds and review budget, FSU cap, impact (change in the estimate / SE) orders within a tier
  -> plain-language case story -> supervisor decision (taxonomy, reason, verification) -> hash-chained audit -> feedback report
```

Release, visit, quarter/month and the January-2025 design break are preserved everywhere; nothing is compared across the redesign. An FSU is never treated as an enumerator. Isolation Forest and LOF are computed for research only and never affect the queue.

| Package | Responsibility |
|---|---|
| `survey_rules/` | Documented PLFS applicability (incl. day-wise casual wage), final weights, period axis, integrity concept maps, the versioned schema read boundary (`schema.py`) and design-based variance (`variance.py`). |
| `preprocessing/` | Release-specific contracts, schema/key/linkage checks, immutable prepared Parquet. |
| `integrity/` | YAML rule facility: 13 rule types, person and household level, rule metadata, self-tests, per-batch dry-run report. |
| `peer_groups/` | Bounded comparable reference populations (spec v1.1). |
| `statistical/` | Leave-one-out placement and finite-sample tail probabilities within peer groups; 2023-24 linked revisit changes. |
| `contextual/` | Occupation-code coding check (conformal frequency tail probability). |
| `ml/` | Expected-value models trained on earlier periods (four targets) with a model registry; IF/LOF research outputs. |
| `historical/` | Earlier-period comparison, same-season comparison, hashed reference snapshot; area indicators with design SEs and a known-events calendar. |
| `pattern/` | FSU checks (status mix standardised for age and sex, distributions, heaping, spread, interview duration and dates, response codes, substitution, near-duplicates), local dispersion, FSU-level q-values. |
| `fusion/` | Lanes, impact, queue, case stories, review/audit, feedback, API and UI. |
| `pipeline/` | Batch orchestration with quality gates (`qa.py`). |
| `evaluation/` | Error catalogue v2, CAPI-pass metrics, seeds and State folds, paired bootstrap, `--verify`; pre-registered `PROTOCOL.md`. |
| `scripts/` | `export_serving_data.py`: portable bundle of the stored runs the workspace reads. |

## Run with Docker (recommended)

```bash
docker compose build
docker compose --profile seed run --rm seed     # copy stored runs into the data volume
docker compose up -d                            # http://127.0.0.1:8000  (health: /healthz)
```

Survey data is never built into the image. Configuration, data mounting, backups, security notes and troubleshooting are in [docs/DOCKER.md](docs/DOCKER.md).

## Hosted review-only instance (Vercel)

A review-only copy of the workspace can be hosted on Vercel: runs are viewed there, batches are never started there, and decisions stay read-only until a durable shared audit store exists. Locally, `python -m fusion.serve --review-only` gives the same batch restriction. Setup, access control, synthetic demo data and the storage blocker are in [docs/VERCEL_REVIEW_ONLY_DEPLOYMENT.md](docs/VERCEL_REVIEW_ONLY_DEPLOYMENT.md).

## Run without Docker

Python 3.11, then `pip install -r requirements.txt` (pinned; `requirements-dev.txt` adds the test tools).

```bash
python -m pipeline.run --release 2024 --suffix v2_1    # batch: every layer, quality gates, immutable runs, report in pipeline/runs/
python -m pipeline.run --release 2025 --suffix v2_1
python -m pipeline.run --release 2024 --suffix v2_2 --reuse-suffix v2_1 --rerun ml,fusion   # recompute only changed stages
python -m evaluation.run --release 2024 --seeds 1-5 --fold A   # protocol v1 (evaluation/PROTOCOL.md); seed 1 run (development), confirmation not run
python -m fusion.serve --fusion-root fusion/runs       # http://127.0.0.1:8000
```

Batches can also be started and followed from the workspace (**Batch validation** page; `/api/batch`), for the prepared releases on the server; uploading raw files is not offered. With authentication on, only an `admin` can start one.

Optional authentication: `python -m fusion.serve --users-file users.json`, where the file is `{"users": [{"name": "...", "role": "supervisor|technical|admin", "token_sha256": "<sha256 of the token>"}]}`. Without it, the server refuses to listen beyond 127.0.0.1.

## Status of each capability

Status words: **Validated** (checked against documents or data), **Implemented, not evaluated**, **Provisional** (default pending HSD), **Not possible with current data**, **Later stage** (PostgreSQL / eSigma), **Not implemented**.

| Capability | Status |
|---|---|
| Stored runs readable by current code (legacy `iospi_*` and current `MoSPI_*` columns) | Implemented; tested on fixtures; real-data smoke tests opt-in (`pytest -m realdata --realdata`) |
| Fail-loud inputs and per-stage quality gates | Implemented and tested (fault injection) |
| Questionnaire applicability, final weights | Validated (Vol. I, schedule, READMEs; all deliveries) |
| Integrity rules (person + household; arithmetic, existential, referential, temporal) | 13 approved hard rules with 0 violations on all stored releases (dry run); district code list valid for 2025 only (pre-2025 list is outdated); 2 soft rules drafted, inactive until HSD approval |
| Value checks (current peers, earlier periods, expected-value models) | Implemented, not evaluated |
| Coding check (occupation code) | Implemented, not evaluated |
| Workload-aware queue, impact ordering | Implemented, not evaluated; budget is a Provisional default |
| FSU group alerts incl. fieldwork paradata and near-duplicates | Implemented, not evaluated |
| Area indicators with design-based SEs, known-events calendar | Implemented, not evaluated; calendar empty until HSD supplies events |
| Decision taxonomy, reason codes, time on case, hash-chained audit, feedback report | Implemented and tested |
| Evaluation instrument (catalogue v2, CAPI-pass metrics, seeds/folds, `--verify`) | Implemented; **the campaign has not been run** |
| Real-time ingestion API, scheduler, PostgreSQL stores | Later stage (not implemented) |
| eSigma integration | Later stage; boundary and open questions in `docs/ESIGMA_INTEGRATION_ROADMAP.md` |
| Related-survey validation | Not possible with current data (no approved related dataset) |
| Enumerator analytics | Not possible with current data (no investigator code in the released files) |
| Same-month-previous-year comparison for 2025 | Not possible with current data (needs 2026 releases) |
| Real-world precision and miss rate | Needs the HSD pilot with pre-scrutiny data (gate G1) |
| Local token authentication | Prototype; not a GoI-approved identity system |

## Tests

```bash
python -m pytest -q                                   # or: docker compose --profile test run --rm tests
```

Tests protect behaviour and the audited failure modes; they do not establish error-detection accuracy. Background documents:
* `AUDIT_2026-10-03.md`: the pre-V2 findings.
* `evaluation/README.md`: the injection design.
* Each package's DESIGN/README.
