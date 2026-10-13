# Technical documentation: MoSPI Intelligent Survey Data Validation Platform (PLFS)

Version 2.2 · October 2026

This document describes how the platform is built: its architecture, every pipeline stage, the review application, the data stores, deployment, configuration, security, evaluation and testing. For a non-technical, page-by-page introduction, read [WALKTHROUGH.md](WALKTHROUGH.md) first.

---

## Contents

1. [Purpose and design principles](#1-purpose-and-design-principles)
2. [System architecture](#2-system-architecture)
3. [Repository layout](#3-repository-layout)
4. [Data and run layout](#4-data-and-run-layout)
5. [The validation pipeline](#5-the-validation-pipeline)
6. [Evidence fusion and the review queue](#6-evidence-fusion-and-the-review-queue)
7. [Review application](#7-review-application)
8. [Data stores](#8-data-stores)
9. [Upload & validate, worker and periodic checks](#9-upload--validate-worker-and-periodic-checks)
10. [Deployment](#10-deployment)
11. [Configuration reference](#11-configuration-reference)
12. [Security](#12-security)
13. [Evaluation](#13-evaluation)
14. [Testing](#14-testing)
15. [Status and known limitations](#15-status-and-known-limitations)
16. [Further reading](#16-further-reading)

---

## 1. Purpose and design principles

The platform was built in response to the HSD/NSO/MoSPI brief *"Design and Development of an Intelligent Survey Data Validation Platform using Probabilistic and Machine Learning Techniques"*. It screens PLFS unit-level data after CAPI validation and produces a workload-sized list of records, households, FSUs and areas for supervisor review, with the evidence behind each item.

Principles that every component follows:

| Principle | How it is enforced |
|---|---|
| **Evidence, not verdicts** | Outputs are tail probabilities, comparisons and rule findings. No component outputs an error probability or a "wrong" label. |
| **Survey data are never changed** | Raw files are read-only. Preparation adds columns and never drops, imputes or corrects. Decisions are stored separately and never written back. |
| **Immutable, traceable runs** | Each stage writes a new run directory with `run_metadata.json` (inputs, versions, parameters, code commit). A run directory is never overwritten. |
| **Survey-design aware** | Release, visit, quarter/month and the January 2025 redesign are boundaries. Nothing is compared across the redesign. Weights are used for estimates and never as model features. |
| **Fail loudly** | Missing columns raise errors, not blanks. Quality gates stop a batch before a degraded stage can publish a queue. |
| **One system** | Every capability lives in the one `mospi` package. Local, Docker and hosted instances run the same code and the same queries. |

## 2. System architecture

```
                      ┌──────────────────────────── processing machine ─────────────────────────────┐
 PLFS CSV deliveries ─►  preprocessing ─► integrity ─► peer groups ─► statistical ─► contextual     │
 (data/raw, uploads)  │        │                            │              │              │         │
                      │        └────────► ml (expected-value models) ──────┤              │         │
                      │        └────────► pattern (FSU checks, fieldwork) ─┤              │         │
                      │        └────────► historical (earlier periods, area indicators) ──┤         │
                      │                                                    ▼              ▼         │
                      │                                   fusion: lanes ─► queue ─► stories          │
                      │                                         │                                    │
                      │   Parquet runs under data/<stage>/runs  │   review_audit.sqlite (default)    │
                      │                                         ▼                                    │
                      │   review application (FastAPI + static UI) ── python -m mospi.app.serve     │
                      │   validation worker ── python -m mospi.ingest.worker run                     │
                      └───────────────┬──────────────────────────────────────────────────────────────┘
                                      │ (optional) MOSPI_AUDIT_BACKEND=postgres
                                      ▼
                      Supabase PostgreSQL, schema "mospi"
                      audit trail · run registry · datasets · jobs · checks · alerts · hosted serving set
                                      │ read-only role, hosted_* views (+ optional insert-only role for decisions)
                                      ▼
                      Vercel: review-only hosted instance (same API and UI)
```

Technology: Python 3.11 (3.12 on Vercel), pandas, NumPy, pyarrow, DuckDB, SciPy, scikit-learn, FastAPI/Starlette, uvicorn and psycopg 3. The UI is plain HTML, CSS and JavaScript with no build step, no external fonts and no CDN. Analytical data is stored as Parquet and queried with DuckDB. Exact versions are pinned in `requirements.txt`.

## 3. Repository layout

```
mospi/                         application package
  paths.py                     data-root resolution (data/ or MOSPI_DATA_DIR)
  survey_rules/                survey knowledge: applicability, weights, periods, integrity concept maps,
                               schema read boundary (schema.py), design-based variance (variance.py)
  pipeline/
    run.py                     batch orchestration of all stages
    jobs.py                    batch jobs started from the workspace
    qa.py                      quality gates after each stage
    stages/
      preprocessing/           release contracts, keys, linkage, prepared Parquet
      integrity/               YAML rule engine; rules/*.yaml
      peer_groups/             comparable reference populations
      statistical/             leave-one-out tail probabilities; 2023-24 revisit changes
      contextual/              occupation-code coding check
      ml/                      expected-value models; Isolation Forest / LOF (research only)
      pattern/                 FSU checks, fieldwork paradata, near-duplicates
      historical/              earlier-period comparison; area indicators with design SEs
      fusion/                  lanes, impact, queue, stories, review/audit store, feedback
  evaluation/                  controlled error injection, metrics, protocol runner
  app/                         api.py, operations_api.py, backends.py, serve.py, vercel_app.py, ui/
  db/                          PostgreSQL: connection, migrations, audit store, registry, serving set, backup
  ingest/                      uploads, pre-flight, worker, periodic checks
tests/                         mirrors mospi/; synthetic.py builds a synthetic PLFS delivery
data/                          raw deliveries and stored runs (git-ignored except demo/ and evaluation/results/)
docs/                          this documentation
scripts/                       export_serving_data.py, build_demo_data.py
deploy/                        public Supabase CA certificate; placeholder CA for Docker builds
Dockerfile, docker-compose.yml, docker-compose.bind.yml, vercel.json, pyproject.toml, requirements*.txt, conftest.py
```

Earlier versions of the repository kept each stage in its own top-level folder (`fusion/`, `ml/`, `pipeline/`, ...). Dated documents and stored run metadata may still name those paths: `fusion/` is now `mospi/pipeline/stages/fusion/` (with `api.py`, `serve.py` and `ui/` under `mospi/app/`), `<stage>/` is `mospi/pipeline/stages/<stage>/`, `<stage>/runs/` is `data/<stage>/runs/`, and `evaluation/` is `mospi/evaluation/` (results under `data/evaluation/results/`).

## 4. Data and run layout

| Path | Contents | Git |
|---|---|---|
| `data/raw/` | Supplied PLFS deliveries: `2023-June2024/`, `Jan-Dec2024/`, `Post2025/`. Input only. | ignored |
| `data/<stage>/runs/<run_id>/` | Immutable stage outputs (Parquet, JSON/Markdown reports, `run_metadata.json`). Fusion runs also hold `review_audit.sqlite`. | ignored |
| `data/pipeline/` | `runs/` batch reports, `jobs/` workspace job records and logs, `logs/`. | ignored |
| `data/evaluation/` | `runs/`, `logs/` (ignored) and `results/` (tracked evidence). | partly |
| `data/demo/` | Synthetic demonstration bundle (no real respondent). | tracked |

The `<stage>/runs/<run_id>/` layout is a contract shared by the stages, the API, the export script and the Docker volume (`/data/<stage>/runs`). Do not rename it.

**Releases and contracts.** Four delivery contracts are defined in `mospi/pipeline/stages/preprocessing/config.py`: `2023_24_first`, `2023_24_revisit`, `2024_first` and `2025_first`. Releases have different raw schemas and are never pooled. 2023-24 and 2024 are quarterly (pre-redesign). 2025 is monthly (post-redesign).

**Schema read boundary.** The platform's own columns were renamed from `iospi_*` to `MoSPI_*`. Runs stored before the rename keep their original names. `mospi/survey_rules/schema.py` resolves canonical names at read time, refuses ambiguous files, and raises `SchemaError` for a missing column. Stored runs are never rewritten.

## 5. The validation pipeline

### 5.1 Orchestration

```bash
python -m mospi.pipeline.run --release 2024 --suffix v2_2
python -m mospi.pipeline.run --release 2024 --suffix v2_3 --reuse-suffix v2_2 --rerun ml,fusion
```

`mospi/pipeline/run.py` runs the stages `peer → statistical → contextual → ml → pattern → historical → integrity → fusion` on a prepared delivery (`PRESETS` names the prepared inputs and history per release). A stage whose run directory already exists is reused, so an interrupted batch resumes. `--reuse-suffix` and `--rerun` recompute only the named stages. Every run records the git commit (`+uncommitted-changes` when the tree is dirty).

**Quality gates** (`mospi/pipeline/qa.py`) run after every stage. They check that required files are present and non-empty, that there is one evidence row per prepared record (per target where relevant), that identity columns are not blank, that the assessable share is above a floor (1%), and optionally that it stays within tolerance of a baseline run. A failed gate stops the batch before fusion. A timing, provenance and QA report is written to `data/pipeline/runs/`.

### 5.2 Preprocessing

`python -m mospi.pipeline.stages.preprocessing.cli --input-root data/raw --output-root data/preprocessing/runs --contract 2024_first`

Deterministic preparation of household and person CSVs against the documented release contract: schema and required-field checks, key construction (`MoSPI_record_key`, a deterministic link key rather than a new PLFS identifier), household-person linkage, period and design tagging, and weight tagging. Every raw column is kept. Outputs: `prepared_households.parquet`, `prepared_persons.parquet`, `issue_log.csv`, reports and metadata. Nothing is dropped, imputed or corrected.

### 5.3 Integrity rules

`python -m mospi.pipeline.stages.integrity.engine --prepared-persons <file> --output-root data/integrity/runs --run-id v2`

A generic engine over YAML rules (`rules/plfs_person_rules.yaml`, `rules/plfs_household_rules.yaml`) written in survey **concepts** that `survey_rules/plfs_integrity.py` maps to each release's raw columns.

* **13 rule types:** `allowed_values`, `range`, `required_when`, `absent_when`, `value_when`, `not_value_when`, `unique`, `arithmetic`, `lower_bound_sum`, `exists_exactly`, `count_matches`, `references`, `within_period`.
* **Current rule set:** 15 person rules (R01–R15) and 5 household rules (H01–H05), all approved, plus 2 draft soft rules (S01, S02) that stay inactive until HSD approval. Examples: one head per household; household size equals persons listed; consumption and income arithmetic identities; district code valid for the State (2025 only, because the supplied pre-2025 code list is outdated); salaried earnings only for statuses 31/71/72; day-7 hours within 24.
* **Metadata required per rule:** id, version, level, severity, citation, owner, approval status, and at least one violating and one passing test case. Test cases run on every load, and a rule that fails its own tests is refused.
* Every batch writes `rule_dry_run.json` with counts for every rule, active or not. Approved hard rules show 0 violations on the stored releases, as expected for post-CAPI data.
* A rule whose concept is not collected in a release is *not applicable*, never *passed*.
* The same engine serves `POST /api/validate/record` (one record, nothing stored).
* The rule files are hashed into each integrity run. Edit them only through review.

### 5.4 Peer groups

Specification `plfs-peer-groups-v1.1`. Each person and target gets a reproducible comparison group of at least 30 people (configurable), built from State/UT × sector × activity status [× occupation group or industry division], with backoff through coarser levels. Mandatory boundaries are release, visit, design period and, after 2025, calendar month. Pre-2025 releases try each level within the record's quarter first, then pooled over the release. Targets: `cws_earnings_salaried`, `cws_earnings_self_employed`, `day7_total_hours` and `day7_casual_wage` (within day-7 casual statuses 41/42/51 and 2-digit industry). Rows that cannot be placed are kept as `NOT_ASSESSABLE`. FSU and weight are never peer dimensions.

### 5.5 Statistical evidence

For each assigned target value: robust placement within the peer group (percentile, median and MAD) and a **leave-one-out finite-sample tail probability**, `(#peers at least as extreme + 1) / (n + 1)`, two-sided. Default tail quantiles are 0.05 and 0.95. For 2023-24, linked first-visit/revisit changes are computed (`revisit_statistical_evidence.parquet`). Those changes are not yet part of the queue.

### 5.6 Contextual (coding) evidence

How often the observed 3-digit `principal_occupation_code` occurs within the person's existing day-7-hours peer group. The output is a **conformal frequency tail probability**, designed to be invariant to group size. First visit only.

### 5.7 ML evidence

* **Expected-value models** (`conditional_models.py`), the only ML component on the decision path. Four targets (salaried and self-employed earnings and casual wage on the log scale; day-7 hours on the natural scale). Each model predicts a value from age, sex, education, activity status, occupation group, industry division, State/UT, sector and, where relevant, hours. Identifiers and weights are never features. A record in period *p* is scored by a model trained **only on strictly earlier periods of the same design period**. The first period of a design falls back to an FSU-grouped two-fold cross-fit and is labelled as such. A held-out 20% of training FSUs gives split-conformal residuals, per State where there are enough (Mondrian calibration) and national otherwise. These yield a tail probability and a "usual range" (prediction + 5th/95th residual percentiles). Fits are recorded in a model registry.
* **Isolation Forest, LOF and exact-similarity** evidence are computed for research only (`decision_path = RESEARCH_ONLY`). Fusion never reads them. LOF is fitted on distinct feature vectors to avoid infinite densities from identical answers.

### 5.8 Pattern (FSU) evidence

Leave-FSU-out comparisons against other FSUs of the same release, visit, month/quarter, State/UT, sector and stratum:

* distribution shift and activity-status mix, standardised for age and sex;
* age and earnings heaping; reduced-variance (too-uniform) concentration; local dispersion;
* temporal drift; revisit pattern evidence (2023-24 linked panel);
* **fieldwork paradata** (`fieldwork.py`): short interview durations (Mann-Whitney), single-day concentration of interviews (empirical p-value), response-code mix (G-test), substitution share (binomial), near-duplicate persons across households (binomial).

Per FSU, the calibrated checks are combined (Bonferroni) and corrected across FSUs with Benjamini-Hochberg into an **FSU q-value**. Short-interview, near-duplicate and response-code checks are shown as context only, because on released data their p-values fire 2–16 times the nominal rate. An FSU is never treated as an enumerator.

### 5.9 Historical evidence

* **Record level.** Each applicable earnings, hours or wage value is compared with the same comparison cell in **strictly preceding periods of the same design period**: up to four quarters before 2025, up to three months in 2025. The reference never contains the record or its own period, so the tail probability `(#reference ≥ x + 1) / (n + 1)` is out-of-sample. Pre-2025 releases overlap (Calendar-2024 Q3/Q4 are the 2023-24 Q3/Q4 records), so periods are placed on one de-duplicated quarter axis and each period is taken from one release only. A same-quarter-last-year comparison is shown where available. Earnings are nominal, because no deflator has been approved. A hashed reference snapshot is written per run.
* **Aggregate level.** Weighted LFPR, WPR, UR (15+), weighted median salaried earnings and weighted mean day-7 hours, by sector for the nation, each State/UT and each district, per period. Each carries a **design-based standard error**: Taylor linearisation with FSU as PSU within strata, Woodruff's method for medians, and the "adjust" convention for lonely PSUs (`survey_rules/variance.py`). A period-on-period change is flagged when it is a robust outlier among other domains' changes **and** exceeds three SEs of the change. A known-events calendar (`known_events.yaml`, currently empty) annotates expected shifts.

## 6. Evidence fusion and the review queue

Fusion version `MoSPI-fusion-v2.2-lanes` (`mospi/pipeline/stages/fusion/`). It replaced the V2.0 design (average of ranks × domain-share influence). That design was measured to lose about half of its components' evidence and to over-review small UTs. It is kept only as evaluation baseline A0 (`legacy.py`).

### 6.1 Lanes (`lanes.py`)

**Rule lane.** Approved hard-rule findings (person and household) always go to *Check now* and are never mixed into a score.

**Value lane.** For each variable *v* of a record:

```
p_cur    leave-one-out tail probability vs current peers           (statistical)
p_hist   out-of-sample tail probability vs earlier periods          (historical)
p_model  split-conformal tail probability vs the expected value     (ml)

p_ref = mean(p_cur, p_hist)                 AND-like across references of the same variable
p_v   = 1 − (1 − min(p_ref, p_model))^k     Šidák over the k mechanisms available
p     = 1 − (1 − min_v p_v)^m               Šidák over the m variables assessed
```

**Discrete-test correction (Tarone, v2.2).** A finite-sample tail probability against *n* values cannot be smaller than 2/(n+1). Mechanisms and variables whose smallest attainable value exceeds the threshold are excluded from *k* and *m*. On the 2024 run this moved observed/nominal value alerts from 0.51 to 0.82.

**Coding lane.** The contextual conformal tail probability of the occupation code.

None of these is an error probability. A small *p* means the answer is rare among comparable people.

### 6.2 Queue (`queue.py`)

Parameters (`config.py`, recorded with every run; provisional until HSD supplies capacity):

| Parameter | Default | Meaning |
|---|---|---|
| `review_budget_share` | 0.01 | Share of records supervisors can review in *Check now* |
| `coding_budget_share` | 0.10 | Share of that budget for coding checks |
| `per_fsu_cap` | 10 | Maximum value checks per FSU in *Check now* |
| `tier_b_factor` / `tier_b_multiplier` | 5 / 2 | *Check if time*: evidence up to 5× the threshold, up to 2× the budget |
| `group_alert_q` / `group_strong_q` | 0.05 / 0.01 | FSU alert and strong-alert q-values |

* **Tier A, "Check now":** all hard-rule findings; value checks with *p* ≤ value threshold, strongest first, within the value budget and the FSU cap; coding checks within the coding budget.
* **Tier B, "Check if time":** soft-rule findings, threshold-passing checks that did not fit, and the next evidence band.
* Thresholds are the lane budget divided by the records the lane can assess. With calibrated evidence the expected number of alerts among clean records equals the budget, and every run reports the observed rate against it.

### 6.3 Impact (`impact.py`)

```
domain d  = release × period × State/UT × sector
delta_i   = w_i (y_i − m_i) / Σ_{j∈d} w_j        change if y_i were replaced by its expected value m_i
SE_d      = design-based SE of the domain mean, floored at national CV × domain mean
impact_i  = |delta_i| / SE_d
```

Impact orders cases **within** a tier only. It is never multiplied into evidence.

### 6.4 Case stories and outputs

`story.py` (current runs) and `explain.py` (all runs, including V1/V2.0) build the case page from stored values only. The order is: recorded → current peers → earlier periods → expected value → group context → importance → what to check. Wording is bounded by the numbers ("above the range covering 9 in 10 comparable records", "model estimate"). Code labels come only from the supplied official code lists (`labels.py`), and an unknown code is shown raw.

Fusion outputs: `fused_cases.parquet`, `value_evidence.parquet`, `evidence_cards.parquet`, `group_priorities.parquet`, `impact_domains.parquet`, `fusion_report.json/.md`, `run_metadata.json` and `review_audit.sqlite`.

### 6.5 Review and audit store (`review.py`)

* Event types: `CASE_VIEWED`, `DECISION_MADE`, `EXPORT`, `AUDIT_CHAIN_STARTED`.
* Decisions: `CONFIRMED_ERROR`, `VALID_BUT_UNUSUAL`, `NEEDS_FIELD_VERIFICATION`, `CANNOT_VERIFY`, `ESCALATE`. Each requires a reason code from its own list and a verification source (`PHONE_CALL`, `FIELD_REVISIT`, `SCHEDULE_IMAGE`, `SUPERVISOR_KNOWLEDGE`, `NOT_VERIFIED`). A corrected field and value may be noted and are never applied. Legacy V2.0 decision codes are mapped when read.
* **Append-only:** triggers abort any UPDATE or DELETE.
* **Tamper-evident:** `event_hash = sha256(previous_hash + canonical content)`. `verify_chain` recomputes the chain. Rows written before the chain existed are sealed by a digest in `AUDIT_CHAIN_STARTED` without being modified.
* **Concurrency:** appends take the write lock (`BEGIN IMMEDIATE`; in PostgreSQL a per-run `pg_advisory_xact_lock`) before reading the previous hash. A decision carries the last decision id the client saw, and a stale one raises `DecisionConflict` (HTTP 409).
* Time on case is computed server-side from the case-open event. An actor without a verified sign-in is stored as unverified.

`feedback.py` summarises decisions per lane and tier with Wilson 95% intervals and may *propose* a threshold change. It never applies one.

## 7. Review application

### 7.1 Entry points

| Command | Use |
|---|---|
| `python -m mospi.app.serve` | Local or Docker server (default `127.0.0.1:8000`). Options: `--fusion-root`, `--review-only`, `--audit-read-only`, `--host`, `--port`. |
| `mospi.app.vercel_app:app` | Hosted entry point: always review-only, with sign-in required. Audit read-only unless `MOSPI_REVIEW_DATABASE_URL` is set, in which case it is append-only for decisions and case views (§10.3). |

Sign-in is always required, with named accounts and three roles: administrator, supervisor and analyst (`mospi/auth`). Accounts are stored in PostgreSQL when `MOSPI_DATABASE_URL` is set, otherwise in a SQLite file. Administrators are created only with `python -m mospi.auth create-admin`. See [deployment/USER_ACCOUNTS.md](deployment/USER_ACCOUNTS.md).

### 7.2 UI

`mospi/app/ui/` (`index.html`, `app.js`, `styles.css`) is a single-page app with hash routes:

| Section | Route | Page |
|---|---|---|
| Review | `#/overview` | Overview: tier counts, progress ring, decision mix, priority by State, FSU alerts |
| | `#/worklist` | Worklist by FSU and household |
| | `#/cases`, `#/cases/<id>` | All cases with filters and CSV export; case page with story, checklist, decision form |
| | `#/groups` | Group alerts (FSU) |
| | `#/areas` | Area trends (inline SVG charts) |
| | `#/reviewed` | Decisions |
| Operations | `#/upload` | Upload & validate (PostgreSQL backend only) |
| | `#/batch` | Batch validation |
| Reference | `#/technical` | Provenance, audit verification, rules, evaluation, decision feedback, single-record check |

Design: sidebar navigation with a skip link, white cards, royal-blue accent (`#3355e0`), green reserved for status. Motion respects `prefers-reduced-motion`. Fonts and assets are local. Static assets carry a cache-bust query (`?v=...`), which must be bumped when they change.

### 7.3 API

Review (`api.py`):

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/session`, `/api/session/required`, `/api/deployment` | Current user; whether sign-in is required; which actions this instance allows |
| GET | `/api/runs`, `/api/labels`, `/api/version` | Reviewable runs; code labels; code version |
| GET | `/api/summary`, `/api/overview` | Counts and overview panels for a run |
| GET | `/api/cases`, `/api/cases/{id}`, `/api/queue/position` | Case list (filters, paging); case story; position in queue |
| POST | `/api/cases/{id}/events` | Record `CASE_VIEWED` or `DECISION_MADE` (supervisor/admin) |
| GET | `/api/reviews`, `/api/feedback`, `/api/audit/verify` | Decisions; feedback report; chain verification |
| GET | `/api/patterns`, `/api/groups`, `/api/groups/{fsu}` | FSU evidence and alerts |
| GET | `/api/aggregates`, `/api/worklist` | Area indicators; FSU/household worklist |
| GET | `/api/integrity`, `/api/evaluation` | Rule facility and dry run; evaluation results |
| POST | `/api/validate/record` | Single-record check (nothing stored) |
| GET | `/api/export/queue` | Streamed CSV export (supervisor/admin; audited) |
| GET/POST | `/api/batch/inputs`, `/api/batch`, `/api/batch/{job_id}` | Batch inputs, jobs, start (admin) |
| GET | `/healthz` | Health: version and, when on PostgreSQL, database reachability, TLS, schema version, serving-set state |

Operations (`operations_api.py`, PostgreSQL backend, local only):

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/operations` | Status for the alert bar (any role) |
| GET | `/api/ingest/contracts` | Supported delivery contracts |
| GET/POST | `/api/datasets`, `/api/datasets/{id}` | List, create and inspect datasets |
| PUT | `/api/datasets/{id}/files` | Upload a file (streamed, size-capped) |
| POST | `/api/datasets/{id}/preflight`, `/confirm`, `/reject` | Pre-flight; start validation; reject |
| GET/POST | `/api/jobs`, `/api/jobs/{id}`, `/retry`, `/cancel` | Jobs ledger |
| POST | `/api/checks` | Queue a periodic integrity check |
| GET/POST | `/api/notifications`, `/api/notifications/{id}/ack` | Alerts |

Writes require sign-in even on loopback. Uploads, validation, retry, cancel and checks are admin-only. Reads are available to admin and technical users.

### 7.4 Deployment modes

| Mode | Batches | Decisions/exports | Set by |
|---|---|---|---|
| Full (default) | Yes (admin) | Yes | — |
| Review-only | Refused (403) | Yes | `--review-only` / `MOSPI_REVIEW_ONLY=1` |
| Audit read-only | — | Refused (503, with reason) | `--audit-read-only` / `MOSPI_AUDIT_READ_ONLY=1` |
| Hosted | Refused | Decisions: with `MOSPI_REVIEW_DATABASE_URL` only (supervisor/admin). Exports: refused | `vercel_app.py` (always review-only, plus sign-in) |

## 8. Data stores

| Store | Holds | Technology |
|---|---|---|
| Stage runs | All evidence, queues and reports | Parquet + JSON under `data/`, queried with DuckDB |
| Review/audit (default) | One `review_audit.sqlite` per Fusion run | SQLite, append-only triggers, hash chain |
| Operational (optional) | Audit trail, run registry, datasets, jobs, checks, alerts, hosted serving set | PostgreSQL (Supabase), schema `mospi` |

PostgreSQL never holds survey rows, apart from the hosted serving set of approved runs, which is stored as verified Parquet bytes. The backend is selected by `MOSPI_AUDIT_BACKEND`. There is no dual-write and no silent fallback: if the database is unreachable, writes return 503.

**Schema (migrations `mospi/db/migrations/0001`–`0004`).** Tables: `schema_migrations`, `audit_events`, `audit_verifications`, `audit_migrations`, `datasets`, `dataset_files`, `jobs`, `job_events`, `runs`, `integrity_checks`, `notifications`, `serving_files`, `serving_chunks`. Hosted views: `hosted_runs`, `hosted_audit_events`, `hosted_audit_verifications`, `hosted_jobs`, `hosted_integrity_checks`, `hosted_serving_files`, `hosted_serving_chunks`, `hosted_schema_version`. Migrations are recorded with their SHA-256, and an applied migration whose file has changed is refused. **Never edit an applied migration file, including its comments.** Add a new numbered file instead.

**Roles.** `mospi_app` (local app and worker) can insert and select audit events and read/write the ledgers, and cannot update or delete audit events. `mospi_reader` (hosted) can only SELECT the `hosted_*` views in read-only transactions. `mospi_reviewer` (hosted decisions, optional) can INSERT into `audit_events` and SELECT five of its columns (ids, event type and hash; never comments, snapshots or corrected values) and `hosted_runs`; its row-level-security policies limit it to chained `DECISION_MADE`/`CASE_VIEWED`/`AUDIT_CHAIN_STARTED` rows of hosted runs by a signed-in actor, never the operations trail. A login refused by the database is not retried by the same process (the Supabase pooler bans addresses after repeated failures). The admin role is used only by operator tools. Row-level security is enabled on every table, and `PUBLIC`, `anon`, `authenticated` and `service_role` are revoked.

**Operator tools.**

```bash
python -m mospi.db.migrate [--roles | --status]        # schema, roles, grants, RLS (idempotent)
python -m mospi.db.migrate_audit [--dry-run]           # copy SQLite audit stores into PostgreSQL, chains verified
python -m mospi.db.registry register --fusion-root data/fusion/runs --run <id> --data-class APPROVED_REAL --hosted \
       --approval "<ref>" --approver "<name>" --approver-role "<role>"
python -m mospi.db.serving load --run <id>             # build, verify, upload, verify in-database
python -m mospi.db.serving remove --run <id>
python -m mospi.db.backup create [--without-serving-data] | verify <dump> | restore <dump> --target-db <new>
```

The run registry stores a manifest (path, size and SHA-256 of every file of the Fusion run and its source stage runs). A published manifest can never change. Run states are `PENDING`, `PUBLISHED`, `REGISTERED`, `FAILED` and `WITHDRAWN`, and data classes are `SYNTHETIC`, `INTERNAL_REAL` and `APPROVED_REAL`. Only `SYNTHETIC` or `APPROVED_REAL` runs can be hosted.

## 9. Upload & validate, worker and periodic checks

Enabled when `MOSPI_AUDIT_BACKEND=postgres`.

1. **Upload** (`ingest/storage.py`): server-generated file names, streamed with a size cap, and SHA-256, UTF-8, BOM and NUL checks recorded. An order-independent content fingerprint detects re-saved copies.
2. **Pre-flight** (`ingest/preflight.py`): one household and one person file of a single contract, required columns present, keys built exactly as preparation builds them, duplicate and overlap checks (record keys compared via keyed HMAC). Findings are BLOCKING, WARNING or INFO, with counts and column names only.
3. **Worker** (`python -m mospi.ingest.worker run`): one validation at a time, in a child process with a 15-second heartbeat:
   *staging* (re-verify hashes, lay out copies) → *preparation* → *pipeline* (with quality gates) → *publication* (manifest, registry `PENDING → PUBLISHED`, audit chain started, alerts).
   A QA-gate failure becomes `FAILED_QA_GATE` and is not retried. A stopped heartbeat becomes `INTERRUPTED` and is retried once: completed stages are reused and partial directories are renamed aside, never deleted.
4. **Periodic checks** (`ingest/checks.py`, every `MOSPI_CHECK_INTERVAL_MINUTES`): manifest files present and unchanged, quality-gate files present, unique case ids, metadata consistent with the registry, and audit chains intact. Uploaded files must be unchanged (a change is tampering). Registered deliveries are fingerprinted, and a change can trigger revalidation (`MOSPI_RERUN_ON_CHANGE`).
5. **Registering an existing delivery:** `python -m mospi.ingest.register --contract 2024_first --input-root data/raw [--preflight]`.

## 10. Deployment

### 10.1 Docker (recommended for local and on-premise use)

```bash
docker compose build                              # MOSPI_CODE_VERSION=$(git rev-parse --short=12 HEAD) for exact provenance
docker compose --profile seed run --rm seed       # copy stored runs into the named data volume
docker compose up -d                              # http://127.0.0.1:8000, health at /healthz
docker compose --profile test run --rm tests      # run the test suite in the container
```

Survey data is never built into the image. Data lives in a named volume. A bind-mount alternative (`docker-compose.bind.yml`) exists but is much slower on Windows and macOS. Behind a TLS-inspecting proxy or antivirus, pass the proxy root as `MOSPI_EXTRA_CA_FILE`. It is used as a BuildKit secret and never stored in the image. Details: [deployment/DOCKER.md](deployment/DOCKER.md).

### 10.2 Without Docker

Python 3.11, then `pip install -r requirements.txt` (`requirements-dev.txt` adds the test tools), then `python -m mospi.app.serve`.

### 10.3 Hosted review-only instance (Vercel + Supabase)

* URL: `https://mospi-survey-data-validation.vercel.app`, region `icn1`, next to the Supabase project (`ap-northeast-2`).
* Entry point `mospi.app.vercel_app:app`. `pyproject.toml` lists the hosted dependencies, which leave out pyarrow, SciPy, scikit-learn and uvicorn to stay under Vercel's 250 MB bundle limit. `.vercelignore` is an allowlist: no `data/`, `docs/`, `tests/` or `.env` is uploaded.
* Data: only the run approved for hosting (PLFS 2024 first visit, `2024_first_visit_v2_2`: 415,549 records, 21 files, 115 MB). After the first signed-in request, a new instance downloads the serving set from the `hosted_serving_*` views into `/tmp`, verifies every SHA-256, and serves it with the same DuckDB queries as the local workspace. A checksum failure or an unreachable database returns 503, and nothing partial is served.
* Environment: `MOSPI_AUDIT_BACKEND=postgres`, `MOSPI_DATABASE_URL` (reader role, transaction pooler `:6543`), `MOSPI_DB_CA_FILE`, `MOSPI_SESSION_SECRET`, `MOSPI_DB_MAX_CONNECTIONS=3`, and optionally `MOSPI_REVIEW_DATABASE_URL`.
* Decisions (code ready, not yet switched on): with `MOSPI_REVIEW_DATABASE_URL` (the `mospi_reviewer` role) signed-in supervisors and administrators record decisions into the Supabase audit chain; `/healthz` reports `"audit_store": "append-only"`. Notes are stored but not shown on the hosted site (the hosted views leave them out), and exports stay off. Without the variable the instance is read-only. The switch-on steps are in the deployment guide §4a.
* Deploy: `vercel link`, `vercel env add … production`, `vercel deploy --prod` (with `VERCEL_TOKEN` set).

Details, verification record and teardown: [deployment/VERCEL_REVIEW_ONLY_DEPLOYMENT.md](deployment/VERCEL_REVIEW_ONLY_DEPLOYMENT.md) and [deployment/POSTGRESQL.md](deployment/POSTGRESQL.md).

### 10.4 Portable data bundles

`python scripts/export_serving_data.py --output ../mospi-data` copies only the files the review pages read, keeping the `<stage>/runs/<run>` layout so the bundle can be mounted as `MOSPI_DATA_DIR`. `python scripts/build_demo_data.py --output data/demo` builds the synthetic demonstration bundle.

## 11. Configuration reference

All configuration comes from environment variables. Local secrets go in the git-ignored `.env`; placeholders are in `.env.example`.

| Variable | Purpose |
|---|---|
| `MOSPI_DATA_DIR` | Data root (default `data/`) |
| `MOSPI_FUSION_ROOT`, `MOSPI_PROJECT_ROOT` | Server roots for Fusion runs and the project |
| `MOSPI_HOST`, `MOSPI_PORT` | Bind address and port |
| `MOSPI_SESSION_SECRET` | Signs session cookies (32+ characters) |
| `MOSPI_USERS_DB` | Account file when no database is configured (default `data/auth/users.sqlite`) |
| `MOSPI_REVIEW_ONLY`, `MOSPI_AUDIT_READ_ONLY` | Deployment modes |
| `MOSPI_AUDIT_BACKEND` | `sqlite` (default) or `postgres` |
| `MOSPI_DATABASE_URL` | Runtime connection (`mospi_app` locally, `mospi_reader` hosted) |
| `MOSPI_HOSTED_DATABASE_URL` | Local copy of the hosted reader URL |
| `MOSPI_REVIEW_DATABASE_URL` | Hosted only, optional: `mospi_reviewer` URL that lets the hosted instance record decisions |
| `MOSPI_DB_ADMIN_URL` | Operator tools only: migrations, registry, serving, backups |
| `MOSPI_DB_CA_FILE` | CA certificate for `sslmode=verify-full` |
| `MOSPI_DB_APP_PASSWORD`, `MOSPI_DB_READER_PASSWORD`, `MOSPI_DB_REVIEWER_PASSWORD` | Role passwords for `migrate --roles` (the reviewer role only when its password is set) |
| `MOSPI_DB_SCHEMA` | Schema name (default `mospi`; tests use throwaway schemas) |
| `MOSPI_DB_MAX_CONNECTIONS`, `MOSPI_DB_CONNECT_TIMEOUT`, `MOSPI_DB_STATEMENT_TIMEOUT_MS` | Pool size (5), connect timeout (5 s), statement timeout (15,000 ms) |
| `MOSPI_SERVING_DIR` | Where the hosted serving set is materialised |
| `MOSPI_KEY_HMAC_SECRET` | Keyed hash for record-key overlap detection in uploads |
| `MOSPI_UPLOAD_*` | Upload directory and size limits |
| `MOSPI_CHECK_INTERVAL_MINUTES`, `MOSPI_CHECK_FULL_HASH`, `MOSPI_RERUN_ON_CHANGE`, `MOSPI_FULL_RERUN_DAYS`, `MOSPI_JOB_STALE_SECONDS` | Worker and periodic checks |
| `MOSPI_BACKUP_DIR` | Backup location (default `%LOCALAPPDATA%/MoSPI/backups`) |
| `MOSPI_CODE_VERSION` | Build argument: source commit reported by `/healthz` |
| `MOSPI_EXTRA_CA_FILE` | Proxy CA for Docker builds |

## 12. Security

Implemented:

* Binds to 127.0.0.1 by default. Password sign-in is always required, with three roles. Only scrypt hashes are stored, sessions are signed HttpOnly cookies, and five failed sign-ins lock an account for 15 minutes.
* Role checks on decisions, exports, batches and operations. Every export is logged in the audit trail.
* Append-only, hash-chained audit trail (SQLite and PostgreSQL, same chain formula) with verification on demand and in periodic checks.
* PostgreSQL least-privilege roles, row-level security, and revoked default roles. TLS `verify-full` against a pinned public CA. Pooler-safe per-transaction settings. Bounded pools and timeouts.
* Upload hardening: server-generated paths, size caps, hashing, and no survey values in reports.
* Hosted instance: read-only database role, views only, data fetched only after sign-in, SHA-256 verification of every chunk and file. Optional hosted decisions use a separate insert-only role limited by grants and row-level security.
* Database errors on the hosted instance return a plain message; host names and driver errors go to the log only.
* Secrets only in the environment or the git-ignored `.env`. Pytest uses short tracebacks so connection strings are never printed.

Not provided, and needed before government production use: a GoI-approved identity provider (OIDC/SSO), MoSPI-hosted infrastructure, network controls and TLS termination, security review and scanning, and signed off-site audit digests. Password sign-in is a prototype.

## 13. Evaluation

The platform includes a controlled-injection evaluation instrument (`mospi/evaluation/`), pre-registered in [evaluation/PROTOCOL.md](evaluation/PROTOCOL.md).

* **Injection** (`inject.py`, catalogue `plfs-injection-catalogue-v2`): extra or lost zeros, ×12 and ×100, digit transposition, plausible-but-wrong values, occupation miscodes, hours keying, casual wage ×10, rule-breaking status/earnings and ages, duplicated persons, copied households, fabricated FSUs, short interviews, one-day FSUs. The injection is applied to a copy, and every change is labelled.
* **Metrics** (`metrics.py`): computed on the **CAPI-pass population** (records breaking a hard rule, and rule-type injections, are scored separately). Recall, precision and F0.5 at K = 0.5/1/2/5% and at the budget; average precision; recall by error type and by State; paired-bootstrap differences.
* **Rankings compared:** A0 (superseded V2.0), E1 current peers, E2 earlier periods, E4 expected-value model, B references only, D full value lane, E3 coding lane, E6 operational queue.
* **Runs:** States are split into folds A/B. Seeds 1–5 on fold A are development; seeds 6–20 on fold B are confirmation. All artefacts are kept, and `python -m mospi.evaluation.run --verify <result.json>` recomputes the metrics.

```bash
python -m mospi.evaluation.run --release 2024 --seeds 1-5 --fold A
python -m mospi.evaluation.run --verify data/evaluation/results/protocol_v1/2024_A_seed1.json
```

**Results so far (development only, seed 1, fold A):** the full value lane beats the superseded design by +13.4 (2024) and +14.4 (2025) points of recall at 1%. However, the expected-value model alone beats the full lane by 2.9 and 6.4 points, so acceptance criterion 1 is not met on development data. Coding-lane recall at 5% is 82% / 69% (criterion met). Rule recall is 100%. The confirmation runs have **not** been run. The design must be re-frozen first.

## 14. Testing

```bash
python -m pytest                       # default suite, no database or real data needed
python -m pytest -m realdata --realdata   # opt-in smoke tests on the stored real runs
python -m pytest --postgres            # opt-in; throwaway schemas in the configured PostgreSQL, never "mospi"
```

Current result (13 Oct 2026, default suite plus `--postgres` against a local PostgreSQL 17): **199 passed, 16 skipped** (15 opt-in real-data tests, and one test that needs Supabase's own `anon`/`authenticated` roles). There are 35 PostgreSQL tests; the earlier set has also passed against Supabase. Hosted decisions (`mospi_reviewer`) have been tested on the local server only.

| Area | Tests |
|---|---|
| `tests/stages/<stage>/` | Each stage: contracts, peer construction, tail probabilities, coding check, models, FSU checks, history, rules |
| `tests/fusion/` | Lanes and calibration, queue, case stories, review store, hash chain, concurrency |
| `tests/pipeline/` | Orchestration, QA gates (fault injection), batch jobs with real processes |
| `tests/evaluation/` | Injection labelling, metrics |
| `tests/app/` | Deployment modes, hosted dependency limits, UI contract |
| `tests/postgres/` | Migrations, privileges, RLS, audit parity, migration of SQLite stores, backup drill, uploads, worker, hosted serving |
| `tests/test_realdata.py` | Case pages and readers on every stored real run (opt-in) |

`tests/synthetic.py` builds a small synthetic PLFS delivery used across the suite and for the demo bundle. Tests protect behaviour and audited failure modes. They do not measure detection accuracy.

## 15. Status and known limitations

| Capability | Status |
|---|---|
| Preparation, integrity rules, peer groups, value/coding/FSU/historical evidence, lanes, queue, impact, case stories | Implemented and tested. Detection value not yet confirmed (evaluation confirmation pending) |
| Review workflow, decision taxonomy, hash-chained audit, feedback report | Implemented and tested |
| Batch validation from the UI; Upload & validate with worker and periodic checks | Implemented and tested |
| PostgreSQL operational store (Supabase); hosted review-only instance | Implemented, deployed and verified (12 Oct 2026) |
| Review budget (1%) and lane shares | Provisional defaults until HSD supplies review capacity |
| District code rule before 2025 | Limited: the supplied pre-2025 list predates 54 codes used in 2024 |
| Soft rules S01, S02 | Drafts, inactive until HSD approval; no rule-authoring UI |
| Known-events calendar | Empty until HSD supplies events |
| Revisit lane (2023-24 linked changes) in the queue | Not done (computed, not queued) |
| Earnings deflation | Not done (no approved deflator) |
| Excel/PDF reports | Not done (CSV export only) |
| Enumerator analytics | Not possible: no investigator code in the released files |
| Related-survey validation | Not possible: no approved related dataset |
| Same month last year for 2025 | Not possible until 2026 releases exist |
| Real-time eSigma integration | Later stage; see [specification/ESIGMA_INTEGRATION_ROADMAP.md](specification/ESIGMA_INTEGRATION_ROADMAP.md) |
| Real-world precision and miss rate | Needs an HSD pilot with pre-scrutiny data and supervisor decisions |

Hosting limits (Supabase Free and Vercel Hobby): the database pauses after about 7 days of inactivity; storage is 500 MB (about 137 MB used); egress is 5 GB per month (about 40 cold starts of the 115 MB serving set). Teardown steps are in [deployment/POSTGRESQL.md](deployment/POSTGRESQL.md) §11.

## 16. Further reading

| Document | Contents |
|---|---|
| [specification/10_10_IMPROVEMENT_PLAN.md](specification/10_10_IMPROVEMENT_PLAN.md) | Master method specification and work-item status |
| [specification/V2_COMPLETION_AND_IMPLEMENTATION_REPORT.md](specification/V2_COMPLETION_AND_IMPLEMENTATION_REPORT.md) | Calibration corrections, measured burden, development evaluation |
| [stages/](stages/) | Per-stage README, DESIGN and VALIDATION_REPORT |
| [evaluation/PROTOCOL.md](evaluation/PROTOCOL.md) | Pre-registered evaluation protocol and run log |
| [deployment/](deployment/) | Docker, PostgreSQL/Supabase, Vercel |
| [audits/AUDIT_2026-10-03.md](audits/AUDIT_2026-10-03.md) | The pre-V2 audit that motivated the redesign |
| [research/](research/) | PLFS data research foundation and the original architecture design |
