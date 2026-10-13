# Vercel review-only deployment (V2.2)

**Audience:** the project team member who sets up hosting, and the faculty guide approving it.
**Status, 12 October 2026:** deployed and verified with Supabase-backed data (§0). Sections 1–9 record the original 9 October design; where they differ, §0 applies.

---

## 0. Current set-up: Supabase-backed hosted review (12 October 2026)

This supersedes the bundled-data default of §6. The hosted instance reads **everything from Supabase PostgreSQL** through
the reader role and the `hosted_*` views (docs/deployment/POSTGRESQL.md): the review records, the audit verification and the
review data of the one run approved for hosting (PLFS 2024 first visit, `2024_first_visit_v2_2`). No `data/` file is uploaded
(`.vercelignore`), so the synthetic demo bundle is not deployed either. Uploads remain local only. Decisions can be recorded
on the hosted site once `MOSPI_REVIEW_DATABASE_URL` is set (§4a); until then it is read-only.

| Vercel setting | Value |
|---|---|
| Region | `icn1` (Seoul), next to the Supabase project (`ap-northeast-2`) — `vercel.json` |
| Function | `mospi/app/vercel_app.py`, `maxDuration` 60 s (Hobby maximum is 300 s), 2 GB memory |
| Dependencies | `pyproject.toml`: the `requirements.txt` pins without pyarrow, scipy, scikit-learn and uvicorn (not needed on the hosted path). This keeps the function under Vercel's standard 250 MB: at 453 MB Vercel unpacked dependencies into `/tmp` at run time and the review data no longer fitted (`No space left on device`, seen on the first deployment of 12 Oct 2026). |
| `MOSPI_AUDIT_BACKEND` | `postgres` |
| `MOSPI_DATABASE_URL` (Sensitive) | the `mospi_reader` transaction-pooler URL (`MOSPI_HOSTED_DATABASE_URL` in the local `.env`) — never the admin or app role |
| `MOSPI_DB_CA_FILE` | `deploy/supabase/prod-ca-2021.crt` (public CA, the only `deploy/` file uploaded) |
| `MOSPI_SESSION_SECRET` (Sensitive) | 32+ random characters; signs session cookies. Accounts come from the database ([USER_ACCOUNTS.md](USER_ACCOUNTS.md)); `MOSPI_USERS_JSON` is no longer read |
| `MOSPI_DB_MAX_CONNECTIONS` | `3` |
| `MOSPI_REVIEW_DATABASE_URL` (Sensitive, optional) | the `mospi_reviewer` transaction-pooler URL; lets supervisors and administrators record decisions (§4a). Not set yet |

Behaviour: every `/api` request needs a signed-in session. After sign-in, the first data request of a new function instance
downloads the serving set (115 MB, SHA-256 verified per chunk and per file) into `/tmp`; later requests reuse it. If the
database is unreachable or a checksum fails, data requests answer 503 with a plain message and nothing partial is served.
`/healthz` reports database reachability, TLS, schema version and whether the review data are loaded.

Deploy (from the repository root, `VERCEL_TOKEN` in the environment): `vercel link`, set the variables above with
`vercel env add … production`, then `vercel deploy --prod`. Teardown after the week: docs/deployment/POSTGRESQL.md §11.

**Deployed and verified, 12 Oct 2026:** https://mospi-survey-data-validation.vercel.app (region icn1). 25 of 25 HTTP checks passed: health (database reachable over TLS, schema `0004_hosted_serving`, no host or user in the response), sign-in refused without or with a wrong token, the first signed-in request on a cold instance loaded the 115 MB serving set from Supabase in 7.6 s, only the approved run listed, 415,549 records and the priority-band counts equal to the source Parquet, queue order equal to the source for the first 50, 12,749 FSU groups, worklist, area trends, audit chain INTACT (head `cb9c2df7…`, the SQLite head), and decisions, batches and exports refused. Ten case pages (5 random, 5 from the queue) were identical, field for field and including the evidence story, to the pages the local workspace builds from the original untrimmed data.

## 1. What the hosted instance is

A **review-only** copy of the existing V2.2 workspace (the same `mospi/app/api.py` and `mospi/app/ui`) that shows stored validation runs:
overview, worklist by FSU, all cases, case pages, group alerts, area trends, decisions, audit-trail verification and the technical reference.

| Capability | Hosted on Vercel | Local / Docker (unchanged) |
|---|---|---|
| View runs, cases, worklists, group alerts, area trends | Yes | Yes |
| View recorded decisions and audit history | Yes (without notes, evidence snapshots or corrected values) | Yes |
| Start, restart or queue a batch validation | **No.** Refused by the server (HTTP 403) | Yes (administrator) |
| Record a decision, record "case opened" | **Yes, when `MOSPI_REVIEW_DATABASE_URL` is set** (supervisor or administrator sign-in; written to the Supabase audit chain by the insert-only `mospi_reviewer` role, see §4a). Without it: refused with HTTP 503 ("Decisions are recorded on the processing machine…") | Yes |
| CSV export of a case list | **No.** Refused with HTTP 503; available on the processing machine | Yes |
| Single-record check (Technical reference) | Yes (stores nothing) | Yes |

Validation runs are performed separately on the processing machine and published by redeploying (§6).

## 2. What changed (all inside the existing V2.2 tree)

| File | Change |
|---|---|
| `mospi/app/api.py` | `create_app(..., review_only, audit_read_only, require_authentication, users)`. Review-only: no job manager is created, and middleware refuses every non-GET on `/api/batch*` (403), even for an administrator. Read-only audit: decision, case-opened and export calls are refused (503) with an explicit reason. New `/api/deployment` tells the UI what is allowed. Optional `expected_last_decision_id` on decisions gives HTTP 409 when another reviewer decided the case in the meantime. `/healthz` reports the audit-store mode. All defaults keep the previous behaviour. |
| `mospi/pipeline/stages/fusion/review.py` | **Concurrency fix (local mode too):** appends now take SQLite's write lock (`BEGIN IMMEDIATE`) *before* reading the previous hash. Before this, two simultaneous appends could chain to the same hash, and `verify_chain` would then report the trail as `BROKEN`. This was reproduced with 6 concurrent writers. Same fix in `initialise`, so only one chain-start event is ever written. Adds `DecisionConflict` for the stale-decision check. Schema, hash formula, legacy handling and stored files are unchanged. |
| `mospi/app/serve.py` | `--review-only`, `--audit-read-only`, `MOSPI_REVIEW_ONLY`, `MOSPI_AUDIT_READ_ONLY`. |
| `mospi/app/vercel_app.py` (new) | Vercel entrypoint. Always review-only and audit read-only, with sign-in required (§5). |
| `pyproject.toml`, `vercel.json`, `.vercelignore` (new) | Vercel entrypoint, Python 3.12, function settings, and an **allowlist** of what may upload. |
| `scripts/build_demo_data.py` (new), `data/demo/` (new, 1.2 MB) | Synthetic demonstration bundle (§6). |
| `.gitignore` | Ignores `.vercel/`; allows only `data/demo/` Parquet files. |
| `mospi/app/ui/*` | Redesign (warm ivory, espresso, walnut and burnt-orange palette), a slim mode strip that names review-only and synthetic data, a read-only decision panel, a batch page that explains where runs are produced, no export link when exports are not offered, and the stale-decision check. |
| `tests/app/test_deployment.py` (new) | 15 tests (§8). |

**Not changed:** every validation engine, scoring, calibration, queue order, `mospi/pipeline/run.py`, `mospi/pipeline/jobs.py`, `mospi/pipeline/qa.py`, rules, the Dockerfile and docker-compose files, and every stored run and audit file.

## 3. Running it

```bash
# Local, full functionality (as before)
python -m mospi.app.serve

# Local, review-only (no batch can start; decisions still recorded in the local audit file)
python -m mospi.app.serve --review-only            # or MOSPI_REVIEW_ONLY=1

# Local imitation of the hosted instance, on the synthetic bundle
MOSPI_DATA_DIR=data/demo MOSPI_ALLOW_ANONYMOUS_DEMO=1 python -m uvicorn mospi.app.vercel_app:app --port 8001
```

The hosted entrypoint never writes. Even so, point it at a copy when you test it against real data.

## 4a. Decisions on the hosted instance (Supabase, code ready 13 Oct 2026, off until enabled)

Supabase PostgreSQL is now the shared, durable store, so the blocker in §4 no longer applies. With `MOSPI_REVIEW_DATABASE_URL`
set, a signed-in supervisor or administrator can open a case on the hosted site and record a decision. It goes into the
same Supabase audit chain the processing machine uses, through the same code: appends are serialised per run by a
transaction advisory lock, the SHA-256 chain continues, and a decision made on a case someone else has decided since the
page was opened is refused with HTTP 409 ("Another reviewer recorded a decision on this case…"). Without the variable the
instance stays read-only, exactly as before.

**Who can record.** Supervisors and administrators only; the analyst role sees "Your role can view cases but not record
decisions." The reviewer recorded is the signed-in user, never a typed name. Opening a case is recorded
as `CASE_VIEWED`, which gives the time spent on the case.

**What the database allows** (`mospi_reviewer`, created by `python -m mospi.db.migrate --roles` when
`MOSPI_DB_REVIEWER_PASSWORD` is set):

* INSERT on `audit_events`; SELECT on five of its columns only (`run_id`, `event_id`, `case_id`, `event_type`, `event_hash`),
  enough to find the chain head, the next event id and the latest decision on a case. It cannot read comments, evidence
  snapshots or corrected values.
* SELECT on `hosted_runs` (used by the row checks below). No other table or view, no UPDATE, no DELETE, no TRUNCATE (the
  append-only triggers refuse those for every role in any case).
* Row level security: rows only of runs cleared for hosting, never the `__operations__` trail; inserts only of
  `DECISION_MADE`, `CASE_VIEWED` and `AUDIT_CHAIN_STARTED`, chained (`event_hash` set), `origin = 'postgres'`, and marked as
  a signed-in actor.
* The hosted writer starts a run's chain only when the run has no events at all. If a run holds earlier, unchained history,
  sealing it reads the full rows, so the hosted site refuses with a plain message and the seal is left to the processing
  machine.
* Run registration, the operations trail and exports stay refused in the code as well (`PostgresAuditStore(hosted=True)`).

**What the reviewer sees.**

* After saving: "Decision saved to the audit trail." If a note was written: "…Your note is stored with it but is not shown on
  this site." Under the note field: "Your note is saved with the decision but is not shown on this site." The hosted views
  (`hosted_audit_events`) leave out notes, evidence snapshots and corrected values; the note is kept in the audit trail and
  shown on the processing machine.
* If the database cannot take the decision (unreachable, or a grant missing): HTTP 503, "Your decision could not be saved
  just now, and nothing was recorded. Please try again in a minute; if it keeps happening, tell the administrator." Host
  names and driver errors go to the function log only.
* `/healthz` reports `"audit_store": "append-only"` with the variable set and `"read-only"` without it.
* CSV export stays off on the hosted instance (HTTP 503, "available on the processing machine").

**Verification.** The chain status shown on the hosted site is the last result recorded on the processing machine. Run the
integrity check there to cover new hosted decisions (below, step 6).

**Login failures.** A wrong password makes the Supabase pooler ban the client address after repeated attempts. A
connection whose login is refused is therefore not tried again by the same function instance (it answers 503 until the
next cold start), but every new instance tries once. Check the URL locally before you add it to Vercel (step 3).

### Steps to switch it on (operator; not yet done)

Run steps 1–3 and 6 on the processing machine, with the production `.env` (`MOSPI_DB_ADMIN_URL` on the session pooler,
`MOSPI_DB_APP_PASSWORD` and `MOSPI_DB_READER_PASSWORD` set to the **current** passwords: `--roles` sets all configured roles).

1. **Create the role.** Generate a password and put it in `.env` as `MOSPI_DB_REVIEWER_PASSWORD`:
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Then run

   ```
   python -m mospi.db.migrate --roles
   ```

   This creates `mospi_reviewer` (connection limit 10, 15 s statement timeout) and applies all grants in the same run.
2. **Apply the grants.** `python -m mospi.db.migrate` re-applies the grants and policies alone; it is idempotent and safe to
   repeat. Check in the Supabase SQL editor:

   ```sql
   SELECT column_name FROM information_schema.column_privileges
    WHERE grantee = 'mospi_reviewer' AND table_schema = 'mospi' AND table_name = 'audit_events';   -- 5 columns, no comment
   SELECT table_name, privilege_type FROM information_schema.role_table_grants
    WHERE grantee = 'mospi_reviewer' AND table_schema = 'mospi';      -- audit_events INSERT, hosted_runs SELECT
   SELECT policyname, cmd FROM pg_policies WHERE schemaname = 'mospi' AND 'mospi_reviewer' = ANY(roles);   -- 2 policies
   ```
3. **Build and check the URL.** Transaction pooler, like the reader:
   `postgresql://mospi_reviewer.<project-ref>:<url-encoded-password>@aws-0-<region>.pooler.supabase.com:6543/postgres?sslmode=verify-full`.
   Put it in `.env` as `MOSPI_REVIEW_DATABASE_URL` (so the password stays out of shell history) and test it **once**; if it
   fails, check the password before trying again:
   `python -c "from mospi.db import load_env_file, database_from_env; load_env_file(); print(database_from_env('MOSPI_REVIEW_DATABASE_URL').ping())"`
   It should print `'role': 'mospi_reviewer'` and `'ssl': True`. The local app ignores this variable.
4. **Set it in Vercel** (Sensitive, production): `vercel env add MOSPI_REVIEW_DATABASE_URL production`.
5. **Redeploy:** `vercel deploy --prod`.
6. **Verify.**
   * `GET /healthz` shows `"audit_store": "append-only"`.
   * Sign in as a supervisor, open a case on the approved run, record a decision with a short note: the
     confirmation appears, the audit history shows the decision (without the note), and the Decisions page lists it.
   * Open the same case in a second window opened before the save and record another decision there: it is refused (409).
   * Sign in as a technical user: the case page shows that the role cannot record decisions.
   * Export on All cases is still not offered.
   * On the processing machine: `python -m mospi.ingest.worker check-now`, then `python -m mospi.ingest.worker run --once`.
     The audit check for the run must be `INTACT`; the hosted Technical reference then shows the new verification.

To switch it off again: remove `MOSPI_REVIEW_DATABASE_URL` in Vercel and redeploy (the instance is read-only again), and
optionally `ALTER ROLE mospi_reviewer NOLOGIN` in the SQL editor. Recorded decisions stay in the chain.

## 4. Storage: why decisions were read-only on Vercel (the blocker, historical)

Review decisions need storage that is **durable and shared across function instances**, with a **compare-and-swap write** so that two reviewers cannot lose each other's events or fork the hash chain. On Vercel alone:

* Function filesystems are read-only, apart from a per-instance `/tmp` that does not persist. Writing the audit file there would lose decisions silently, so that was **not done**.
* Vercel Blob (private) is the only first-party durable store. Its conditional write (`ifMatch` / `BlobPreconditionFailedError`) and consistent read (`useCache: false`) are documented for the **TypeScript SDK** (<https://vercel.com/docs/vercel-blob>). The official **Python** SDK (`vercel` 0.11.6 on PyPI, inspected on 9 Oct 2026) has **no `if_match` on `put()`**. Without it, two concurrent read-modify-write cycles of the audit file can silently drop one reviewer's events. Blob is an object store, not a database: an SQLite file in Blob cannot be opened and written concurrently.
* Marketplace databases are third-party services, and PostgreSQL is out of scope for this stage.

**Decision:** the hosted instance is audit **read-only**. Decisions are made in the local or Docker workspace, which keeps the single authoritative, hash-chained store.

Ways to lift this later (each needs your approval):
1. Vercel adds conditional writes to the Python SDK. A Blob audit backend can then be added behind the same `append_event` interface (download, append, conditional upload, retry on conflict).
2. A small Node.js function that uses `@vercel/blob` with `ifMatch` for appends only. This adds a second runtime.
3. The PostgreSQL stage in the roadmap.

**Concurrency in the local workspace** (where decisions are recorded) is now safe and tested: appends are serialised, a stale decision gets HTTP 409, and the UI reloads the case to show the other decision.

## 5. Access control

* **Accounts (since 13 Oct 2026):** named accounts with passwords and three roles (administrator, supervisor, analyst), stored in the database and replacing the earlier bearer tokens ([USER_ACCOUNTS.md](USER_ACCOUNTS.md)). The typed reviewer name is gone.
* **On Vercel the app requires sign-in.** Every `/api` call is refused (503) without a database or without `MOSPI_SESSION_SECRET`, and refused (401) without a valid session. The only exception is `MOSPI_ALLOW_ANONYMOUS_DEMO=1`, which is honoured **only** when the data manifest says `"synthetic": true`.
* **Public without a session:** `/` and `/assets/*` (the UI shell, no data), `/api/session/required` (says only whether sign-in is needed), `/api/auth/login`, and `/healthz`. `/healthz` reports readiness, the default run's directory name, the code version and the audit-store mode. It reports no records and no paths. `tests/app/test_deployment.py` fails if a new `/api` route is added without access coverage.
* **Platform layer (you must configure it):** Vercel Deployment Protection → Vercel Authentication → **All Deployments**. Per the audit (re-check the pricing pages before relying on this): Hobby allows no team members, one external user and one shareable link. Pro adds free Viewer seats. Password Protection is a paid add-on. For the team plus the faculty guide, **Pro is the realistic option**. On Hobby, use a time-limited shareable link for a demo only.
* Accounts are created on the processing machine: the first administrator with `python -m mospi.auth create-admin`, the others on the **Users** page. A temporary password is shown once and goes to the person through a separate channel.

## 6. Data on the hosted instance

* **Default: the synthetic bundle `data/demo/`** (1.2 MB, committed). It is produced by `python scripts/build_demo_data.py --replace` from the test suite's synthetic delivery, run through the unchanged pipeline, and copied with `scripts/export_serving_data.py`. It holds no PLFS record. Every page shows a "Synthetic data" notice.
* **Approved real results** (only with the written approval required for unit-level PLFS data, audit §6):
  1. On the processing machine: `python scripts/export_serving_data.py --output serving-data --without-audit` (`serving-data/` is git-ignored).
  2. Deploy with the CLI from that machine, after deliberately adding `!/serving-data/` to `.vercelignore` for that deployment only, and set `MOSPI_DATA_DIR=serving-data`. **Never commit real data.** Size limits apply: the 500 MB function bundle, or Large Functions (beta). See audit §3.
  3. Leave out `review_audit.sqlite` unless the history is meant to be visible. It contains reviewer names and comments.
* A new batch reaches the instance only by repeating step 1 and redeploying.

## 7. Vercel configuration you will set

| Setting | Value |
|---|---|
| Framework preset | FastAPI (detected from `pyproject.toml` → `tool.vercel.entrypoint = "mospi.app.vercel_app:app"`) |
| Python | 3.12 (`requires-python`). The stored runs were produced on 3.11; serving only reads them. |
| Build / install | Defaults. Dependencies are pinned identically in `pyproject.toml` and `requirements.txt` (a test checks this). |
| Function | `vercel.json`: `mospi/app/vercel_app.py`, `maxDuration` 60 s |
| Environment variables | `MOSPI_SESSION_SECRET` (encrypted, required), `MOSPI_CODE_VERSION` (optional, e.g. the commit), `MOSPI_DATA_DIR` (only for an approved bundle), `MOSPI_ALLOW_ANONYMOUS_DEMO` (synthetic demo only) |
| Deployment Protection | Vercel Authentication, **All Deployments** |
| Region | Choose deliberately (the default is `iad1`, USA). Check whether `bom1` (Mumbai) is available on your plan. |

## 8. Tests run (locally, 9 October 2026) and their results

| Check | Result |
|---|---|
| Full suite before changes (Python 3.11.9) | 140 passed, 15 skipped (opt-in real-data tests) |
| Full suite after changes (Python 3.11.9) | 155 passed, 15 skipped (the same opt-in real-data tests); 15 of the passes are the new deployment tests |
| `fusion/tests` on Python 3.12 with the pinned requirements (Vercel's runtime version) | 53 passed (Python 3.12.4, Windows; every pinned wheel installed) |
| Review-only: POST/PUT/DELETE on `/api/batch*` → 403, also for an authenticated admin. No job file written | Passed (`test_deployment.py`) |
| Batch routes still reach the job manager when review-only is off. Real local batches still run (`tests/pipeline/test_jobs.py`, `test_pipeline.py`) | Passed |
| Decision persists across requests and a new application instance | Passed |
| 6 threads × 15 concurrent appends → one `INTACT` chain with one chain start. 8 concurrent decisions on one case → exactly 1 saved, 7 conflicts | Passed. The previous code gave `BROKEN` on the same workload. |
| Read-only audit: decisions, case-opened events and export refused. The file is byte-for-byte unchanged and the chain stays `INTACT` | Passed |
| Hosted entrypoint: no data without users, malformed users JSON, anonymous demo refused on non-synthetic data, synthetic demo served | Passed |
| Every `/api` route needs a signed-in session (401) | Passed |
| Packaging: pins identical, `.vercelignore` allowlist, demo manifest synthetic with no audit file | Passed |
| `node --check mospi/app/ui/app.js` | Passed |
| Browser (Chrome via Playwright) at 1440, 820 and 390 px, all pages, hosted and local: no horizontal overflow. Hosted: no decision form, no export link, no batch form, direct POST `/api/batch` → 403. Local: decision saved through the form, stale decision → 409, chain `INTACT` | Passed (scratch copies only) |

**Not tested, because it needs Vercel itself:** the build on Vercel's Linux image, the bundle size against the 500 MB limit (packages measured ≈386 MB on Windows), cold-start time, Deployment Protection behaviour, and region availability.

## 9. Steps for you in Vercel

1. Confirm the plan (Hobby is for non-commercial personal use only; audit §5) and the data-hosting approval if real data will ever be used.
2. Import the GitHub repository as a new project. Keep the detected FastAPI preset and the root directory `/`.
3. Add `MOSPI_SESSION_SECRET` (Production and Preview): 32+ random characters.
4. Turn on Deployment Protection → Vercel Authentication → All Deployments, and invite the team and the faculty guide.
5. Deploy. Check `/healthz` (expect `"status": "ok"`, `"review_only": true`, `"audit_store": "read-only"`), then sign in with an account and open a case.
6. If the build exceeds the bundle limit, enable Large Functions or reduce the dependencies. Report the measured size back to the team.

## 10. Remaining limitations

* Decisions are recorded on the hosted instance only when the insert-only reviewer role is configured (§4a; not yet switched on). Notes are stored but not shown there, and CSV export is not offered there.
* Not suitable for real PLFS data until hosting approval exists, and Pro (named access) and region are settled.
* The hosted instance shows only the data it was deployed with. Updates require a redeploy.
