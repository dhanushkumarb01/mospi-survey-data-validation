# PostgreSQL on Supabase: operational store and hosted review data

Status 12 Oct 2026: the platform's PostgreSQL is a **Supabase** project (Free plan, region `ap-northeast-2`, Seoul) used for a
one-week hosted review. It is the only database. The laptop's own PostgreSQL (database `mospi_v22`) is no longer used by
the application and is left untouched as an offline backup. The Cloudflare Tunnel and signed-gateway path was removed.

## 1. Architecture

```
 local workspace / worker (this laptop)               Supabase PostgreSQL (schema "mospi")              Vercel (review-only)
 python -m mospi.app.serve ─ mospi_app ─ session pooler :5432 ─┐                                  ┌─ transaction pooler :6543 ─ mospi_reader
 operator tools (migrate, registry, serving, backup) ─ postgres ┘  audit trail, registry, jobs,   │   hosted_* views only, read-only sessions
                                                                   checks, serving files ─────────┘   review data fetched into /tmp, SHA-256 verified
```

* **Operational state** (unchanged design): review/audit trail with the same SHA-256 chain, run registry with per-file manifests,
  datasets, jobs, integrity checks, alerts.
* **Hosted serving set** (new, migration `0004_hosted_serving`): the stored-run files the review pages read, for runs cleared
  for hosting. Vercel has no persistent disk and the review data must not travel in the deployment bundle, so the hosted
  instance reads them from `hosted_serving_files` / `hosted_serving_chunks` into its temporary directory on the first
  signed-in data request of each instance, checks every SHA-256, and serves them with the **unchanged DuckDB queries**: the
  queue order, scores, stories and evidence are exactly those of the local workspace (one system, no second query layer).
  The files are stored as Parquet bytes rather than as table rows because the same data as rows would need several times the
  space (the 2024 value evidence alone is 1.66 million rows of 46 columns) and the Free plan allows 500 MB.
* **Unchanged**: every validation engine, the preparation contracts, `mospi.pipeline.run`, QA gates, scoring, queue order,
  stored runs, branding, the UI. SQLite stays the default local backend.
* **No dual-write, no silent fallback**: the backend is chosen by `MOSPI_AUDIT_BACKEND`. If the database cannot be reached,
  writes are refused with HTTP 503 and the hosted pages say plainly that the review database cannot be reached; nothing is
  served or written anywhere else.

## 2. What is hosted (data choice, 12 Oct 2026)

One year was chosen: **PLFS 2024, first visit, Fusion run `2024_first_visit_v2_2`** (current lane method), registered as
`APPROVED_REAL` and `hosted_visible`. The approval (reference, approver, role, date, run label) is in the run's manifest and
in the chained operations audit trail as a `HOSTING_APPROVED` event. Hosted views still exclude comments, evidence snapshots
and corrected values.

| Candidate (current method) | Records | Files the hosted pages read | As loaded (zstd, page columns only) |
|---|---:|---:|---:|
| 2023_24 first visit v2_2 | 418,159 | 240 MB | ~115 MB (not loaded) |
| **2024 first visit v2_2** | **415,549** | **240 MB** | **115.0 MB, loaded** |
| 2025 first visit v2_2 | 1,148,634 | 570 MB | ~300 MB (not loaded) |

Why 2024: it is the latest method on the most recent complete year that fits **in full** (every case, every evidence row).
2025 shows 2.8 times more records but would put about 300 MB into each hosted cold start: close to Vercel's 500 MB temporary
space and quickly exhausting the Free plan's 5 GB monthly egress. 2023_24 is the same size as 2024 but older.

What was left out (nothing the hosted pages show): the other 10 Fusion runs and 2025/2023_24 data, raw survey files,
peer-group tables, ML evidence files (not read by current-method pages), historical record evidence (superseded V2.0 pages
only), `impact_domains`, `fsu_summary`, and columns no page reads: `prepared_persons` keeps the 13 of 159 columns used for
the person facts on the case page; `statistical_evidence` keeps the 4 of 51 columns used by the record-check tool. Every row
is kept. Each file is checked against its source Parquet before loading: row count, and a content digest (DuckDB `hash` of
the kept columns of every row, summed) computed on both files.

| File (2024) | Rows | Loaded | Source |
|---|---:|---:|---:|
| fusion `fused_cases` | 415,549 | 26.6 MB | 43.7 MB |
| fusion `value_evidence` | 1,662,196 | 53.0 MB | 80.0 MB |
| fusion `evidence_cards` / `group_priorities` | 10,000 / 12,749 | 1.1 / 0.6 MB | 3.3 / 1.0 MB |
| preprocessing `prepared_persons` (13 columns) | 415,549 | 2.6 MB | 19.6 MB |
| statistical `statistical_evidence` (4 columns) | 1,662,196 | 2.6 MB | 43.9 MB |
| contextual `contextual_evidence` | 415,549 | 7.5 MB | 12.1 MB |
| pattern `pattern_evidence` | 278,399 | 19.2 MB | 34.5 MB |
| historical `aggregate_indicators` | 34,450 | 1.7 MB | 1.8 MB |
| integrity `integrity_violations` + JSON reports and run metadata | 0 + 12 files | < 0.1 MB | < 0.1 MB |
| **21 files** | | **115.0 MB** | **239.9 MB** |

## 3. Configuration (environment variables only)

Local secrets are in the git-ignored `.env` at the repository root (excluded from git, Docker and Vercel uploads; never read on
Vercel; read by tests only with `--postgres`). Placeholders are in `.env.example`.

| Variable | Where | Value / meaning |
|---|---|---|
| `MOSPI_DB_ADMIN_URL` | operator tools only | `postgres.<ref>` on the **session pooler** `aws-0-ap-northeast-2.pooler.supabase.com:5432`, `sslmode=verify-full&sslrootcert=<abs path>/deploy/supabase/prod-ca-2021.crt`. Migrations, roles, registry, serving loads, audit migration, backups. Never the web app, never Vercel. |
| `MOSPI_DATABASE_URL` (local) | local app, worker | `mospi_app.<ref>` on the session pooler `:5432`, `sslmode=verify-full`. Session pooler because the worker is long-lived. |
| `MOSPI_HOSTED_DATABASE_URL` (local) → `MOSPI_DATABASE_URL` on Vercel | hosted instance | `mospi_reader.<ref>` on the **transaction pooler** `:6543`, `sslmode=verify-full`. The only database credential Vercel holds. |
| `MOSPI_DB_CA_FILE` | all | `deploy/supabase/prod-ca-2021.crt`: Supabase Root 2021 CA (public). Its SHA-256 fingerprint `80:70:25:AD:…:CA:FA` was checked against both the chain the pooler presents and Supabase's published file. |
| `MOSPI_DB_APP_PASSWORD`, `MOSPI_DB_READER_PASSWORD` | `migrate --roles` | generated 32-character passwords (in `.env` only) |
| `MOSPI_AUDIT_BACKEND` | app | `sqlite` (local default) or `postgres` (Vercel; locally when chosen) |
| `MOSPI_USERS_JSON` (Vercel), `MOSPI_HOSTED_USERS_JSON` (local copy) | hosted sign-in | SHA-256 hashes of the access tokens; tokens are never stored in the repository |
| `MOSPI_DB_MAX_CONNECTIONS` (5; 3 on Vercel), `MOSPI_DB_CONNECT_TIMEOUT` (5 s), `MOSPI_DB_STATEMENT_TIMEOUT_MS` (15000) | all | bounded pool and timeouts |
| `MOSPI_SERVING_DIR` | hosted | where the serving set is materialised (default `<tmp>/mospi-serving`) |
| `MOSPI_KEY_HMAC_SECRET`, `MOSPI_UPLOAD_*`, `MOSPI_CHECK_INTERVAL_MINUTES`, `MOSPI_RERUN_ON_CHANGE`, `MOSPI_FULL_RERUN_DAYS`, `MOSPI_JOB_STALE_SECONDS` | local uploads and worker | as before (docs in §7) |

TLS: `verify-full` is used everywhere (the pooler presents `*.pooler.supabase.com` signed by Supabase Intermediate/Root 2021).
Usernames use Supabase's pooler format `role.projectref`; passwords are URL-encoded.

**Transaction-pooler compatibility** (`mospi/db/connection.py`): no server-side prepared statements (`prepare_threshold=None`);
`search_path`, `statement_timeout` and, for the reader, `transaction_read_only` are set **per transaction** with
`set_config(..., true)`, because a transaction pooler shares server sessions; no session state, LISTEN or temporary tables; the
advisory locks that exist are transaction-scoped (`pg_advisory_xact_lock`). The worker and operator tools use the session pooler.

## 4. Roles, privileges and Supabase hardening

| Role | Can | Cannot |
|---|---|---|
| `mospi_app` (local app and worker) | INSERT/SELECT the audit trail; read/write ledgers | UPDATE/DELETE/TRUNCATE audit events; read serving files |
| `mospi_reader` (Vercel) | SELECT the 8 `hosted_*` views; read-only sessions and transactions; 20 connections; 15 s statement timeout | read any base table; see runs not cleared for hosting; see comments, evidence snapshots or corrected values; write anything |
| `postgres` (Supabase admin, via session pooler) | operator tools from this laptop | — (never used by the web app; never on Vercel) |
| `service_role`, `anon`, `authenticated` | nothing in `mospi` | `service_role` and the anon key are never used or shipped by this project |

Applied with the grants (`python -m mospi.db.migrate`, idempotent), verified 12 Oct 2026:

* Data API disabled on the project (owner setting). In addition, **row level security is enabled on all 13 tables** of `mospi`,
  with one policy (`mospi_app_access`) for `mospi_app` only; the views run as their owner, so the reader sees rows only through them.
* All privileges on schema `mospi`, its tables, sequences and functions, and the default privileges for future objects, are
  revoked from `PUBLIC`, `anon`, `authenticated`, `service_role` and `authenticator`. Verified: none of them has USAGE on the
  schema or SELECT on any object, and `SET ROLE anon` reading any table or view is refused.
* The database-level `REVOKE CONNECT … FROM PUBLIC` used on a dedicated server is skipped on Supabase, because the database
  is shared with the platform's own services; the controls above protect `mospi` instead.
* Triggers (present and tested): audit events append-only for every role; a finished job never changes; a published manifest
  never changes; `hosted_visible` only for `SYNTHETIC` or `APPROVED_REAL`; serving files only for registered, reviewable runs.

## 5. Setting up and loading (done on 12 Oct 2026)

```
python -m mospi.db.migrate --roles               # schema "mospi", 0001-0004, roles, grants, RLS, revocations (repeatable)
python -m mospi.db.backup create                 # before loading
python -m mospi.db.migrate_audit --dry-run       # then without --dry-run
python -m mospi.db.registry register --fusion-root data/fusion/runs --run 2024_first_visit_v2_2 --data-class APPROVED_REAL --hosted \
    --approval "<reference>" --approver "<name>" --approver-role "<role>"
python -m mospi.db.registry register --fusion-root data/demo/fusion/runs --data-class SYNTHETIC --hosted
python -m mospi.db.registry register --fusion-root data/fusion/runs --data-class INTERNAL_REAL     # the other runs, not hosted
python -m mospi.db.serving load --run 2024_first_visit_v2_2   # build -> verify vs source -> upload -> verify in the database
python -m mospi.db.backup create --without-serving-data       # after loading
```

`serving load` writes one file per transaction (batched `executemany` of 2 MiB chunks), skips files whose SHA-256 is already
stored, replaces changed ones and removes stale ones, then recomputes every chunk's SHA-256 and length **inside the database**
(`sha256(data)`) and compares them with the built files, so nothing has to be downloaded to verify a load. The synthetic demo
run is registered (SYNTHETIC, hosted) but its files were not loaded, so the hosted site lists only the approved real run.

Results of 12 Oct 2026:

* Audit migration: 13 stores (11 Fusion runs, 2 evaluation runs), 34 events copied verbatim; every chained store's PostgreSQL
  head hash equals its SQLite head hash; all 13 chains INTACT; the 5 legacy stores received their `AUDIT_CHAIN_STARTED` seal;
  a second run inserted nothing; the 13 SQLite sources were byte-identical (SHA-256) before and after.
* Registry: 12 runs (2024_first_visit_v2_2 APPROVED_REAL hosted; 2024_first_visit_demo SYNTHETIC hosted; 10 INTERNAL_REAL).
* Serving set: 21 files, 114,992,636 bytes, uploaded in 48 s, **VERIFIED**; a second load uploaded nothing.
* Database size after loading: **134 MB of the 500 MB Free limit** (schema `mospi` ≈ 120 MB: `serving_chunks` 119.5 MB, every
  other table < 0.2 MB). Budget was 400 MB.

## 6. Hosted instance (Vercel)

`mospi/app/vercel_app.py` with `MOSPI_AUDIT_BACKEND=postgres`: review-only, audit read-only (decisions and uploads only on the
local instance), sign-in required for every `/api` request. The serving set is fetched only after a request has been
authenticated, so an anonymous request never causes a download. `/healthz` (no sign-in) reports database reachability, TLS,
the applied schema version and whether the review data are loaded, never addresses or records. Function region `icn1`
(Seoul, the Supabase region), `maxDuration` 60 s, at most 3 database connections per instance. Details and the Vercel
environment variables: docs/deployment/VERCEL_REVIEW_ONLY_DEPLOYMENT.md §0.

## 7. Upload & validate, worker, periodic checks (local instance)

Unchanged from the V2.2 implementation: upload with pre-flight, explicit *Start Validation*, the worker
(`python -m mospi.ingest.worker run`) running the unchanged pipeline, periodic integrity checks
(`MOSPI_CHECK_INTERVAL_MINUTES`), reruns on change. With `MOSPI_AUDIT_BACKEND=postgres` locally they now use Supabase through
`mospi_app`. Uploaded survey files stay on this laptop (`MOSPI_UPLOAD_DIR`); PostgreSQL holds no survey rows except the hosted
serving set of approved runs.

## 8. Backup and recovery

```
python -m mospi.db.backup create [--without-serving-data]   # pg_dump (custom) + SHA-256 + content summary, %LOCALAPPDATA%\MoSPI\backups
python -m mospi.db.backup verify <dump>                      # restore drill into a scratch database, compare, drop it
python -m mospi.db.backup restore <dump> --target-db <new>   # recovery into a NEW database, then repoint the URLs
```

Dumps of 12 Oct 2026: `mospi-mospi-20261012T072326Z.dump` (before loading) and `mospi-mospi-20261012T072903Z.dump` (after
loading, without serving bytes). `--without-serving-data` leaves out only `serving_chunks` bytes; their file list and checksums
are in the dump and they are rebuilt exactly with `serving load`. The original SQLite stores remain the rollback source for
the audit trail, and the laptop's PostgreSQL `mospi_v22` is an untouched offline copy of the state before the move.

## 9. Limits and risks (Free plan, one week)

* Supabase Free pauses a project after about 7 days without activity, and a paused project must be restored from the dashboard.
* 500 MB database (134 MB used), 5 GB egress per month: each Vercel cold start downloads the 115 MB serving set once
  (about 40 cold starts per 5 GB). Warm instances reuse it.
* Supabase bans an IP address after repeated failed password logins; the tests use an unreachable address, never a wrong password.
* Vercel Hobby: 300 s maximum duration (set to 60 s), 2 GB memory, 500 MB Python bundle, about 500 MB of `/tmp`.
* From this laptop, downloads from the Supabase pooler measured only 0.02-0.08 MB/s (uploads 4-6 MB/s), so verification is done
  in the database and backups leave out serving bytes. Vercel in the same region does not share this laptop's network path.

## 10. Tests

```
python -m pytest                 # no database needed
python -m pytest --postgres      # throwaway schemas in the Supabase database; never the "mospi" schema
```

`tests/postgres/test_supabase_hosted.py` covers per-transaction settings behind the transaction pooler, RLS on every table,
`anon`/`authenticated`/`service_role`/`PUBLIC` denied, the reader refused on every base table, the serving set (verified in the
database, idempotent, registered runs only, hidden runs invisible, tampering detected and never served), the hosted app serving
the same pages from the database as from the local files, plain 503s when the database is unreachable, and the recorded
approval. The earlier tests cover migrations, privileges, guards, redaction, SQLite/PostgreSQL hash parity, concurrency, the
audit migration, the backup drill, uploads and the worker.

## 11. Teardown after the week, and rollback

1. Vercel: remove the production deployment or the project (`vercel remove mospi-survey-data-validation` or Project Settings →
   Delete), or at least delete the `MOSPI_DATABASE_URL` and `MOSPI_USERS_JSON` environment variables and redeploy.
2. Supabase: take a final backup (`python -m mospi.db.backup create`), then remove the hosted data
   (`python -m mospi.db.serving remove --run 2024_first_visit_v2_2`), and pause or delete the project
   (Dashboard → Project Settings → General → Pause project / Delete project). Deleting removes every copy of the hosted data.
3. Local rollback: set `MOSPI_AUDIT_BACKEND=sqlite` (the default). The per-run `review_audit.sqlite` files were never modified.
   Decisions recorded in Supabase after the move exist only there and in the dumps; restore a dump into a local database
   (`backup restore`) if they must be kept. The laptop's PostgreSQL `mospi_v22` still holds the state of 12 Oct 2026 before the
   move; its old connection values are kept in `.env` as `MOSPI_LOCAL_BACKUP_*` (not read by the application).
4. Rotate or drop the Supabase role passwords if the project is kept (`DROP ROLE mospi_reader, mospi_app` after
   `DROP SCHEMA mospi CASCADE`).
