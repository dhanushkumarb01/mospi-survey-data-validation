# Implementation plan: PostgreSQL, hosted parity and automated CSV validation for the V2.2 platform

**Status:** PLAN ONLY, for review. Nothing described here has been implemented, migrated, deployed or run against real data.
**Written:** 10 October 2026, against git `fac8ac3` (working tree clean at the start of the inspection).
**Audience:** the project owner and faculty guide who will approve (or change) the decisions in §17 before any work starts.
**Scope rule:** everything below extends the existing V2.2 tree in place (README, `docs/10_10_IMPROVEMENT_PLAN.md` §9–10). No V3, no parallel service tree, no change to any validation engine, score, calibration, queue order or stored run.

---

## 0. How to read this document

Every factual statement carries one of these tags.

| Tag | Meaning |
|---|---|
| **[V]** | Verified today by reading the repository files named, or by a read-only count (see §0.2). |
| **[D]** | Stated in an existing repository document (for example a measurement or a vendor limit) and **not** re-checked today. |
| **[E]** | From an external web page found today. The link is in §19. |
| **[A]** | Assumption. It drives a recommendation and is repeated in §18 so you can reject it. |
| **[U]** | Unverified. A named spike (§13, P0) must settle it before the dependent work starts. |

### 0.1 What the inspection covered

Read in full: `fusion/review.py`, `fusion/api.py`, `fusion/serve.py`, `fusion/vercel_app.py`, `pipeline/jobs.py`, `pipeline/run.py`, `pipeline/qa.py`, `preprocessing/pipeline.py`, `preprocessing/config.py`, `survey_rules/schema.py`, `scripts/export_serving_data.py`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `pyproject.toml`, `vercel.json`, `.vercelignore`, `.gitignore`, `.dockerignore`, `conftest.py`, `README.md`, and `docs/DOCKER.md`, `docs/VERCEL_REVIEW_ONLY_DEPLOYMENT.md`, `docs/VERCEL_COMPATIBILITY_AUDIT.md`, `docs/ESIGMA_INTEGRATION_ROADMAP.md`. Read in part: `fusion/engine.py`, `fusion/explain.py`, `fusion/ui/app.js`, `fusion/ui/index.html`, `statistical/engine.py`, `docs/10_10_IMPROVEMENT_PLAN.md` §9–10, tests in `fusion/tests/` and `pipeline/tests/`.

### 0.2 What was deliberately not done

* No code or project file was changed. This file is the only file created.
* No test suite was run (the pytest cache and bytecode would be written). The last recorded result is "155 passed, 15 skipped (opt-in real-data)" **[D]** `docs/VERCEL_REVIEW_ONLY_DEPLOYMENT.md` §8.
* No database was contacted and nothing was migrated or deployed.
* No survey row was read. The only data reads were: `COUNT(*)` and event-type counts on the 11 `review_audit.sqlite` files, opened with `mode=ro` (no content columns); the small aggregate `fusion_report.json` files of the three V2.2 runs; one job record `pipeline/jobs/*.json`; file listings and sizes.

---

## 1. Executive summary

**What can be done.** All seven areas of the brief can be delivered inside the existing V2.2 application. The recommended shape is:

1. **PostgreSQL holds operational state only**: the review audit trail (hash chain preserved byte-for-byte), a run registry, upload and dataset ledgers, job and attempt records, and notifications. It does **not** hold survey rows. Parquet and DuckDB stay the analytical store (§4).
2. **Local and hosted instances read the same review records** from PostgreSQL. The hosted instance uses a SELECT-only database role, so "hosted is read-only" is enforced by the database as well as by the application (§6).
3. A **new "Upload & validate" page** lets an administrator upload a CSV, see a pre-flight report (schema, column mapping, duplicates), and **manually confirm** validation. A worker then runs the **existing, unchanged** `preprocessing` and `pipeline.run` code, registers the new run, and publishes it (§7–§8).
4. Failures raise persistent in-app alerts, are tracked per attempt, and can be retried safely because pipeline stages are already immutable and resumable (§9).

**Five findings you should know before approving anything** (all verified):

| # | Finding | Why it matters |
|---|---|---|
| F1 | The **real review record set is tiny today**: across all 11 audit stores there are **32 events: 1 decision, 25 case-views and 6 chain-start markers**. The only decision is in a superseded V1 run (`2024_first_visit_2024_first_v1`). **[V]** | "Exact same real records" is mostly a requirement on the *future*; migrating today's data is small and cheap. The one decision's origin (genuine review or test) must be classified by you (D5). |
| F2 | `docs/VERCEL_COMPATIBILITY_AUDIT.md` §3 says two stores hold recorded decisions (`2024_first_visit_v2`, `..._v1_clean`). Today's read-only count shows those two hold **only case-views (11 each)**. **[V]** | The earlier statement is out of date or mis-stated. Treat today's count as the baseline and re-count immediately before migration. |
| F3 | The hosted app **cannot see real review outputs today by design**. `fusion/vercel_app.py` serves only `demo-data/` (synthetic, `"synthetic": true`), and `.vercelignore` is an allowlist that excludes every `*/runs/` folder, all `*.sqlite`, and every package not listed. **[V]** | Hosted parity needs a deliberate publish path and a hosting decision (§6). It will not happen by adding a database alone. |
| F4 | On Vercel Functions, a **new run is visible only after a redeploy** (data ships in the deployment), and the real 2025 serving set (≈777 MB **[D]**) plus dependencies (≈386 MB **[D]**) exceeds the documented 500 MB function limit unless Large Functions (beta) are used **[U]**. | "Hosted dashboard refresh" has two honest answers: redeploy on publish (Vercel) or a writable data volume (container host). See H-A vs H-B in §6. |
| F5 | The **default Docker `app` container cannot run batches or accept uploads**: its root filesystem is read-only and only `fusion/runs` is writable; `preprocessing/runs`, `peer_groups/runs` and `pipeline/jobs` are not writable mounts. **[V]** (`docker-compose.yml`) | Automation needs a separate worker service with writable volumes (§8.3), not a change inside the `app` container. |

**Effort.** About **60–90 person-days** (≈12–18 calendar weeks for one developer), ±30 %, in nine phases with exit gates (§13). Phases 0–2 (approvals, PostgreSQL audit store, migration) are the critical, high-risk core and are about 20–28 person-days on their own.

**Hard preconditions (non-technical).** (a) Written authority for any real or pre-scrutiny unit-level data to leave the processing machine; (b) a decision on where PostgreSQL runs; (c) your answers to the 20 decisions in §17. Until they exist, hosted work proceeds with **synthetic data only**.

---

## 2. Verified baseline (what exists today)

### 2.1 Architecture in one table

| Concern | Current implementation | Evidence |
|---|---|---|
| Analytical store | Immutable Parquet runs per stage, read in place with DuckDB (`read_parquet`), no database | `fusion/api.py` (`FusionRepository.query`), `pipeline/run.py` **[V]** |
| Review/audit store | **One SQLite file per Fusion run**: `fusion/runs/<run>/review_audit.sqlite`, append-only triggers, SHA-256 hash chain, `BEGIN IMMEDIATE` serialisation | `fusion/review.py` **[V]** |
| Case identity | `case_id = "case_" + sha256(source_observation_id)[:20]`, deterministic, so a decision stays attached to the same record across restarts | `fusion/engine.py:99` **[V]** |
| Audit call sites | `fusion/api.py` references `review_audit.sqlite` in **13 places**; `fusion/engine.py:361` creates an empty store at the end of every Fusion run; `scripts/export_serving_data.py` copies it | `grep` **[V]** |
| Batch execution | `JobManager.start` spawns `python -m pipeline.jobs run` as a child process; state is `pipeline/jobs/<32-hex>.json` + `.log`; PID liveness; one job at a time; labels `^[a-z0-9][a-z0-9_]{0,23}$`, never overwritten | `pipeline/jobs.py` **[V]** |
| Pipeline | 8 stages, each an immutable directory `<module>/runs/<release>_<observation>_<label>`, per-stage QA gate, **resume**: an existing stage directory with `run_metadata.json` is reused; a directory without it raises "inspect and remove it before resuming" | `pipeline/run.py:97-116`, `pipeline/qa.py` **[V]** |
| Preparation | Release-specific `DatasetContract`s (4: 2023_24 first/revisit, 2024 first, 2025 first), fixed raw file paths, required column names, expected column counts, **no header whitelist configured** (warning `FULL_HEADER_WHITELIST_UNCONFIRMED`), key duplicates flagged and retained, nothing dropped or corrected | `preprocessing/config.py`, `preprocessing/pipeline.py` **[V]** |
| Upload | **None, by design.** `/api/batch/inputs` returns `upload.available = false` with a reason | `fusion/api.py:651` **[V]** |
| Auth | Optional bearer tokens (SHA-256 in a users file or `MOSPI_USERS_JSON`), roles `supervisor`/`technical`/`admin`; hosted entrypoint forces sign-in | `fusion/api.py:165-228`, `fusion/vercel_app.py` **[V]** |
| Hosted | `fusion.vercel_app:app`: always `review_only=True`, `audit_read_only=True`, sign-in required; data = `demo-data/` (synthetic, 1.2 MB). **Nothing has been deployed to Vercel** | `fusion/vercel_app.py`, `docs/VERCEL_REVIEW_ONLY_DEPLOYMENT.md` **[V]/[D]** |
| PostgreSQL | Not used. Planned as a "later stage" in `docs/10_10_IMPROVEMENT_PLAN.md` §10 (operational state only, "analytical data stays in Parquet", "no destructive migration", W7.1/W7.7) | **[V]** |
| Dependencies | `requirements.txt` has no database driver and no `python-multipart`. `psycopg 3.2.3` and `SQLAlchemy 2.0.36` are installed in the local environment but **not pinned** in the project | `pip list` vs `requirements.txt` **[V]** |
| Local tooling | Python 3.11.9, Docker 29.2.1, PostgreSQL 17 client/server binaries (`psql`, `pg_ctl`) present on this machine. Whether a server is running was not checked | **[V]** |

### 2.2 The audit stores, counted today (read-only)

| Fusion run | Format | Events | Decisions | Case-views | Chain starts |
|---|---|---:|---:|---:|---:|
| `2023_24_first_visit_2023_24_first_v1_clean` | legacy (8 columns, no chain) | 0 | 0 | 0 | 0 |
| `2023_24_first_visit_v2` | legacy | 0 | 0 | 0 | 0 |
| `2023_24_first_visit_v2_2` | chained (19 columns) | 1 | 0 | 0 | 1 |
| `2024_first_visit_2024_first_v1` | legacy | 1 | **1** | 0 | 0 |
| `2024_first_visit_2024_first_v1_clean` | legacy | 11 | 0 | 11 | 0 |
| `2024_first_visit_v2` | legacy | 11 | 0 | 11 | 0 |
| `2024_first_visit_v2_1` | chained | 1 | 0 | 0 | 1 |
| `2024_first_visit_v2_2` | chained | 1 | 0 | 0 | 1 |
| `2025_first_visit_v2` | chained | 4 | 0 | 3 | 1 |
| `2025_first_visit_v2_1` | chained | 1 | 0 | 0 | 1 |
| `2025_first_visit_v2_2` | chained | 1 | 0 | 0 | 1 |
| **Total (11 stores)** | | **32** | **1** | **25** | **6** |

Hash-chain integrity (`verify_chain`) was **not** run today; the migration phase runs it before and after (§11).

### 2.3 Properties of the hash chain that the PostgreSQL design must preserve exactly

These come from `fusion/review.py` **[V]** and are the reason the schema in §5.2 is shaped as it is.

1. `event_hash = sha256(previous_hash + "|" + json.dumps({HASHED_FIELDS}, sort_keys=True, separators=(",", ":"), default=str))`. `HASHED_FIELDS` are 16 columns: `case_id, event_type, actor, event_timestamp_utc, decision, comment, evidence_snapshot_json, reason_code, verification_source, corrected_field, corrected_value, lane, opened_at_utc, seconds_on_case, actor_authenticated, actor_role`. `event_id`, `previous_hash`, `event_hash` are **not** hashed.
2. Consequences for column types: timestamps are **TEXT** ISO strings inside the hash, so they must stay TEXT (a `timestamptz` round-trip changes the string and breaks the hash). `evidence_snapshot_json` must be **TEXT, not JSONB** (JSONB reorders and normalises). `actor_authenticated` is an integer 0/1 inside the JSON (a boolean would hash as `true`). `seconds_on_case` must be **double precision** (a 4-byte `real` changes the digits).
3. The chain is **per Fusion run**, starting from `"GENESIS"`, and `event_id` is per run and visible to the UI (`expected_last_decision_id`, the "Audit history" table). The migrated table therefore needs a composite key `(run_id, event_id)`, not a global identity.
4. Legacy rows (written before the chain existed) are never rewritten: the first chained event `AUDIT_CHAIN_STARTED` seals them with a digest of their first 8 columns. `verify_chain` re-derives that seal.
5. Concurrency: appends are serialised (`BEGIN IMMEDIATE`) so two writers cannot fork the chain; a decision may carry `expected_last_decision_id` and gets a 409 on a stale view. Both behaviours are tested (`fusion/tests/test_deployment.py`) and must hold on PostgreSQL.
6. Decision legacy aliases (`CONFIRMED_ISSUE`, `CONFIRMED_VALID`, `INCONCLUSIVE_NEEDS_FOLLOW_UP`) are mapped at read time only.

---

## 3. Requirements and constraints mapped to design rules

| Your restriction / requirement | Design rule |
|---|---|
| Do not modify code in this task | This task changed nothing but this file. Implementation starts only after §17 is approved. |
| No V3, preserve the architecture | New code lives in new packages (`db/`, `ingestion/`) and thin, additive edits to existing files (§15). Engines, `pipeline/run.py`, `pipeline/qa.py`, `preprocessing/` and `integrity/` are unchanged. |
| Preserve V2.2 functionality and historical records | SQLite remains a supported backend (default). PostgreSQL is selected by configuration. Original SQLite files are never opened for writing, altered or deleted. Full rollback to SQLite is a tested procedure (§12). |
| No lost review history or audit integrity | Rows are copied verbatim (ids, timestamps, hashes), chain verified before and after, per-file reconciliation recorded in the database (§11). |
| PostgreSQL need not store every survey row | Decision D1: it does not. Options evaluated in §4. |
| Hosted dashboard shows the same real review records | Same database (topology T1) or an idempotent one-way sync that preserves ids and hashes (T2), plus a parity endpoint and script (§6.5). |
| Verify how hosted accesses generated review outputs | §6.1–§6.4: verified facts, the gap, and the options. |
| Do not assume real data is authorised for public hosting | Gate G-AUTH in §10 and §13. Until it passes, hosted instances show synthetic data only and the publish step refuses non-synthetic targets. |

---

## 4. Does PostgreSQL need to store the survey rows? (evaluation)

| Option | What PostgreSQL holds | Verdict |
|---|---|---|
| **S1: operational state only** (recommended) | Audit events, run registry, publish records, upload/dataset/job ledgers, notifications, mapping profiles, migration records. | Matches the project's own plan ("analytical data stays in Parquet", `10_10_IMPROVEMENT_PLAN.md` §10 and line 1246) **[V]**. Small (< 5 GB for years **[A]**, see §10.4), fast to back up, no duplication of unit-level data. |
| S2: S1 + a light queue index | S1 plus `(run_id, case_id, tier, queue_position, priority_score, state, fsu)` for tier A/B cases only (3,110 + 8,364 for 2023-24; 3,079 + 8,312 for 2024; 7,634 + 22,974 for 2025 **[V]** `fusion_report.json`). | Useful only if the UI needs to join decisions to the queue inside SQL (it does not today: it joins in Python). Defer; revisit if review-status filtering becomes slow (§5.5). |
| S3: all survey/case rows | 418,159 + 415,549 + 1,148,634 person-level cases **[V]**, plus evidence tables (`value_evidence.parquet` alone is 78–212 MB **[D]**). | **Not recommended.** It duplicates the Parquet store, multiplies the amount of unit-level data held in a database that must be secured and backed up, replaces fast columnar DuckDB scans with row storage, and creates a second source of truth that can drift from the immutable runs. No requirement in the brief needs it. |

Rule: **a stored run stays immutable and is read from Parquet; PostgreSQL only records what happened to it** (who reviewed what, which file arrived, which job ran, what was published).

---

## 5. Workstream A: PostgreSQL integration

### 5.1 Principles

1. **Backend abstraction, not a rewrite.** A new module `fusion/audit_store.py` defines the five operations the API already uses (`append_event`, `history`, `latest_statuses`, `all_events`, `verify_chain`) plus `register_run`. `SqliteAuditStore` delegates to the existing functions in `fusion/review.py` (unchanged). `PostgresAuditStore` is new. `create_app(...)` receives a store factory; the 13 `directory / "review_audit.sqlite"` expressions in `fusion/api.py` become `store.for_run(directory)`.
2. **Selection by configuration**: `MOSPI_AUDIT_BACKEND=sqlite` (default, current behaviour) or `postgres`. There is **no dual-write mode**: two writable copies of one chain is exactly the divergence this plan exists to prevent.
3. **No silent fallback.** In PostgreSQL mode, if the database is unreachable, decisions are refused with a plain message; they are never written to a local SQLite instead.
4. **Dependencies stay minimal**: add `psycopg[binary]` (pinned, 3.2.x) only. No SQLAlchemy, no Alembic. Migrations are numbered SQL files applied by a ~60-line runner that records them in `schema_migrations` (decision D14). The pin must appear identically in `requirements.txt` and `pyproject.toml` (enforced by `test_vercel_packaging_matches_the_docker_dependencies` **[V]**).
5. **Serverless-safe connections** (hosted on Vercel): short-lived connections to a pooled endpoint, `prepare_threshold=None` (transaction-pooling poolers reject server-side prepared statements), only transaction-scoped advisory locks **[A]**.

### 5.2 Schema (draft; final DDL is a P1 deliverable)

```sql
-- migrations/0001_audit.sql
CREATE TABLE audit_events (
  run_id                text    NOT NULL,          -- Fusion run directory name, e.g. 2024_first_visit_v2_2
  event_id              bigint  NOT NULL,          -- per run, preserved from SQLite for migrated rows
  case_id               text    NOT NULL,
  event_type            text    NOT NULL,
  actor                 text    NOT NULL,
  event_timestamp_utc   text    NOT NULL,          -- TEXT on purpose: inside the hash
  decision              text, comment text,
  evidence_snapshot_json text,                     -- TEXT on purpose (not JSONB): inside the hash
  reason_code text, verification_source text, corrected_field text, corrected_value text, lane text,
  opened_at_utc         text,
  seconds_on_case       double precision,
  actor_authenticated   smallint,
  actor_role            text,
  previous_hash         text,                      -- NULL only for legacy, un-chained rows
  event_hash            text,
  PRIMARY KEY (run_id, event_id)
);
CREATE INDEX audit_case_idx     ON audit_events (run_id, case_id, event_id);
CREATE INDEX audit_decision_idx ON audit_events (run_id, case_id, event_id) WHERE event_type = 'DECISION_MADE';
-- Append-only, twice over:
CREATE FUNCTION audit_reject() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'audit trail is append-only'; END $$ LANGUAGE plpgsql;
CREATE TRIGGER audit_no_update BEFORE UPDATE OR DELETE ON audit_events FOR EACH ROW EXECUTE FUNCTION audit_reject();
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_events FOR EACH STATEMENT EXECUTE FUNCTION audit_reject();
REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM PUBLIC;
```

Operational tables (migration `0002`–`0004`), all with `created_utc timestamptz`, all append-or-status-only:

| Table | Purpose | Key columns |
|---|---|---|
| `runs` | Registry of Fusion runs the system knows | `run_id` PK, `release`, `observation`, `fusion_version`, `dataset_id` (null for pre-existing runs), `code_version`, `fused_cases_sha256`, `status` (`REGISTERED`/`PUBLISHED`/`WITHDRAWN`) |
| `published_runs` | One row per (target, run) publish | `target`, `run_id`, `manifest_sha256`, `status`, `published_by`, `published_utc` |
| `uploads` | Every received file | `upload_id` (32 hex), `sha256`, `size_bytes`, `display_name` (sanitised, never used as a path), `contract_name`, `level`, `status`, `uploaded_by`, `uploaded_by_verified`, `retention_until` |
| `datasets` | A validated set of uploads (household + person) | `dataset_id`, `contract_name`, `fingerprint`, `record_counts`, `preparation_run_id`, `label` |
| `mapping_profiles` | Versioned header-mapping templates | `profile_id`, `contract_name`, `level`, `version`, `mapping_json`, `status` (`DRAFT`/`APPROVED`/`RETIRED`), `approved_by` |
| `jobs` | Ledger of ingestion/validation/publish jobs | `job_id` (32 hex, same shape as today's), `kind`, `dataset_id`, `attempt`, `parent_job_id`, `status`, `error_class`, `error_message` (sanitised), `idempotency_key` UNIQUE, timings, `code_version`, `actor` |
| `job_events` | Per-stage progress trail | `job_id`, `seq`, `stage`, `status`, `message` (sanitised) |
| `notifications` | Persistent alerts | `severity`, `job_id`, `kind`, `message`, `acknowledged_by`, `acknowledged_utc` |
| `audit_verifications` | Result of each chain verification | `run_id`, `status`, `events`, `last_hash`, `checked_utc`, `checked_by` |
| `migration_records` | One row per migrated SQLite file | `run_id`, `source_sha256`, `source_events`, `migrated_events`, `last_hash_before`, `last_hash_after`, `verified_utc` |
| `schema_migrations` | Applied migrations | `version`, `applied_utc`, `checksum` |

### 5.3 Roles and privileges

| Role | Used by | Privileges |
|---|---|---|
| `mospi_owner` | Migration runner only (an operator, not a service) | Owns the schema. Not used at runtime. |
| `mospi_writer` | Local/processing instance, worker | `INSERT, SELECT` on `audit_events`; `INSERT, SELECT, UPDATE` on ledger tables; **no** `UPDATE/DELETE/TRUNCATE` on `audit_events` |
| `mospi_reader` | Hosted instance | `SELECT` on `audit_events`, `runs`, `published_runs`, `jobs`, `audit_verifications`; **no** access to `uploads`, `mapping_profiles`, `notifications`. A view `audit_events_hosted` can omit `evidence_snapshot_json` and `comment` if D18 says hosted must not see them. |

TLS with `sslmode=verify-full` for every non-local connection. Connection strings only from environment variables; never logged (the existing code already avoids echoing `MOSPI_USERS_JSON`, and the same discipline applies).

### 5.4 Append algorithm (PostgreSQL equivalent of `BEGIN IMMEDIATE`)

```
BEGIN;
SELECT pg_advisory_xact_lock(hashtextextended(:run_id, 0));          -- one writer per run's chain
-- decisions only: optimistic check, same semantics as today
SELECT MAX(event_id) FROM audit_events WHERE run_id=:r AND case_id=:c AND event_type='DECISION_MADE';
   -- differs from expected_last_decision_id  ->  ROLLBACK, return 409 (DecisionConflict)
SELECT event_id, event_hash FROM audit_events WHERE run_id=:r AND event_hash IS NOT NULL ORDER BY event_id DESC LIMIT 1;
INSERT INTO audit_events (... event_id = COALESCE(MAX(event_id),0)+1, previous_hash = <last or 'GENESIS'>,
                          event_hash = digest(previous_hash, event)) ...;   -- digest computed in Python by the same _digest code
COMMIT;
```

The digest function is **imported from `fusion/review.py`**, not re-implemented, so SQLite and PostgreSQL cannot drift. A property test appends the same event sequence (with an injected clock) through both backends and asserts identical hashes (§14).

`register_run(run_id)` mirrors `_initialise`: under the same lock, if the run has no chained event, insert `AUDIT_CHAIN_STARTED` sealing any existing legacy rows with the same digest formula. It is idempotent.

Note: `fusion/engine.py:361` still creates an empty `review_audit.sqlite` for every new run. In PostgreSQL mode that file is **inert** (never read). It is left alone because changing the engine is out of scope **[V]**; it is documented, not removed.

### 5.5 Performance considerations

* `latest_statuses` is called on most list pages (`case_rows`, overview, worklist, feedback). With SQLite each call opens a file; with PostgreSQL it is one query per request, and the result should be cached for the duration of the request. At today's volume (≤ 1 decision) this is irrelevant; the design target is ≤ 100,000 events per run **[A]**.
* The review-status filter builds `case_id IN (SELECT UNNEST(?))` lists from decided cases. This is fine into the tens of thousands; beyond that, option S2 (queue index) or a `case_status` view is the remedy (§4). Measure in P2, do not pre-build.
* `all_events` loads every event of a run into memory (as today). Acceptable at the target volume; paginate if a run exceeds it.

### 5.6 Where PostgreSQL runs (decision D2)

| Option | Notes |
|---|---|
| **P-L: local PostgreSQL 17** on the processing machine (present here **[V]**) or the Compose `postgres` service | Zero third-party exposure. The data directory must **not** sit in a OneDrive-synced folder (the repository itself does, see §10.1). Required for development and CI in every scenario. |
| P-I: institutional/approved PostgreSQL | What the roadmap assumes for the later MoSPI stage (`ESIGMA_INTEGRATION_ROADMAP.md`, "GoI hosting … encryption at rest") **[V]**. Needs an owner and a network path. |
| P-M: managed third-party (for example Neon through the Vercel Marketplace) | Vercel's marketplace databases are operated by third parties **[D]/[E]**. Region choice (Mumbai availability) and current free-plan limits were **not** confirmed by the search today **[E]/[U]**. Only with explicit approval (D2, D4). |

Recommendation: **P-L for development, test and the system of record** until an institutional host exists; P-M only for a synthetic-data demo, never for real review records without D4.

---

## 6. Workstream B: the hosted dashboard shows the same real review records

### 6.1 Verified facts about the hosted path

1. `fusion/vercel_app.py` builds the app with `root = MOSPI_DATA_DIR or "demo-data"`, `review_only=True`, `audit_read_only=True`, `require_authentication=True` (or anonymous only if the manifest says `"synthetic": true`). **[V]**
2. `demo-data/SERVING_DATA_MANIFEST.json` says `"synthetic": true`, `"review_audit_included": false`, one run `2024_first_visit_demo`, 1.14 MB. **[V]**
3. `.vercelignore` is an **allowlist**: only `fusion/ survey_rules/ integrity/ pipeline/ preprocessing/ peer_groups/ pattern/ demo-data/ requirements.txt pyproject.toml vercel.json` upload; `/*/runs/`, `*.sqlite`, `*.csv`, `*.parquet`-bearing run folders are excluded. Any **new top-level package** (such as `db/`) must be added or the hosted import fails. **[V]**
4. The documented route for approved real results is manual: export with `--without-audit`, add `!/serving-data/` to `.vercelignore` for that deployment only, deploy from the CLI, set `MOSPI_DATA_DIR`. Size limits: 500 MB function bundle; Large Functions beta; CLI upload 100 MB Hobby / 1 GB Pro. **[D]** The per-run serving sets are 315 / 319 / 777 MB (2023-24 / 2024 / 2025) **[D]**.
5. `FusionRepository.runs()` lists runs by globbing the data directory on every request, and `SourceResolver.run_dir` is `lru_cache`d **including `None` results** (`fusion/explain.py:223`). A run directory that appears before its source runs are complete would be listed and its missing sources cached until restart. **[V]**
6. The audit file for the hosted app would be read from `<run>/review_audit.sqlite` inside the deployment; `audit_read_only` makes writes impossible. Real review history therefore reaches the hosted app only if the SQLite file is shipped, and it is then a **frozen copy** at deploy time, not live. **[V]**

**Conclusion (verified):** today the hosted app cannot show real review outputs or real review records. It shows a synthetic demo. Parity needs (i) the runs, (ii) the review records, and (iii) a way to keep both current.

### 6.2 Two independent parity problems

| Problem | Moves how often | Solution |
|---|---|---|
| **Review records** (decisions, case-views, exports) | Continuously, as supervisors work | PostgreSQL. With T1 the hosted app reads the same database live; with T2 an idempotent sync copies events (§6.3). **No redeploy needed** for review records. |
| **Run outputs** (Parquet, reports) | Once per validated batch | Publish step (§6.4): atomic, checksummed, registered. May need a redeploy (H-A) or not (H-B). |

### 6.3 Database topology for the review records

| Topology | Description | Parity | Exposure |
|---|---|---|---|
| **T1: single database** | One PostgreSQL; local app uses `mospi_writer`, hosted app uses `mospi_reader`. | Exact and live. | The database must be reachable from both sites and holds evidence snapshots (survey values). Acceptable only on infrastructure approved for that data. |
| **T2: primary + one-way sync** | System of record stays on the processing side. `scripts/sync_audit.py` copies new events `(run_id, event_id)` to the hosted database, preserving ids, timestamps and hashes, idempotently, then asserts that the last chain hash and event count match. | Exact up to the last sync; the hosted UI shows "records as of <time>, chain head <hash prefix>". | Hosted database can be restricted to a redacted column set. Raw evidence snapshots never leave the primary. |

**Recommendation:** T2 when the hosted tier is a third-party cloud (Vercel, Neon); T1 when both tiers run on one approved infrastructure (H-B). The code supports both from the same `PostgresAuditStore`.

Hosted decision-writing stays **off** (decision D6 keeps the previous rule "hosted = review-only, decisions only local"). The reader role makes this a database-level guarantee. If you later want hosted decisions, the PostgreSQL store removes the old blocker (the missing Python Blob conditional write): the lock-and-append algorithm needs no object-store compare-and-swap. It would need real user identity (token per person) and D4.

### 6.4 How the hosted app gets the run outputs (decision D3)

| Option | Mechanism | Pros | Cons |
|---|---|---|---|
| **H-A: Vercel Functions** | Publish step stages a verified bundle; a deploy hook redeploys; build copies the bundle into the function. New run visible after redeploy (minutes). | Already built and tested for synthetic data; instant rollback by redeploy. | 2025 run + dependencies exceed 500 MB unless Large Functions **[U]**; Pro plan needed for named access **[D]**; Hobby licence is "non-commercial personal use" **[D]**; unit-level data on a US provider needs written approval (region `bom1` availability **[U]**); no uploads (4.5 MB body limit **[D]**, and review-only). Redeploy per published run. |
| **H-B: the existing Docker image on one approved host** (recommended for real data) | Same image and compose file already in the repository. Publish step copies the verified run into the host's data volume (`seed` already does this idempotently, never overwriting). `/api/runs` sees it at once. PostgreSQL on the same host (T1). | No bundle limit; writable volumes for uploads and the worker; same code path as today's supported Docker deployment; matches the roadmap ("Compose on one approved VM is enough for a pilot", `10_10_IMPROVEMENT_PLAN.md` §9 **[V]**). | Needs a host, TLS reverse proxy, backups and identity controls (all listed as "not provided" in `docs/DOCKER.md` **[V]**). Departs from the earlier "Vercel only" constraint, so it needs your approval. |
| H-C: Vercel + object storage read at runtime (DuckDB `httpfs`) | Runs live in a private bucket; no redeploy. | Would remove the redeploy. | Entirely **[U]** (extension availability in the runtime, private-bucket authentication, request costs). Spike only. |

**Recommendation.** Keep Vercel (H-A) for the **synthetic demo and review-only previews**. For **real review records and real runs**, prefer **H-B**. Build the publish step, registry and parity check once; both targets use them.

### 6.5 Proving parity (acceptance, not hope)

* **Run parity:** every published run has a manifest listing each served file with its SHA-256 and the run's `fused_cases.parquet` hash. The hosted side re-hashes after copy and refuses to register on any mismatch.
* **Review parity:** `GET /api/parity` (roles `technical`/`admin`) returns, per run, `event_count`, `last_hash`, `decided_cases`, `fused_cases_sha256`, `code_version`, `as_of`. `scripts/verify_parity.py --local <url> --hosted <url>` compares both sides and exits non-zero on any difference. It also samples N case pages (configurable) and compares the review fields.
* **Chain parity:** both sides run `verify_chain`; both must report `INTACT` with the same `last_hash`.
* This check runs automatically after each publish and sync, and its result is stored in `audit_verifications` and shown on the hosted overview ("Records verified identical to the processing site at <time>").

### 6.6 Publish step details

`scripts/publish_run.py --run <fusion_run> --target <name>` (new; reuses `scripts/export_serving_data.export`):

1. Preconditions: run exists, passed all QA gates (job ledger says `COMPLETED`), run is registered in `runs`, target is allowed for the data class (non-synthetic requires G-AUTH, §10).
2. Stage to `<target>/.incoming/<run>/` — **source runs first, the Fusion directory last**, then an atomic rename. This is required by fact 5 above (otherwise a half-copied run could be listed and its missing sources cached).
3. Write the manifest, verify checksums, insert `published_runs`, flip `runs.status`.
4. H-A only: call the deploy hook; wait for a healthy `/healthz` with the new `default_run`; if it fails, keep the previous deployment live (Vercel promotes only successful builds **[A]**).
5. Run the parity check (§6.5); record result.

`export_serving_data.py` today iterates over **all** Fusion runs; it needs an additive `--run` filter and SHA-256 manifest entries. Its existing `--keep-existing` rule (never overwrite) stays.

---

## 7. Workstream C: "Upload & validate" page

### 7.1 What the code allows (verified constraints that shape the feature)

1. **Preparation is contract-driven.** `PLFSPreprocessor` reads exactly two files per delivery (household and person) at fixed relative paths inside `input_root`, requires every column named in the contract, and treats raw headers as release-specific ("raw headers must never be treated as a pooled schema") **[V]**. An upload therefore must be matched to a **registered contract** (one of the four today). A CSV in an unknown layout needs a new contract (a code/config change owned by HSD review), not a UI mapping.
2. **"Column mapping" therefore means mapping to a contract's expected raw headers**, for example when a supplied file renames a header. The mapping is stored as a versioned, approved profile and applied by writing a **derived copy** whose header row is rewritten and whose data bytes are untouched. The original upload stays immutable. Free-form mapping to arbitrary schemas is **not** proposed (decision D8).
3. **Preparation works on an `input_root`.** Staging the files as `uploads/<upload_id>/<contract.household_path>` and `.../<contract.person_path>` lets the existing `PLFSPreprocessor` run unchanged. `output_dir.mkdir(exist_ok=False)` also makes preparation idempotent-safe.
4. **The pipeline accepts dynamic inputs.** `run_pipeline(Inputs(prepared, ...), suffix, roots=...)` and `JobManager(root, datasets=...)` already take explicit paths **[V]**. `JobManager` keys datasets by `release`, and matches existing runs by the `release` in each run's metadata. Two uploads of the same contract release would collide on that key, so `pipeline/jobs.py` needs a small additive change: a `dataset_id` distinct from `release` (§15).
5. **Run directory names** are `<release>_<observation>_<label>`; the label must be unique per release/observation. Uploads use a generated label such as `u20261010_01` (≤ 24 characters, matches the existing pattern).
6. **Statistical evidence depends on the delivery's own size.** Peer groups and "current peers" comparisons are built from the prepared file being validated, and earlier periods come from `history` presets **[V]** (`pipeline/run.py` `PRESETS`, `statistical/engine.py` peer-group inputs). A small upload (hundreds of records) will have mostly `NOT_ASSESSABLE` value checks, and the engines' minimum group sizes will not be met. **[A/U]**: whether a "delta batch" can be meaningfully validated against a frozen reference snapshot is **not** supported by the current preset mechanism and is a P0 spike and decision D7. The first release of this feature should accept **complete deliveries** (a full household + person pair for one contract), as the pipeline assumes.
7. **Minimum columns are unknown.** The contract's `person_fields` list only a subset of the ~140 columns; integrity rules and other engines read further raw columns through concept maps (`survey_rules/plfs_integrity.py`). A CSV with only the contract's required columns may pass preparation but degrade or fail downstream. **[U]** P0 spike S3 determines the real minimum per contract.
8. **Browser upload mechanics.** `python-multipart` is not a dependency **[V]**, so standard FastAPI file forms are unavailable. The design streams the body with `request.stream()` (`PUT /api/uploads/{upload_id}/content`, `Content-Type: application/octet-stream`), computes SHA-256 and size on the fly, writes to quarantine, and never buffers the file in memory. The browser sends `fetch(url, {method:'PUT', body: file})`. No new dependency.
9. **Hosted instances never accept uploads.** The route is off unless `MOSPI_UPLOADS_ENABLED=1`, and `fusion/vercel_app.py` hard-codes it off, as it does `review_only`. (Vercel's 4.5 MB request limit **[D]** makes large uploads impossible there anyway.)

### 7.2 User flow ("manual validation")

```
 1 Choose        Pick the survey layout (contract) and the two files (household, person).
 2 Upload        Files stream to quarantine. Page shows size, SHA-256, progress. Nothing else happens.
 3 Pre-flight    Server reads headers only (no pandas full load) and shows a plain-language report:
                   - layout matched / not matched; missing, unexpected and renamed columns; column count vs documented
                   - suggested mapping from an APPROVED profile (never applied silently)
                   - file already received? same content already received? record keys already validated?
                   - row counts, blank-key counts, within-file duplicate keys (counts only, no row values)
 4 Decide        Administrator clicks "Start validation" (manual gate) or "Reject upload".
                   Blocking findings disable the button and say why.
 5 Follow        Progress page: stage list, elapsed time, log tail (sanitised). Leave and come back.
 6 Result        "Review list ready" (opens the new run) or a plain failure with the next step.
```

"Manual validation" is interpreted here as: **a person reviews the pre-flight report and explicitly starts validation**. If you meant something else (for example manual single-record entry, which already exists as `POST /api/validate/record`), say so (D7). Automatic start is a configuration flag, default **off**, because a batch takes 23–47 minutes and 2–3 GB of memory **[D]**, and only one runs at a time **[V]**.

The page follows the existing UI rules: plain language first, technical details behind a disclosure, no invented evidence, the same warm editorial style, and the review-only variant that explains why upload is unavailable (as `batchReviewOnly()` does today). No row values are shown in the pre-flight report by default (D11).

### 7.3 API surface (all new routes inherit the existing auth middleware and must appear in `test_every_api_route_is_covered_by_the_access_test`)

| Route | Role | Purpose |
|---|---|---|
| `GET /api/ingest/contracts` | admin, technical | Supported layouts, required columns, documented counts, active mapping profiles |
| `POST /api/uploads` | admin | Create an upload record (`contract`, `level`, `declared_size`, `Idempotency-Key`) |
| `PUT /api/uploads/{id}/content` | admin | Stream the file |
| `POST /api/uploads/{id}/preflight` | admin | Run header/duplicate pre-flight (async job, fast) |
| `GET /api/uploads`, `GET /api/uploads/{id}` | admin, technical | History and status |
| `POST /api/uploads/{id}/validate` | admin | Manual gate: create the validation job (idempotent) |
| `POST /api/uploads/{id}/reject` | admin | Mark rejected (file kept until retention rule) |
| `GET /api/jobs`, `GET /api/jobs/{id}` | admin, technical | Unified ledger incl. legacy batch jobs |
| `POST /api/jobs/{id}/retry` | admin | Safe retry (§9.3) |
| `GET /api/notifications`, `POST /api/notifications/{id}/ack` | admin, technical | Alerts |
| `GET /api/parity` | technical, admin | §6.5 |

Roles: reuse `admin` for upload/validate/retry (it already gates `POST /api/batch`) and `technical` for read-only follow. No new role unless you ask for one (D11).

---

## 8. Workstream D: the automated workflow

### 8.1 State machine

```
RECEIVED ─► QUARANTINED ─► PREFLIGHT_OK ──(manual "Start validation")──► QUEUED
   │            │               │                                           │
   │            │               └─► PREFLIGHT_BLOCKED (terminal: reject / fix / re-upload)
   │            └─► REJECTED_FORMAT (not CSV, binary, too large, bad encoding)           ▼
   └─► REJECTED_DUPLICATE (L1/L2/L3, §8.2)                                      PREPARING (preprocessing, unchanged)
                                                                                         ▼
                                                                                  PREPARED ─► VALIDATING (pipeline.run via JobManager, unchanged)
                                                                                         ▼                         │
                                                                              REVIEW_OUTPUT_READY ◄────────────────┘ (QA gates passed)
                                                                                         ▼
                                                                                   REGISTERED (runs row + audit chain start in PostgreSQL)
                                                                                         ▼
                                                                  PUBLISHING ─► PUBLISHED ─► PARITY_VERIFIED
                                  failures at any stage: FAILED_<STAGE> / FAILED_QA_GATE / INTERRUPTED  (alert raised, retry rules §9.3)
```

Every transition writes a `job_events` row and, for failures, a `notifications` row. Transitions are monotonic and enforced by a database check so a retry cannot silently skip a stage.

### 8.2 Duplicate protection (five layers, strongest first)

| Layer | Check | When | Outcome |
|---|---|---|---|
| L1 | **File SHA-256** equals an existing `uploads.sha256` | At end of streaming | `REJECTED_DUPLICATE`, shows the earlier upload |
| L2 | **Content fingerprint**: order-independent digest of per-row hashes, computed in one streaming pass | Pre-flight | Detects the same data re-saved (line endings, quoting, row order). Same outcome as L1 |
| L3 | **Record-key overlap** with earlier accepted datasets of the same contract: canonical record keys (the same construction as `MoSPI_record_key`) hashed with an HMAC secret and kept in a per-contract Parquet registry beside the run, **not** in PostgreSQL | Pre-flight | Overlap > 0 **blocks** and reports counts. No silent de-duplication: the project rule is that records are never dropped. Treating overlap as a "revision" is not defined in the current system (revision semantics belong to the eSigma stage) and is therefore out of scope (D9). |
| L4 | **Job idempotency**: `UNIQUE (idempotency_key)` and `UNIQUE (dataset_id, kind)` among non-failed jobs; the UI sends an `Idempotency-Key`; double clicks and retries of the HTTP call create one job | Job creation | Second request returns the first job |
| L5 | **Existing rules**: within-file duplicate expected keys are already flagged by `PLFSPreprocessor` (`DUPLICATE_EXPECTED_KEY`, retained as `not_assessable_key_integrity`); run labels are never overwritten (`JobManager.start`) | Preparation / start | Counted in pre-flight so the user sees them *before* starting |

### 8.3 Execution: worker, not web process

* A new `worker` Compose service (profile `worker`, same image) runs `python -m ingestion.worker`. It claims jobs with `SELECT ... FOR UPDATE SKIP LOCKED` on `jobs` in state `QUEUED`, one at a time (matching the "one job at a time" rule), and calls the **existing** `JobManager.start` and `pipeline.jobs run`, so QA gates, immutability and the label rule behave exactly as today. It mirrors progress from the job JSON/log to `jobs` and `job_events`.
* Writable volumes the worker needs: `uploads/`, `preprocessing/runs`, `peer_groups/runs`, `statistical/runs` … `fusion/runs`, `pipeline/jobs`, `pipeline/runs`. The `app` container keeps its read-only layout.
* Memory: the compose `batch` service already uses 6 GB; peak is 2–3 GB for 2025 **[D]**. Windows Docker Desktop with folder mounts is "much slower" **[D]**; on this Windows machine prefer running the worker natively (`python -m ingestion.worker`) as today's batches are run, or use a Linux host.
* Process safety on Windows and Linux is already handled by `_alive` and `INTERRUPTED` detection **[V]**.

### 8.4 After the pipeline: "review-output generation" and "hosted refresh"

* The review outputs (`fused_cases.parquet`, `evidence_cards.parquet`, `group_priorities.parquet`, `fusion_report.*`) are produced by the **fusion stage of the existing pipeline**. Nothing new generates them. The new work is registering the run, then publishing it.
* Registration: insert `runs`, call `register_run(run_id)` (chain start), record `fused_cases_sha256`.
* Publishing and refresh: §6.6. For H-B the new run appears on the hosted instance without a redeploy; for H-A after the deploy hook completes.
* A run that exists in `runs` but is not `PUBLISHED` to a target is invisible there. `/api/runs` on a hosted target filters by `published_runs` in addition to the directory glob, closing the half-published window (fact 5, §6.1).

---

## 9. Failure alerts, job tracking, safe retries

### 9.1 Alerts

| Channel | Default | Notes |
|---|---|---|
| In-app banner + "Alerts" list (persistent, acknowledgeable) | **On** | Needs no external service. Shown to `admin` and `technical`. |
| Server log line (structured, sanitised) | **On** | |
| Email through an approved SMTP relay | Off | Needs a relay address and an approved recipient list (D10). The roadmap states "No external services" **[V]**, so no third-party channel (Slack, SMS, hosted webhooks) is proposed without approval. |

Events that alert: upload rejected (format/duplicate), pre-flight blocked, any `FAILED_*`, `FAILED_QA_GATE`, `INTERRUPTED`, publish failed, parity mismatch, audit chain `BROKEN`, database unreachable in PostgreSQL mode, worker heartbeat missing for N minutes, disk below a threshold.

**Alert content rule:** job id, stage, error class and a plain next step, **never** record keys, observed values, file excerpts or raw tracebacks. Today `GET /api/batch/{id}` returns `error`, `log_tail` and `traceback` unfiltered **[V]** (`fusion/api.py:668`), and the preparation issue files contain `observed_value` and record keys. A sanitiser (length cap, strip values after known markers, allow-list of error classes) is applied before anything is stored in `jobs`, `notifications` or returned to a non-admin.

### 9.2 Job tracking

The `jobs` + `job_events` ledger is the single view across upload, preparation, validation, publish and legacy batches. Legacy `pipeline/jobs/*.json` records (one exists: `a6fbc51c…`, release 2023_24, label `v2_2`, `COMPLETED`, 1,400 s **[V]**) are imported read-only into the ledger as `kind=LEGACY_BATCH`, flagged as such, and keep working on the existing Batch page. The JSON file remains the runtime artefact the unchanged `JobManager` reads; the ledger mirrors it. There is no second writer of job state.

### 9.3 Retry rules

| Failure class | Retryable? | What a retry does |
|---|---|---|
| `INTERRUPTED` (process vanished, host restart) | Yes | New attempt (`attempt+1`, `parent_job_id` set) with the **same label**. Completed stages are reused by the pipeline's own resume rule **[V]**. |
| Stage crashed leaving a directory **without** `run_metadata.json` | Only after an explicit admin action | The pipeline refuses to resume ("inspect and remove it") **[V]**. The action **renames** the partial directory to `…_failed_<utc>` (never deletes; D12) and records it, then retries. |
| `FAILED_QA_GATE` | No (automatic) | The data or method is the cause. Alert explains the failed gate. Fix, then re-upload or request a new label. |
| `FAILED_SCHEMA` / `PREFLIGHT_BLOCKED` / duplicates | No | Needs a different file or an approved mapping. |
| Transient infrastructure (database connection, disk full, publish copy error) | Yes, bounded | Up to 3 automatic attempts with backoff for publish/sync only; validation attempts are always manual. |
| Out-of-memory kill | Manual | Alert recommends a host with more memory; never auto-loops. |

A retry never overwrites a stored run, never reuses a label that already has a completed Fusion run (`JobManager.start` already refuses that **[V]**), and is idempotent through L4.

---

## 10. Security and sensitive-data protection

### 10.1 Findings that need your attention first

1. **The working tree is inside a OneDrive folder** (`C:\Users\Dhanush\OneDrive\Documents\INTERNSHIP\Data_IoSPI`), and it holds the raw PLFS folders (`2023-June2024`, `Jan-Dec2024`, `Post2025`: CSV, zips, 406 MB for 2025 alone), prepared Parquet runs and the audit SQLite files. Whether OneDrive is actually syncing them to the cloud was not checked. **[V]** (path) / **[U]** (sync). If it is, unit-level data and review history are already replicated to a consumer cloud account. This is independent of this plan and should be settled by you (D4). The plan places uploads, the PostgreSQL data directory and the worker's output **outside** any synced folder.
2. Whether the 2023-24, 2024 and 2025 PLFS files may be hosted publicly is **not documented in the repository**. The repository's own rule is that unit-level data be stored and transferred only under the applicable GoI controls (`docs/DOCKER.md`) **[V]**. This plan **does not assume** authorisation. Gate **G-AUTH** (below) is required before any non-synthetic data or review record reaches a hosted target.
3. Review records are themselves sensitive: they contain reviewer names and free-text comments, and `evidence_snapshot_json` embeds survey values of the case. `GET /api/cases/{id}` already returns the full `audit_history` (including snapshots) to any authenticated user **[V]**.

### 10.2 Controls

| Area | Control |
|---|---|
| Data classes | `SYNTHETIC` (hosted allowed), `INTERNAL_REAL` (processing side only), `APPROVED_REAL` (hosted allowed after G-AUTH). Stored on `datasets` and `runs`; the publish step refuses to target a host not cleared for the class. |
| Upload intake | CSV only (`.zip` and other archives refused in v1); size cap (default 2 GB, configurable); streamed to disk; server-generated paths only (client file name is display text, never a path); reject NUL bytes, binary content, over-long lines and header counts beyond a cap; UTF-8 (with/without BOM) and Windows-1252 detected, never silently transcoded (original kept, derived copy only if approved). |
| Quarantine | `uploads/` directory outside git and outside OneDrive, owner-only permissions, never served, never executed. Optional malware scan hook (ClamAV) if the host provides it (D11). |
| Authentication and roles | Token auth mandatory for any upload-enabled instance not bound to loopback; `serve.py` already refuses non-local listening without it **[V]**. Upload/validate/retry = `admin`. |
| CSRF/XSS | Bearer-header tokens (no cookies) avoid CSRF; the existing CSP (`default-src 'self'`) stays. All user-supplied display strings are escaped (the UI has an `esc()` helper **[V]**). |
| Database | Separate owner/writer/reader roles (§5.3), TLS `verify-full`, no superuser at runtime, DSN only in environment, least-privilege views for hosted. Disk encryption (BitLocker or LUKS) for the data directory and backups (D4). |
| Logging | Never log row values, file excerpts or DSNs. Sanitiser (§9.1) applies to API responses, ledger and alerts. |
| Retention | Raw uploads and derived copies kept until an approved retention date, then removed **only by an explicit admin action** recorded in the ledger (D12). Nothing is auto-deleted. |
| Audit of the new features | Upload, pre-flight, start, reject, retry, publish and view-of-pre-flight events are written to the **same hash-chained audit store** (new `event_type`s, scope `run_id = "*uploads*"`), so the trail covers operations, not only reviews. |
| Backups | Encrypted `pg_dump` plus WAL archive if the host supports it; weekly restore drill (§14). A periodic signed digest of each chain head is a planned hardening from W9.6 and is optional here (D14). |
| Hosted | `mospi_reader` role only; IP allow-list or private networking where available; Vercel Deployment Protection "All Deployments" and bearer tokens as already documented **[D]**; no export endpoint (already refused when `audit_read_only`). |

### 10.3 Gate G-AUTH (blocks all non-synthetic hosted work)

Written confirmation from the faculty guide or data owner of: which datasets and review records may be hosted, where (country/provider/region), for whom, for how long, and under what controls. Until then: hosted = synthetic only; publishing a non-synthetic run to a hosted target fails with a message naming this gate.

### 10.4 Storage sizing (estimates; the audit-volume figure is an assumption)

| Item | Estimate | Basis |
|---|---|---|
| PostgreSQL | < 5 GB for several years; start with 10 GB | Existing 11-event store file is 57 KB, ≈ 5 KB/event incl. snapshot **[V]**; worst case about 100k events per round ≈ 0.5 GB **[A]**; ledgers are KB-scale |
| Upload quarantine per full delivery | 0.5–1 GB raw CSV | 2025 raw CSV folder is 406 MB, zip 35 MB **[V]** |
| Derived working set per full delivery | ≈ 2–4 GB (prepared Parquet 18–51 MB, plus stage runs of hundreds of MB each) | `docs/VERCEL_COMPATIBILITY_AUDIT.md` §3 **[D]** |
| Published serving set per run | 315 / 319 / 777 MB | **[D]** |
| Worker memory | 6 GB limit, 2–3 GB peak | **[D]** |
| Worker time | 23 min (2023-24) to ≈ 47 min (2025) | **[D]**; today's job record: 1,400 s **[V]** |

---

## 11. Migration strategy (existing data → PostgreSQL, non-destructive)

**Principle:** copy, verify, switch by configuration; the SQLite files stay untouched and remain the rollback source.

| Step | Action | Check |
|---|---|---|
| M0 | Prerequisites: G-AUTH answered for the target host; D2/D5 decided; PostgreSQL provisioned; roles created by `mospi_owner`. Stop the local app (no writers). | `docker compose ps` / process list shows no app |
| M1 | **Backup**: copy the 11 `review_audit.sqlite` files to a dated folder **outside** the repo and OneDrive; record SHA-256 of each; set copies read-only. Re-count events (compare with §2.2). | Checksums stored; counts match §2.2 or differences are explained |
| M2 | **Dry run into a scratch schema** (`migration_staging`) on a throwaway database using the *copies*. | Reconciliation report generated |
| M3 | **Chained stores (19 columns, 6 stores)**: copy rows verbatim with their `event_id`, `previous_hash`, `event_hash`. | Per run: same event count; same last hash; `verify_chain` on PostgreSQL = `INTACT` with the same `last_hash` as SQLite; SHA-256 of an ordered dump of all 19 columns equal on both sides |
| M4 | **Legacy stores (8 columns, 5 stores incl. the 1 decision and 22 case-views)**: copy the 8 columns verbatim with original `event_id`; leave hash columns NULL; then `register_run` inserts `AUDIT_CHAIN_STARTED` sealing them with the existing digest (a new, dated event; the legacy rows are not modified). | `verify_chain` = `INTACT`; seal re-derives; the legacy `CONFIRMED_VALID`-style aliases still map at read time |
| M5 | Insert `migration_records` (one per file: source SHA-256, event counts, hashes before/after). Register all existing Fusion runs in `runs` (`dataset_id = NULL`, `status = REGISTERED`). | Records present for 11 files |
| M6 | **API equivalence test**: start the app against PostgreSQL on the *copied* data and compare `/api/overview`, `/api/reviews`, `/api/cases/{id}` (sampled), `/api/audit/verify`, `/api/feedback` with the SQLite-backed app, field by field (timestamps and ids identical). | Zero differences |
| M7 | **Cutover**: set `MOSPI_AUDIT_BACKEND=postgres` on the local instance. Take one more dry check (event count equal). From now PostgreSQL is the system of record; the SQLite files are archived read-only. | `/healthz` reports `audit_store: postgres` |
| M8 | Hosted parity: T1 reader or T2 sync, then §6.5. | `verify_parity` exits 0 |

**D5 handling:** the single decision and 25 case-views in superseded V1/V2.0 runs are migrated by default because "no loss of history" is a requirement; if you classify them as test data, the alternative is to migrate them with `actor`/`comment` untouched but flag the runs `HISTORICAL_TEST` in `runs` (a label, not a modification of events). Deleting them is not proposed.

**Timeline note:** the migration of today's data is small (32 events) and takes minutes; most of the effort is the automated verification so the same tooling is trustworthy when the volume is real.

---

## 12. Rollback plan

| Layer | Rollback | Preserves |
|---|---|---|
| **Audit backend** | `scripts/export_audit_to_sqlite.py` writes each run's PostgreSQL events (ids, timestamps, hashes) into a **new** SQLite file in the existing format (`COLUMNS` of `fusion/review.py`), runs `verify_chain`, and only then is the file placed (the archived original is kept beside it). Set `MOSPI_AUDIT_BACKEND=sqlite`. Events written after cutover come along. | Every event, byte-compatible; chains `INTACT` |
| **Code** | All changes are additive and behind flags. `git revert` of the feature branch restores V2.2. Tag `v2.2-pre-postgres` before work starts. | Docker/local behaviour of V2.2 |
| **Uploads/automation** | `MOSPI_UPLOADS_ENABLED=0` hides the page and refuses routes. Stored runs are immutable; uploads and derived copies stay on disk. Partial stage directories are renamed, never deleted. | All runs, all uploaded files |
| **Hosted** | H-A: Vercel instant rollback to the previous deployment (each deployment carries its own snapshot). H-B: `published_runs` row set `WITHDRAWN`, run hidden from `/api/runs`; files stay. T2: stop the sync job. | Local system unaffected |
| **Database** | Restore from the last encrypted dump; chain verification after restore is mandatory. | Last backup point |

Rollback is rehearsed in P2 and P8 on synthetic data before it is relied on (§14).

---

## 13. Phased implementation, gates and effort

Effort is in **person-days for one developer** who already knows this codebase, ±30 %. A second reviewer for security and migration is assumed outside these numbers.

| Phase | Scope | Exit gate (all must hold) | Effort |
|---|---|---|---:|
| **P0 Decisions and spikes** | Approvals D1–D20. Spikes: **S1** psycopg + pooled endpoint behaviour on Python 3.12 Linux wheel; **S2** hosted bundle size/cold start (H-A) and H-C feasibility; **S3** minimum columns per contract (run preparation + engines on a *synthetic* file with only required columns); **S4** can a small delivery be validated meaningfully (peer-group minimum sizes); **S5** Docker worker with writable volumes; classify existing audit data (D5); settle OneDrive question. | Written decisions; spike notes committed as docs | 4–6 |
| **P1 PostgreSQL foundation** | `db/` (connection, migration runner, `0001–0004` SQL), `fusion/audit_store.py` (SQLite adapter + PostgreSQL store), roles, `MOSPI_AUDIT_BACKEND`, `/healthz` for PostgreSQL, Compose `postgres` service, dependency pins. Existing tests run unchanged on SQLite. | Full existing suite green on SQLite; same suite green with `MOSPI_AUDIT_BACKEND=postgres` on synthetic data; hash-parity property test passes; concurrency tests (threads **and** processes) pass; privilege tests prove writer cannot UPDATE/DELETE | 8–12 |
| **P2 Audit migration and reconciliation** | `scripts/migrate_audit_to_postgres.py`, `export_audit_to_sqlite.py`, reconciliation report, `audit_verifications`, rehearsals on copies | Dry-run reconciliation = zero differences for all 11 stores (§2.2); rollback rehearsal restores identical chains; M6 equivalence test passes | 5–8 |
| **P3 Run registry, publish, hosted parity** | `runs`/`published_runs`, `scripts/publish_run.py`, manifest hashing, `/api/parity`, `scripts/verify_parity.py`, hosted reader (T1/T2), `scripts/sync_audit.py` (T2), `vercel_app.py` PostgreSQL reader, `.vercelignore` allowlist update | On **synthetic** data: hosted and local report identical parity for runs and events; half-published window closed (test); hosted write refused at both layers | 8–12 |
| **P4 Upload backend** | `ingestion/` (quarantine, streaming, hashing, header pre-flight, mapping profiles, fingerprint, key registry), `uploads/datasets/mapping_profiles` migrations, routes, role tests | Adversarial upload tests pass (§14); duplicate layers L1–L4 proven; no row values in any response | 10–15 |
| **P5 Worker and job ledger** | `ingestion/worker.py`, `jobs/job_events`, `JobManager` `dataset_id` change, state machine, retry rules, partial-directory quarantine action, legacy job import | Kill-9 mid-stage test → `INTERRUPTED` → retry resumes without overwriting; QA-gate failure not auto-retried; one-at-a-time preserved | 10–14 |
| **P6 UI** | "Upload & validate" page, jobs/alerts views, publish/parity indicators, review-only explanation variant, `test_ui_contract` extension; responsive checks at 1440/820/390 px as before | UI contract tests; manual walk-through on synthetic data; no horizontal overflow | 6–9 |
| **P7 Alerts** | `notifications`, sanitiser, banner, optional SMTP, heartbeat | Alert tests; sanitiser tests prove no values/keys in alerts | 3–5 |
| **P8 Hardening and pilot** | Security review, load test, restore drill, docs (`docs/POSTGRESQL.md`, `docs/INGESTION.md`, updates to `DOCKER.md`, README status table), pilot on synthetic data end to end | All §14 acceptance tests; documented runbooks; sign-off | 7–10 |
| **P9 (optional)** | Hosted decisions via PostgreSQL; signed chain digests; queue index (S2); eSigma-facing ingestion hooks | Separate approval | not included |
| **Total P0–P8** | | | **61–91** |

Real data enters only at **P8-pilot or later**, and only if G-AUTH has passed. All earlier verification uses `pipeline/tests/synthetic.py`-style synthetic deliveries.

---

## 14. Test plan

All tests use synthetic data and throwaway databases. PostgreSQL tests are opt-in like the existing real-data tests: marker `postgres`, enabled with `--postgres` and `MOSPI_TEST_DATABASE_URL` (a small `conftest.py` addition, same pattern as `--realdata` **[V]**).

| Area | Tests |
|---|---|
| Hash parity | Same event sequence with an injected clock through SQLite and PostgreSQL gives identical `event_hash`es; legacy rows sealed identically; unusual values (unicode, empty strings, `None`, very small floats, 2000-char comments) round-trip exactly. |
| Append-only | Writer role cannot UPDATE/DELETE/TRUNCATE; owner-level tampering is detected by `verify_chain` (mirrors `test_hash_chain_detects_tampering`). |
| Concurrency | Port `test_concurrent_appends_keep_one_intact_chain` and `test_concurrent_decisions_on_one_case_admit_exactly_one` to PostgreSQL, using threads and separate processes. |
| Migration | Build SQLite stores in all three shapes (legacy 8-column, chained 19-column, mixed) from synthetic events; migrate; compare counts, ordered column dump, `verify_chain`, `last_hash`; migrate twice (idempotent); migrate a store whose chain is already `BROKEN` and confirm the migrator refuses and reports. |
| Rollback | Export PostgreSQL back to SQLite; `verify_chain` INTACT; application on SQLite equals application on PostgreSQL. |
| API equivalence | Existing `fusion/tests` and `pipeline/tests` suites parametrised over both backends; `/api/*` responses compared field-for-field. |
| Access matrix | Extend `test_every_api_route_is_covered_by_the_access_test` for every new route; hosted entrypoint refuses uploads, jobs, retry, parity-write. |
| Upload intake | Zero-byte file; header-only; 5 GB declared vs actual; truncated stream; path-traversal and reserved names in `display_name`; NUL bytes; BOM; Windows-1252; very long line; 100k columns; zip bomb refused; CSV-injection strings; slow client; duplicate concurrent uploads; resumed upload. |
| Pre-flight | Missing/extra/renamed columns; mapping suggestion never auto-applied; unapproved profile refused; counts only in responses (assert no cell values). |
| Duplicates | L1 identical file; L2 re-ordered/re-quoted file; L3 partial overlap; L4 double-click and parallel POST with one `Idempotency-Key`. |
| Pipeline integration | Upload a synthetic complete delivery → run to `PUBLISHED` → open the run in the UI; QA-gate failure injected → `FAILED_QA_GATE`, alert raised, no retry; kill the worker mid-`ml` → `INTERRUPTED` → retry resumes; partial directory without `run_metadata.json` → blocked until the rename action. |
| Publish/parity | Atomic publish; killed mid-copy leaves nothing listed; checksum mismatch refuses registration; parity script detects a flipped byte and a missing event. |
| Security | Auth matrix; role escalation; sanitiser; log scrubbing (grep test for sample values in logs); TLS-required connection test; DSN never in responses or logs. |
| Packaging | Pins identical across `requirements.txt` and `pyproject.toml`; `.vercelignore` allowlist includes new packages and still excludes runs, sqlite, csv; hosted app imports without `psycopg` failing on Python 3.12. |
| Load | 20 concurrent reviewers appending on 3 runs; 10k events per run; page-latency budget measured against the SQLite baseline. |
| Operations | Backup/restore drill with chain verification; worker restart; database restart during an append (no half-written event). |
| Regression | The documented suite (155 passed, 15 skipped **[D]**) is the floor; nothing may regress. |

---

## 15. Files likely to change

### 15.1 Modified (additive; defaults keep today's behaviour)

| File | Change | Risk |
|---|---|---|
| `fusion/api.py` | Accept an audit-store factory; replace the 13 `review_audit.sqlite` expressions; add `/api/uploads*`, `/api/jobs*`, `/api/notifications*`, `/api/parity`; update `/healthz` (writability check currently uses `os.access` on the run directory); sanitise `batch_job` output; extend middleware roles | Medium (large file; most routes call the store) |
| `fusion/serve.py` | `MOSPI_AUDIT_BACKEND`, `MOSPI_DATABASE_URL`, `MOSPI_UPLOADS_ENABLED` | Low |
| `fusion/vercel_app.py` | PostgreSQL **reader** backend; uploads hard-off | Low |
| `fusion/review.py` | **No behavioural change planned.** At most, export `_digest` and the column list under public names so the PostgreSQL store imports them | Low |
| `pipeline/jobs.py` | `dataset_id` distinct from `release`; optional hook to mirror status to the ledger; everything else unchanged | Medium (core of batch control) |
| `scripts/export_serving_data.py` | `--run` filter, SHA-256 manifest entries | Low |
| `requirements.txt`, `pyproject.toml` | Pin `psycopg[binary]` identically | Low (but must pass the pin test and fit the Vercel bundle) |
| `Dockerfile` | `COPY db/ ingestion/ migrations/` (the file copies an explicit package list **[V]**) | Low |
| `docker-compose.yml` | `postgres` and `worker` services; writable volumes for the worker; app environment | Medium |
| `.dockerignore`, `.vercelignore`, `.gitignore` | Allowlist new packages for hosted import; ignore `uploads/`; keep `*.sqlite`/`*.csv` exclusions | Low but easy to get wrong |
| `conftest.py` | `postgres` marker and option | Low |
| `fusion/ui/app.js`, `index.html`, `styles.css` | New page and nav entry, job/alert views, parity indicator, review-only variant, version bump on asset URLs | Medium |
| `fusion/tests/test_ui_contract.py`, `test_deployment.py` | New routes in access matrix; pin test extended | Low |
| `README.md`, `docs/DOCKER.md`, `docs/VERCEL_REVIEW_ONLY_DEPLOYMENT.md`, `docs/ESIGMA_INTEGRATION_ROADMAP.md` | Status table ("PostgreSQL stores: implemented, operational state only"), new procedures | Low |

### 15.2 New

`db/__init__.py`, `db/connection.py`, `db/migrate.py`, `migrations/0001_audit.sql … 0004_*.sql`, `fusion/audit_store.py`, `ingestion/__init__.py`, `ingestion/quarantine.py`, `ingestion/preflight.py`, `ingestion/mapping.py`, `ingestion/dedupe.py`, `ingestion/worker.py`, `ingestion/sanitise.py`, `ingestion/alerts.py`, `scripts/migrate_audit_to_postgres.py`, `scripts/export_audit_to_sqlite.py`, `scripts/publish_run.py`, `scripts/sync_audit.py`, `scripts/verify_parity.py`, tests under `db/tests/` and `ingestion/tests/`, `docs/POSTGRESQL.md`, `docs/INGESTION.md`.

### 15.3 Explicitly unchanged

`statistical/`, `contextual/`, `ml/`, `pattern/`, `historical/`, `integrity/` (engines, rules), `peer_groups/`, `fusion/engine.py`, `fusion/queue.py`, `fusion/lanes.py`, `fusion/calibration.py`, `pipeline/run.py`, `pipeline/qa.py`, `preprocessing/` (it is *invoked*, not edited), `survey_rules/`, `evaluation/`, every stored run, every existing SQLite audit file, `demo-data/`.

---

## 16. Risks

| # | Risk | L | I | Mitigation |
|---|---|---|---|---|
| R1 | Hash drift between SQLite and PostgreSQL (type round-trip) breaks chains | M | H | TEXT/double/smallint choices (§2.3); digest imported not reimplemented; parity property test; verify before and after migration |
| R2 | Real data or review records reach a host without authority | M | H | G-AUTH gate; data-class check in publish; synthetic-only default; OneDrive question resolved first |
| R3 | Hosted bundle exceeds Vercel limits (2025) | H | M | H-B recommendation; S2 spike; serve fewer runs |
| R4 | Half-published run is listed and a missing source is cached by `lru_cache` | M | M | Source-first atomic publish; `published_runs` filter; test |
| R5 | Small uploads give mostly "not assessable" results and mislead | H | M | Accept complete deliveries only (D7); S4 spike; pre-flight states expected assessability |
| R6 | CSV passes preparation but lacks columns that engines need | M | M | S3 spike; minimum-column check per contract in pre-flight |
| R7 | Memory/time of batch (2–3 GB, 23–47 min) on the worker host | M | M | Worker limits, one at a time, clear alerts, no auto-retry on OOM |
| R8 | Lock contention or pooler incompatibility on serverless | L | M | Transaction-scoped advisory locks, `prepare_threshold=None`, S1 |
| R9 | Silent divergence if someone runs the app in SQLite mode after cutover | M | H | Cutover archives SQLite files read-only; `/healthz` and a UI strip show the active backend; startup refuses SQLite when `runs` says PostgreSQL is authoritative |
| R10 | Sensitive text in error messages/tracebacks reaches alerts or hosted users | M | H | Sanitiser, allow-listed error classes, tests |
| R11 | Windows/OneDrive file locking or sync of working directories | M | M | Uploads/DB/worker output outside synced folders; native worker documented |
| R12 | Scope creep into revisions/eSigma semantics | M | M | Overlap blocks; revision handling explicitly out of scope (D9) |
| R13 | Uploaded files cause denial of service (disk, CPU) | M | M | Size caps, quota, one concurrent upload per admin, disk alert |
| R14 | Extra dependency (`psycopg`) breaks the Vercel bundle or the pin test | L | M | S1/S2; pin check in CI |
| R15 | Effort underestimated in the UI/API file (`fusion/api.py` ~850 lines) | M | L | Keep routes in a new router module if the file becomes unwieldy |

---

## 17. Decisions requiring your approval

Each has a recommendation; none is assumed.

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | What PostgreSQL stores | S1 operational / S2 + queue index / S3 all rows | **S1** |
| D2 | Where PostgreSQL runs | P-L local / P-I institutional / P-M managed third party | **P-L now**; P-I when available; P-M synthetic demo only |
| D3 | Hosting for real data | H-A Vercel / H-B Docker host / H-C object storage | **H-B for real data; H-A for synthetic demo** |
| D4 | Data-hosting authority (G-AUTH) and the OneDrive question | Obtain written approval / keep processing side only | **Obtain before any non-synthetic hosting**; resolve OneDrive now |
| D5 | Existing audit data (1 decision, 25 case-views) | Migrate as is / migrate and label as test / exclude | **Migrate as is**, label if you say they were tests |
| D6 | Hosted decision-writing | Stay read-only / enable later | **Stay read-only** (keeps your earlier decision); database enforces it |
| D7 | What the upload accepts and what "manual validation" means | Complete deliveries only / delta batches against a reference snapshot; manual start gate / auto | **Complete deliveries, manual gate, auto-start off** |
| D8 | Column mapping policy | Approved per-contract profiles / free mapping | **Approved per-contract profiles**; unknown layouts need a new contract |
| D9 | Duplicate and overlap policy | Block overlap / allow as revision | **Block**; revisions wait for the eSigma stage |
| D10 | Alert channels | In-app+log / + SMTP / + third-party | **In-app + log; SMTP only via an approved relay** |
| D11 | Upload roles and limits; whether pre-flight may show sample rows; malware scanning | admin-only vs add a role; counts-only vs samples; ClamAV or not | **admin-only, counts-only, 2 GB cap, scan if host provides one** |
| D12 | Retention and deletion | Keep until approved / auto-expire | **Keep; delete only by explicit admin action** |
| D13 | Refresh mechanism on Vercel | Redeploy on publish / manual | **Deploy hook after verified publish** (H-A only) |
| D14 | Dependencies and migrations | psycopg only + SQL files / SQLAlchemy + Alembic; optional signed chain digests | **psycopg only + SQL files**; digests later |
| D15 | Database topology | T1 single / T2 primary + sync | **T2 for third-party hosting; T1 on one approved host** |
| D16 | Reviewer names and comments as personal data | Show to all hosted users / roles only / pseudonymise on hosted | **Hosted shows reviewer name; comments and snapshots hidden from hosted unless D4 allows** |
| D17 | Versions | PostgreSQL 17 (present locally) vs ≥ 15; Python 3.11 local vs 3.12 hosted | **PostgreSQL ≥ 15, test on 17; keep 3.11 (local) and 3.12 (Vercel) as today** |
| D18 | What hosted may read from audit rows | Full row / view without `comment` and `evidence_snapshot_json` | **View without them**; verification result published separately (`audit_verifications`) |
| D19 | Migration window and who runs it | Dedicated window with the app stopped | **Yes**, with a reviewer present |
| D20 | Legacy runs on the hosted tier | Only V2.2 / V2.2 + runs holding decisions / all | **V2.2 plus the one run holding a decision**, to keep bundle/volume small |

---

## 18. Assumptions and unverified items (consolidated)

| Item | Status | Resolved by |
|---|---|---|
| Audit volume stays ≤ ~100k events per run | **[A]** | P2 load test |
| Vercel promotes only successful builds, so a failed publish leaves the old deployment live | **[A]** | S2 |
| `psycopg[binary]` 3.2.x installs on Python 3.12 Linux and works with transaction pooling | **[A]/[U]** | S1 |
| Large Functions are available to this account; cold-start with a 1 GB+ bundle is acceptable | **[U]** | S2 |
| Indian region availability for Vercel Functions and the chosen database | **[U]** | S2 / D2 |
| Neon free-plan limits and regions (the search today did not return them) | **[U]** | D2 |
| Python Blob SDK conditional write: today's search found JavaScript documentation only; the earlier inspection found none for Python 0.11.6 | **[D]/[E]** | Not needed by this plan (PostgreSQL replaces it) |
| Minimum raw columns per contract for downstream engines | **[U]** | S3 |
| Meaningful validation of small deliveries | **[U]** | S4 |
| Docker worker with writable volumes works on this Windows host at acceptable speed | **[U]** | S5 (native worker is the fallback) |
| OneDrive syncs the project folder | **[U]** | You (D4) |
| Whether the default Docker `app` container's UI-started batch works at all | **[V]** that paths are read-only mounts; **[U]** whether it fails in practice | S5 |
| Test baseline 155 passed / 15 skipped still holds | **[D]** | First step of P1 |

---

## 19. Sources

* Repository files named throughout (all inspected 10 Oct 2026).
* Vercel Blob docs, conditional writes (`ifMatch`), consistent reads, private storage: <https://vercel.com/docs/vercel-blob>, <https://vercel.com/docs/vercel-blob/using-blob-sdk>, <https://vercel.com/changelog/vercel-blob-now-supports-consistent-reads-on-private-storage> (search result; Python equivalent not confirmed). **[E]**
* Vercel Postgres transition to Neon through the Marketplace: <https://neon.tech/docs/guides/vercel-postgres-transition-guide>, <https://vercel.com/marketplace/neon> (search result; Mumbai region and current free-plan figures not confirmed). **[E]**
* Vercel limits used above (500 MB function bundle, 4.5 MB request body, Large Functions, CLI upload limits, Hobby terms, Sandbox): as recorded in `docs/VERCEL_COMPATIBILITY_AUDIT.md` §11 on 9 Oct 2026. **[D]** Re-check before relying on them.

---

## 20. What happens next

1. You review this file and answer §17 (or tell me which decisions to change).
2. On approval I start **P0** only (decisions recorded, spikes run on synthetic data, no production changes) and report before P1.
3. Nothing in P1 onward starts without your explicit go-ahead for that phase, and no real data is processed or hosted before G-AUTH.
