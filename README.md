# MoSPI — Intelligent Survey Data Validation Platform (PLFS)

A local, open-source evidence and review workspace for validating Periodic Labour Force Survey (PLFS) unit-level data, built in response to the HSD/NSO/MoSPI project brief *"Design and Development of an Intelligent Survey Data Validation Platform using Probabilistic and Machine Learning Techniques"*. It helps an HSD supervisor find records, FSUs and areas that merit attention, and see the stored evidence behind every flag. It never decides that a record is wrong, never corrects a response and never claims an error probability.

> **Naming.** The application presents itself as the MoSPI survey data validation platform. "MoSPI" is the project's internal working name. It remains in code identifiers that are stored inside existing runs and must not change: Parquet column prefixes `MoSPI_*`, method versions such as `MoSPI-fusion-v2.0`, and logger names. The UI footer carries "Powered by INNODATATICS".

**Read first:** [docs/FINAL_EVALUATION_AGAINST_PROBLEM_STATEMENT.md](docs/FINAL_EVALUATION_AGAINST_PROBLEM_STATEMENT.md). It is the strict evaluation of this implementation against the brief: what is satisfied, what is partial, what is not, and why.

## Architecture

`raw PLFS → preparation & integrity → survey-design-aware peer groups → record evidence (statistical · contextual · ML · historical · documented rules) → calibration → risk; influence (weighted-total share) → priority → case explanation → human decision → audit`

Two separate tracks never raise an individual record's priority:
* **FSU (group) evidence** (`pattern/`), which has its own queue.
* **Area trends** (`historical/` aggregates).

Release, visit, quarter/month and the January-2025 design break are preserved everywhere. An FSU is never treated as an enumerator.

| Package | Responsibility |
|---|---|
| `survey_rules/` | Documented PLFS applicability, final-weight and period rules, with citations. |
| `preprocessing/` | Release-specific contracts, schema/key/linkage integrity checks, immutable prepared Parquet. |
| `integrity/` | YAML rule facility (documented rules only); batch and single-record. |
| `peer_groups/` | Bounded comparable reference populations. |
| `statistical/` | Robust peer-conditioned evidence for applicable values; 2023-24 linked revisit changes. |
| `contextual/` | Conditional occupation-frequency evidence. |
| `ml/` | Isolation Forest, distinct-point LOF, applicable-earner conditional model, exact signatures. |
| `historical/` | Comparison with earlier periods of the same design; weighted area indicators and change screening. |
| `pattern/` | FSU-level tested evidence with q-values. |
| `fusion/` | Provenance gate, calibration, risk, influence, priority, explanations, review audit, API and UI. |
| `pipeline/` | Batch orchestration of all layers for a release. |
| `evaluation/` | Controlled error injection and E0–E7. |
| `scripts/` | `export_serving_data.py`: portable bundle of the stored runs the workspace reads. |

## Run with Docker (recommended)

```bash
docker compose build
docker compose --profile seed run --rm seed     # copy stored runs into the data volume
docker compose up -d                            # http://127.0.0.1:8000  (health: /healthz)
```

Survey data is never built into the image. Configuration, data mounting, backups, security notes and troubleshooting are in [docs/DOCKER.md](docs/DOCKER.md).

## Run without Docker

Python 3.11, then `pip install -r requirements.txt` (pinned; `requirements-dev.txt` adds the test tools).

```bash
python -m pipeline.run --release 2024 --suffix v2      # batch: every layer, immutable runs, timing report
python -m pipeline.run --release 2023_24 --suffix v2
python -m pipeline.run --release 2025 --suffix v2
python -m evaluation.run --release 2024                # controlled injection study (also 2025)
python -m fusion.serve --fusion-root fusion/runs       # http://127.0.0.1:8000
```

Optional authentication: `python -m fusion.serve --users-file users.json`, where the file is `{"users": [{"name": "...", "role": "supervisor|technical|admin", "token_sha256": "<sha256 of the token>"}]}`. Without it, the server refuses to listen beyond 127.0.0.1.

## Status of each capability

Full evidence and gap analysis: [docs/FINAL_EVALUATION_AGAINST_PROBLEM_STATEMENT.md](docs/FINAL_EVALUATION_AGAINST_PROBLEM_STATEMENT.md).

| Capability | Status |
|---|---|
| Questionnaire applicability (placeholder zeros excluded) | Validated against Vol. I §3.6.17–3.6.19 and all three deliveries |
| Final weights (MULT/100, /200 when NSS ≠ NSC; 2025 MULT/100) | Validated against READMEs; national indicators match published magnitudes |
| Survey rounds in the workspace | 2023-24, Calendar 2024 (pre-2025 design) and 2025 (post-2025 design), first visit |
| Record-level statistical, contextual, ML, historical evidence | Implemented; evaluated on injected errors only |
| Fused priority (risk × influence) | Implemented; **in the injection study it ranks non-rule errors worse than the statistical or historical layer alone** (see evaluation report) |
| FSU tests, q-values | Implemented; the current (overdispersion-corrected) version has **not** been re-evaluated |
| Area indicators and change screening | Implemented; screening only, SRS standard errors without design effects (Provisional) |
| Source weights, override, priority bands, influence | Provisional engineering choices |
| Documented integrity rules, online single-record check, streamed CSV export | Implemented (rules: file-based YAML, person level only) |
| Local token authentication | Prototype; not a GoI-approved identity system |
| Docker deployment | Implemented and tested (single app container, data volume, health check) |
| Real-time / streaming ingestion | Not implemented: single-record check API (nothing stored) and batch pipeline only |
| Cross-release record linkage, related-survey validation | Not assessable with the supplied data |
| Enumerator analytics | Not assessable (no enumerator identifier in the data) |
| Revisit (panel) evidence in the review list | Computed for 2023-24; not in the first-visit review list |
| Learning from supervisor decisions | Not implemented (decisions are audited but not fed back) |
| eSigma integration | Roadmap only: `docs/ESIGMA_INTEGRATION_ROADMAP.md` |

## Tests

```bash
python -m pytest -q                                   # or: docker compose --profile test run --rm tests
```

Tests protect behaviour and the audited failure modes; they do not establish error-detection accuracy. Background documents:
* `AUDIT_2026-10-03.md`: the pre-V2 findings.
* `evaluation/README.md`: the injection design.
* Each package's DESIGN/README.
