# Vercel review-only deployment (V2.2)

**Audience:** the project team member who sets up hosting, and the faculty guide approving it.
**Status, 9 October 2026:** code prepared and tested locally. **Nothing has been deployed to Vercel.** The first real Vercel deployment is the remaining verification step (see §9).
**Starting point:** [VERCEL_COMPATIBILITY_AUDIT.md](VERCEL_COMPATIBILITY_AUDIT.md). This document records what was built and what was decided differently from that audit, and why.

---

## 1. What the hosted instance is

A **review-only** copy of the existing V2.2 workspace (the same `fusion/api.py` and `fusion/ui`) that shows stored validation runs:
overview, worklist by FSU, all cases, case pages, group alerts, area trends, decisions, audit-trail verification and the technical reference.

| Capability | Hosted on Vercel | Local / Docker (unchanged) |
|---|---|---|
| View runs, cases, worklists, group alerts, area trends | Yes | Yes |
| View recorded decisions and audit history | Yes, read-only, for history shipped with the data | Yes |
| Start, restart or queue a batch validation | **No.** Refused by the server (HTTP 403) | Yes (administrator) |
| Record a decision, record "case opened" | **No.** Refused with HTTP 503 and a plain reason (see §4) | Yes |
| CSV export of a case list | **No.** Every export is logged in the audit trail, which is read-only here | Yes |
| Single-record check (Technical reference) | Yes (stores nothing) | Yes |

Validation runs are performed separately on the processing machine and published by redeploying (§6).

## 2. What changed (all inside the existing V2.2 tree)

| File | Change |
|---|---|
| `fusion/api.py` | `create_app(..., review_only, audit_read_only, require_authentication, users_json)`. Review-only: no job manager is created, and middleware refuses every non-GET on `/api/batch*` (403), even for an administrator. Read-only audit: decision, case-opened and export calls are refused (503) with an explicit reason. New `/api/deployment` tells the UI what is allowed. Users can come from the `MOSPI_USERS_JSON` environment variable. Optional `expected_last_decision_id` on decisions gives HTTP 409 when another reviewer decided the case in the meantime. `/healthz` reports the audit-store mode. All defaults keep the previous behaviour. |
| `fusion/review.py` | **Concurrency fix (local mode too):** appends now take SQLite's write lock (`BEGIN IMMEDIATE`) *before* reading the previous hash. Before this, two simultaneous appends could chain to the same hash, and `verify_chain` would then report the trail as `BROKEN`. This was reproduced with 6 concurrent writers. Same fix in `initialise`, so only one chain-start event is ever written. Adds `DecisionConflict` for the stale-decision check. Schema, hash formula, legacy handling and stored files are unchanged. |
| `fusion/serve.py` | `--review-only`, `--audit-read-only`, `MOSPI_REVIEW_ONLY`, `MOSPI_AUDIT_READ_ONLY`, `MOSPI_USERS_JSON`. |
| `fusion/vercel_app.py` (new) | Vercel entrypoint. Always review-only and audit read-only, with sign-in required (§5). |
| `pyproject.toml`, `vercel.json`, `.vercelignore` (new) | Vercel entrypoint, Python 3.12, function settings, and an **allowlist** of what may upload. |
| `scripts/build_demo_data.py` (new), `demo-data/` (new, 1.2 MB) | Synthetic demonstration bundle (§6). |
| `.gitignore` | Ignores `.vercel/`; allows only `demo-data/` Parquet files. |
| `fusion/ui/*` | Redesign (warm ivory, espresso, walnut and burnt-orange palette), a slim mode strip that names review-only and synthetic data, a read-only decision panel, a batch page that explains where runs are produced, no export link when exports are not offered, and the stale-decision check. |
| `fusion/tests/test_deployment.py` (new) | 15 tests (§8). |

**Not changed:** every validation engine, scoring, calibration, queue order, `pipeline/run.py`, `pipeline/jobs.py`, `pipeline/qa.py`, rules, the Dockerfile and docker-compose files, and every stored run and audit file.

## 3. Running it

```bash
# Local, full functionality (as before)
python -m fusion.serve

# Local, review-only (no batch can start; decisions still recorded in the local audit file)
python -m fusion.serve --review-only            # or MOSPI_REVIEW_ONLY=1

# Local imitation of the hosted instance, on the synthetic bundle
MOSPI_DATA_DIR=demo-data MOSPI_ALLOW_ANONYMOUS_DEMO=1 python -m uvicorn fusion.vercel_app:app --port 8001
```

The hosted entrypoint never writes. Even so, point it at a copy when you test it against real data.

## 4. Storage: why decisions are read-only on Vercel (the blocker)

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

* **What existed:** optional bearer tokens (SHA-256 hashes in a users file), with roles supervisor, technical and admin. A typed reviewer name was never authentication, and it still is not: on the hosted instance the name field is hidden.
* **On Vercel the app requires sign-in.** Every `/api` call is refused (503) until `MOSPI_USERS_JSON` is set, and refused (401) without a valid token. The only exception is `MOSPI_ALLOW_ANONYMOUS_DEMO=1`, which is honoured **only** when the data manifest says `"synthetic": true`.
* **Public without a token:** `/` and `/assets/*` (the UI shell, no data), `/api/session/required` (says only whether sign-in is needed), and `/healthz`. `/healthz` reports readiness, the default run's directory name, the code version and the audit-store mode. It reports no records and no paths. `fusion/tests/test_deployment.py` fails if a new `/api` route is added without access coverage.
* **Platform layer (you must configure it):** Vercel Deployment Protection → Vercel Authentication → **All Deployments**. Per the audit (re-check the pricing pages before relying on this): Hobby allows no team members, one external user and one shareable link. Pro adds free Viewer seats. Password Protection is a paid add-on. For the team plus the faculty guide, **Pro is the realistic option**. On Hobby, use a time-limited shareable link for a demo only.
* Create tokens on your own computer and never commit them:
  ```bash
  python -c "import secrets,hashlib; t=secrets.token_urlsafe(24); print('give to user:', t); print('token_sha256:', hashlib.sha256(t.encode()).hexdigest())"
  ```
  `MOSPI_USERS_JSON` value (one line, placeholders only):
  `{"users": [{"name": "<Full name>", "role": "supervisor", "token_sha256": "<64 hex characters>"}]}`

## 6. Data on the hosted instance

* **Default: the synthetic bundle `demo-data/`** (1.2 MB, committed). It is produced by `python scripts/build_demo_data.py --replace` from the test suite's synthetic delivery, run through the unchanged pipeline, and copied with `scripts/export_serving_data.py`. It holds no PLFS record. Every page shows a "Synthetic data" notice.
* **Approved real results** (only with the written approval required for unit-level PLFS data, audit §6):
  1. On the processing machine: `python scripts/export_serving_data.py --output serving-data --without-audit` (`serving-data/` is git-ignored).
  2. Deploy with the CLI from that machine, after deliberately adding `!/serving-data/` to `.vercelignore` for that deployment only, and set `MOSPI_DATA_DIR=serving-data`. **Never commit real data.** Size limits apply: the 500 MB function bundle, or Large Functions (beta). See audit §3.
  3. Leave out `review_audit.sqlite` unless the history is meant to be visible. It contains reviewer names and comments.
* A new batch reaches the instance only by repeating step 1 and redeploying.

## 7. Vercel configuration you will set

| Setting | Value |
|---|---|
| Framework preset | FastAPI (detected from `pyproject.toml` → `tool.vercel.entrypoint = "fusion.vercel_app:app"`) |
| Python | 3.12 (`requires-python`). The stored runs were produced on 3.11; serving only reads them. |
| Build / install | Defaults. Dependencies are pinned identically in `pyproject.toml` and `requirements.txt` (a test checks this). |
| Function | `vercel.json`: `fusion/vercel_app.py`, `maxDuration` 60 s |
| Environment variables | `MOSPI_USERS_JSON` (encrypted, required), `MOSPI_CODE_VERSION` (optional, e.g. the commit), `MOSPI_DATA_DIR` (only for an approved bundle), `MOSPI_ALLOW_ANONYMOUS_DEMO` (synthetic demo only) |
| Deployment Protection | Vercel Authentication, **All Deployments** |
| Region | Choose deliberately (the default is `iad1`, USA). Check whether `bom1` (Mumbai) is available on your plan. |

## 8. Tests run (locally, 9 October 2026) and their results

| Check | Result |
|---|---|
| Full suite before changes (Python 3.11.9) | 140 passed, 15 skipped (opt-in real-data tests) |
| Full suite after changes (Python 3.11.9) | 155 passed, 15 skipped (the same opt-in real-data tests); 15 of the passes are the new deployment tests |
| `fusion/tests` on Python 3.12 with the pinned requirements (Vercel's runtime version) | 53 passed (Python 3.12.4, Windows; every pinned wheel installed) |
| Review-only: POST/PUT/DELETE on `/api/batch*` → 403, also for an authenticated admin. No job file written | Passed (`test_deployment.py`) |
| Batch routes still reach the job manager when review-only is off. Real local batches still run (`pipeline/tests/test_jobs.py`, `test_pipeline.py`) | Passed |
| Decision persists across requests and a new application instance | Passed |
| 6 threads × 15 concurrent appends → one `INTACT` chain with one chain start. 8 concurrent decisions on one case → exactly 1 saved, 7 conflicts | Passed. The previous code gave `BROKEN` on the same workload. |
| Read-only audit: decisions, case-opened events and export refused. The file is byte-for-byte unchanged and the chain stays `INTACT` | Passed |
| Hosted entrypoint: no data without users, malformed users JSON, anonymous demo refused on non-synthetic data, synthetic demo served | Passed |
| Every `/api` route needs a token (401) when users are configured | Passed |
| Packaging: pins identical, `.vercelignore` allowlist, demo manifest synthetic with no audit file | Passed |
| `node --check fusion/ui/app.js` | Passed |
| Browser (Chrome via Playwright) at 1440, 820 and 390 px, all pages, hosted and local: no horizontal overflow. Hosted: no decision form, no export link, no batch form, direct POST `/api/batch` → 403. Local: decision saved through the form, stale decision → 409, chain `INTACT` | Passed (scratch copies only) |

**Not tested, because it needs Vercel itself:** the build on Vercel's Linux image, the bundle size against the 500 MB limit (packages measured ≈386 MB on Windows), cold-start time, Deployment Protection behaviour, and region availability.

## 9. Steps for you in Vercel

1. Confirm the plan (Hobby is for non-commercial personal use only; audit §5) and the data-hosting approval if real data will ever be used.
2. Import the GitHub repository as a new project. Keep the detected FastAPI preset and the root directory `/`.
3. Add `MOSPI_USERS_JSON` (Production and Preview) with the hashes you generated (§5).
4. Turn on Deployment Protection → Vercel Authentication → All Deployments, and invite the team and the faculty guide.
5. Deploy. Check `/healthz` (expect `"status": "ok"`, `"review_only": true`, `"audit_store": "read-only"`), then sign in with a token and open a case.
6. If the build exceeds the bundle limit, enable Large Functions or reduce the dependencies. Report the measured size back to the team.

## 10. Remaining limitations

* Decisions cannot be recorded on the hosted instance (§4). This is deliberate.
* Not suitable for real PLFS data until hosting approval exists, and Pro (named access) and region are settled.
* The hosted instance shows only the data it was deployed with. Updates require a redeploy.
