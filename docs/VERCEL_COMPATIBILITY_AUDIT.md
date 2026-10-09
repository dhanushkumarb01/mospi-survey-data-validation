# Vercel compatibility audit: V2.2 survey data validation platform

**Audience:** project team and faculty guide deciding whether and how to host the existing V2.2 application on Vercel.
**Date of audit:** 9 October 2026. **Type:** read-only audit. No code, configuration, data or deployment was changed. The only file written is this report.
**Constraint set used:** Vercel is the only hosting platform. PostgreSQL and eSigma are out of scope. Existing logic, runs, audit trails and legacy runs must be preserved.

Every platform claim below cites a page of Vercel's official documentation as retrieved on the audit date (see §11). Vercel changes limits often, so re-check the cited pages before you act on this report. Items marked **UNVERIFIED** were not confirmed and must be tested.

---

## 1. Executive verdict

**The existing V2.2 application cannot be deployed on Vercel without major architectural changes. It can be deployed with changes. Not all of it can run on the free (Hobby) plan.**

The application was built as **one long-lived server process with a local, writable disk**. It uses the disk for three things:

1. It reads about 1.4 GB of stored Parquet runs (V2.2 only; 2.8 GB including the V2.0 and V2.1 runs the UI still lists).
2. It appends review decisions to a SQLite file inside each Fusion run directory.
3. It starts the batch pipeline as a separate operating-system process, which runs for 23 to 47 minutes, uses 2 to 3 GB of memory, and writes new run directories next to the old ones.

Vercel Functions have a read-only filesystem and only a temporary `/tmp` directory, with no persistence across instances. They have a 300-second limit on Hobby (800 s on Pro) and 2 GB of memory on Hobby. Vercel's runtime model rules out all three uses as they are written today.

| Part | Verdict |
|---|---|
| Review workspace (UI plus read-only API) | **Compatible with changes.** FastAPI runs on Vercel's Python runtime. The stored runs must be shipped with the deployment or kept in Vercel Blob. |
| Review decisions and audit trail | **Compatible with changes.** The only first-party durable store that fits is **Vercel Blob** (private). The SQLite audit file can be kept byte-for-byte compatible if a concurrency-safe wrapper downloads it, appends and re-uploads it. |
| Batch pipeline started from the UI | **Not suitable for Vercel Functions.** It is feasible only in **Vercel Sandbox**, and realistically only on Pro: the 2025 batch takes about 47 minutes, longer than the 45-minute Hobby session limit. |
| Free plan | **Only a reduced demo is realistic:** one release, review and decisions, no in-app batch. The full workload exceeds Hobby limits on Blob storage, Blob operations, function duration and team access. |

---

## 2. Component compatibility table

| # | Component | Current implementation (evidence) | Vercel compatibility | Required action |
|---|---|---|---|---|
| C1 | Frontend | Static `fusion/ui/index.html`, `app.js` (68 KB), `styles.css`, served by FastAPI `StaticFiles` at `/assets` plus a catch-all route that returns `index.html` (`fusion/api.py:714-719`). No build step and no `package.json`. All `fetch` calls use relative paths (`app.js:34`). | **Compatible.** Vercel serves `StaticFiles` mounts. Because the app has top-level middleware, Vercel keeps the files inside the function, so the CSP and security headers still apply ([FastAPI on Vercel](https://vercel.com/docs/frameworks/backend/fastapi)). Relative paths work with the Deployment Protection cookie ([Deployment Protection](https://vercel.com/docs/deployment-protection)). | None for the UI itself. One project serves both frontend and backend. **No separate Vercel project is needed.** |
| C2 | Backend framework | FastAPI 0.141.1 / Starlette 1.6.0. `create_app()` factory in `fusion/api.py:163`. Started by `fusion/serve.py` via `uvicorn.run`. | **Compatible with changes.** Vercel detects an ASGI `app` at `app.py`/`index.py`/… or at `tool.vercel.entrypoint` in `pyproject.toml` ([Python runtime](https://vercel.com/docs/functions/runtimes/python)). `serve.py` is not used on Vercel. | Add a thin entrypoint module that calls `create_app(...)` with roots read from environment variables, and a `pyproject.toml` `[tool.vercel] entrypoint`. Keep `serve.py` for Docker and local use. |
| C3 | Python version | Pinned to 3.11.9 (`Dockerfile:6`). The stored runs were produced on 3.11. | **Compatible with changes.** Vercel offers **3.12 (default), 3.13 and 3.14**. **3.11 is not available** ([Python runtime](https://vercel.com/docs/functions/runtimes/python)). | Serve on 3.12. Serving only reads stored outputs and never refits models. **UNVERIFIED:** that every pinned wheel installs on 3.12 Linux and that the test suite passes on 3.12. |
| C4 | Dependency bundle | `requirements.txt`: pandas, numpy, pyarrow, scipy, scikit-learn, duckdb, PyYAML, fastapi, starlette, pydantic, uvicorn. Measured installed size **≈386 MB** on the Windows build machine (pyarrow 85, scipy 121, numpy 58, pandas 39, duckdb 38, sklearn 31). | **UNVERIFIED / at risk.** The Python bundle limit is **500 MB uncompressed**. **Large Functions** (public beta, Fluid compute) allow up to **5 GB** ([Functions limits](https://vercel.com/docs/functions/limitations)). Linux wheels are usually larger than Windows ones, so the margin is small. | Measure with a test deployment. Optional: a slimmer serving requirement set if `scipy`/`sklearn` are not imported on the serving path (must be verified). Use `excludeFiles` for tests and docs. |
| C5 | Read-only stored runs | DuckDB `read_parquet` on local paths: `fused_cases.parquet` (44–112 MB per run), `value_evidence.parquet` (78–212 MB), and source-run Parquet resolved by `SourceResolver` (`fusion/explain.py:217`). Serving set per V2.2 run: **315 MB** (2023-24), **319 MB** (2024), **777 MB** (2025). **1,411 MB** for all three, **2,786 MB** for all V2 runs (measured with `scripts/export_serving_data.py`'s own file list, without copying). | **Compatible with changes.** Data cannot come from Git: it is git-ignored and is unit-level microdata. `/tmp` is limited to 500 MB and does not persist. Options are in §3. | Ship the serving bundle **inside the deployment** at build time (recommended), or download it from a private Blob store to `/tmp` (only for runs under 500 MB). |
| C6 | Review decisions / audit trail | `fusion/review.py`: append-only SQLite (`review_audit.sqlite` per Fusion run), with UPDATE and DELETE triggers and a SHA-256 hash chain. Written on **every case open** (`CASE_VIEWED`, `app.js:336`), every decision and every CSV export (`fusion/api.py:380, 664`). | **Not suitable as-is.** The function filesystem is read-only, and `/tmp` is per instance and temporary. Concurrent instances would each write their own copy, which would split the hash chain. | Keep SQLite as the file format, but store each run's file in **private Vercel Blob**. Each write must: download → append with the existing `append_event` → upload with `ifMatch` ETag (conditional write) → retry on conflict ([Vercel Blob](https://vercel.com/docs/vercel-blob)). Reads use `useCache: false` or an ETag check. |
| C7 | Batch job manager | `pipeline/jobs.py`: `subprocess.Popen` of `python -m pipeline.jobs run` (line 211). State is kept in `pipeline/jobs/<id>.json` and `.log`. Liveness is checked by PID (`_alive`). Jobs run one at a time. | **Not suitable on Functions.** It needs a writable project directory, a child process that outlives the request, and PID tracking across requests. None of these survive when a function instance stops. | Replace the *launcher* (not the pipeline) with a Vercel Sandbox launcher. Store job records and logs in Blob. See §4. |
| C8 | Batch pipeline | `pipeline/run.py`, 8 stages. Measured: **2023-24 full, 1,400 s** (pattern 633 s, ML 249 s). **2025 ML re-run 650 s, fusion 197 s.** **Full 2025 ≈ 47 min.** Peak memory **2–3 GB** (`docs/DOCKER.md`). Writes hundreds of MB per stage. | **Not suitable for Vercel Functions.** The limits are 300 s / 2 GB on Hobby and 800 s (1,800 s beta) / 4 GB on Pro ([Functions limits](https://vercel.com/docs/functions/limitations)). Single stages (pattern 633–955 s) exceed the Hobby limit. Vercel Workflows bound each step by the function limit ([Workflows limits](https://vercel.com/docs/workflows/pricing)), and the engines cannot be split without changing validation logic. **Vercel Sandbox:** Hobby allows a 45-minute session, 4 vCPU, 8 GB and a 64 GB disk; Pro allows 24 hours and 16 GB ([Sandbox pricing](https://vercel.com/docs/vercel-sandbox/pricing)). | Run the **unchanged** `pipeline.run` inside a Sandbox, with inputs on a Sandbox **Drive** (public beta) or pulled from Blob. Upload the outputs to Blob and publish them for serving. The 2025 batch does not fit Hobby's 45-minute session. |
| C9 | Job status polling | The UI polls `/api/batch/{id}` every 5 s (`app.js:584, 634`). | **Compatible with changes.** Each poll becomes a Blob read. | Read the job record from Blob. Consider a longer interval on Vercel to save Blob operations. |
| C10 | CSV export | `/api/export/queue` streams the full filtered list (`fusion/api.py:650-691`). The full 2025 queue is about 1.15 M rows. | **UNVERIFIED / at risk.** Vercel states a **4.5 MB** request and response payload limit ([Functions limits](https://vercel.com/docs/functions/limitations)). Whether streamed responses are exempt was not confirmed. The 300 s limit also applies. | Test with the largest realistic filter. If the response is capped, export in pages or build the CSV in Blob and stream it in parts. Do not truncate silently. |
| C11 | Other API reads | Overview, case page, worklist, groups, aggregates (`limit ≤ 5000`), evaluation, integrity. Measured locally at 0.4–1.2 s on a Docker volume (`docs/DOCKER.md`). | **Compatible with changes.** These run within 300 s and 2 GB. **UNVERIFIED:** latency on 1 vCPU, and cold-start time with a large bundle. | Measure on a Preview deployment. |
| C12 | Online single-record check | `/api/validate/record`: loads YAML rules and queries stored statistical evidence. Stores nothing. | **Compatible** once C5 is solved. | None. |
| C13 | Authentication | Optional bearer tokens from a JSON *file* of SHA-256 hashes (`fusion/api.py:150-186`). Roles are supervisor, technical and admin. Without the file, **every API call is unauthenticated** and the actor name is free text. | **Compatible with changes.** No file can be mounted on Vercel. | Read users from an environment variable (Vercel encrypted env var), keeping file support. Combine with Vercel Deployment Protection (§6). |
| C14 | Health check | `/healthz` uses `os.access(directory, os.W_OK)` to decide whether the audit store is writable (`fusion/api.py:707`). | **Compatible with changes.** It would always report "degraded" on a read-only filesystem. | Make the writability check ask the audit-store backend. |
| C15 | Code version | `MOSPI_CODE_VERSION` env var. `pipeline.run.code_version()` calls `git`. | **Compatible.** Set the env var from Vercel's system variables at build time. `git` is absent at runtime, so the pipeline records `unknown` unless the version is passed in. | Pass the commit into the Sandbox job. |
| C16 | Docker / docker-compose | Hardened single container, named volume, `seed`, `batch` and `tests` services. | **Not applicable on Vercel.** Vercel does not run these containers. | **Keep unchanged.** This remains the local and rollback path. |
| C17 | Tests | `pytest` suites per module; `tests/test_realdata.py` is opt-in (`conftest.py`). `fusion/tests/test_ui_contract.py` checks the UI. | **Compatible** (run in CI or locally, not on Vercel). | Add tests for the Blob audit backend and env-var users. Run the whole suite on Python 3.12. |

---

## 3. Data persistence audit

| Artifact | Current location | Size (measured) | Written by | Preservation on Vercel |
|---|---|---|---|---|
| Raw PLFS files | `2023-June2024/`, `Jan-Dec2024/`, `Post2025/` | 278 + 145 + 445 MB | Never by the app | **Do not upload.** The app does not need them for serving. Exclude them from every deployment (§8 `.vercelignore`). |
| Prepared persons | `preprocessing/runs/*final*/prepared_persons.parquet` | 18–51 MB each | Preprocessing (offline) | Part of the read-only serving bundle (case pages read it). Also a batch input (Sandbox Drive or Blob). |
| Stage runs (statistical, contextual, ML, pattern, historical, integrity, peer groups) | `<module>/runs/<run>/` | 914 MB statistical, 768 MB ML, 547 MB pattern, 256 MB peer, 164 MB historical, 122 MB contextual (all runs) | Pipeline only. **Immutable** | Only the files `export_serving_data.py` lists go in the serving bundle. They are read-only and **shipped with the deployment** (recommended) or held in private Blob. Each deployment then keeps its own immutable copy. |
| Fusion runs | `fusion/runs/<run>/` (11 runs, 1.3 GB) | V2.2: 125–321 MB per run | Pipeline (fusion stage) | Same as above. Legacy V1, V2.0 and V2.1 runs stay readable if they are included in the bundle; including them raises the bundle to about 2.8 GB. |
| **Review audit trails** | `fusion/runs/<run>/review_audit.sqlite` (13 files, 12–57 KB) | Small. **`2024_first_visit_v2` (57 KB) and `2024_first_visit_2024_first_v1_clean` (41 KB) hold recorded decisions.** The rest hold only the chain-start event. | Web app (every case open, decision and export) | **Private Vercel Blob**, one object per run (for example `audit/<run>/review_audit.sqlite`), written only through conditional writes (`ifMatch`). Seed it once from the local files without overwriting anything (same rule as `--keep-existing`). Verify with `/api/audit/verify` before and after. |
| Evaluation results | `evaluation/results/*.json`, `protocol_v1/` | 164 KB | Evaluation scripts (offline) | Read-only bundle. |
| Evaluation runs | `evaluation/runs/` | 739 MB | Offline | **Not needed for serving.** Leave local. |
| Batch job records and logs | `pipeline/jobs/<id>.json`, `.log` | KB | Web app, job process | Private Blob (`jobs/<id>.json`, `jobs/<id>.log`). Existing local records stay local. |
| Batch reports | `pipeline/runs/<release>_<label>.json` | KB | Pipeline | Blob, alongside the outputs of the run that produced them. |
| Rule definitions | `integrity/rules/*.yaml` | Small | Code | Part of the code bundle. **Compatible.** |
| Users and tokens | Optional `users*.json` (git-ignored) | Small | Admin | Vercel **encrypted environment variable**. Never committed and never placed in the bundle. |
| ML models | None persisted (no joblib or pickle in the code). Models are fitted inside the ML stage, and registries are JSON. | n/a | Pipeline | Nothing extra to persist. |
| Uploaded files | **None.** Upload is deliberately not offered (`fusion/api.py:601`) | n/a | n/a | Nothing to migrate. Note the 4.5 MB request limit if upload is ever added. |

**Ways to keep the read-only run data, while hosting only on Vercel:**

| Option | How | Fits Hobby? | Assessment |
|---|---|---|---|
| **A. Ship the data inside the deployment (recommended)** | A build step downloads the serving bundle from a private Blob store into the function bundle. Functions then read local files exactly as today, with no per-request Blob reads. | Partly. The bundle of ≈386 MB+ of packages plus data exceeds 500 MB, so it needs **Large Functions (beta, up to 5 GB)**. **UNVERIFIED:** whether Large Functions are enabled on Hobby, and how long a cold start takes with a 1–2 GB bundle. Staging in Blob is capped at **1 GB on Hobby**, which fits one or two releases but not all three V2.2 runs (1.41 GB). | Closest to current behaviour. Each deployment is an immutable snapshot of the data, which makes rollback simple. |
| A′. Prebuilt CLI upload | `vercel build` locally, then `vercel deploy --prebuilt`, without Blob staging. | **UNVERIFIED.** The CLI upload limit is **100 MB on Hobby, 1 GB on Pro** ([Limits](https://vercel.com/docs/limits)). Whether it applies to prebuilt output must be checked. | Avoids Blob storage costs if allowed. Requires the deploying machine to hold the data, which it does. |
| B. Download from Blob to `/tmp` on cold start | The first request on each instance copies the run's files to `/tmp`. | Only for runs under **500 MB**, so not 2025 (777 MB). Every cold start uses Blob data transfer (**10 GB/month on Hobby**, about 30 cold starts of a 300 MB run). | Fragile. Not recommended. |
| C. DuckDB reading Blob over HTTPS | `httpfs` with an auth header. | **UNVERIFIED** (extension availability at runtime, private-blob authentication, and the cost of range requests against **10,000 simple operations/month on Hobby**). | Not recommended without a spike. |
| Marketplace databases (Neon, Upstash, Supabase) | Provisioned through Vercel, but **operated by third-party providers** ([Storage](https://vercel.com/docs/storage)). | — | **Excluded:** they are external services, and PostgreSQL is out of scope. |

**What "Vercel only" makes impossible:** a single shared, writable POSIX filesystem that the web functions can use directly. Sandbox **Drives** are persistent, but only Sandboxes can mount them, never Functions ([Drives](https://vercel.com/docs/sandbox/concepts/drives)). Durable shared state for the web app therefore has to go through Vercel Blob's object API. That is why the audit store needs an adapter.

---

## 4. Pipeline execution audit

**The current path, traced in the code:**

1. In the UI, an admin opens Batch, chooses a release and label, and the UI sends `POST /api/batch` (`app.js:599`).
2. `JobManager.start` (`pipeline/jobs.py:179`) validates the label and refuses to reuse one. It allows one job at a time, writes `pipeline/jobs/<id>.json`, and **spawns a child Python process** with stdout going to `<id>.log`.
3. The child process (`run_job`) calls `run_pipeline`, which runs 8 stages. Each stage writes a new immutable `<module>/runs/<release>_<obs>_<label>/` directory and passes a QA gate (`pipeline/qa.py`). The fusion stage writes `fusion/runs/<…>/` with `fused_cases.parquet` and the other outputs.
4. The child writes its final status into the job JSON and `pipeline/runs/<release>_<label>.json`.
5. The UI polls every 5 s. `_refresh` checks the PID and reads the log tail.
6. The new Fusion run appears in `/api/runs` because the server lists `fusion/runs/`. Supervisors open cases, and each open and decision appends to that run's `review_audit.sqlite`.

**Exact risks on Vercel Functions:**

| Risk | Detail |
|---|---|
| R1 Duration | Hobby allows 300 s at most. Measured stage times: pattern 633–955 s, ML 249–650 s, full batch 1,400 s (2023-24) to about 2,800 s (2025). Pro allows 800 s, or 1,800 s in beta, which is still shorter than a full batch. A timed-out request returns 504 and the work stops ([Functions limits](https://vercel.com/docs/functions/limitations)). |
| R2 Background work | `waitUntil` and background tasks are bounded by the same invocation lifetime ([Fluid compute](https://vercel.com/docs/fluid-compute)). A child process started with `Popen` has no guarantee of surviving once the instance is frozen or recycled. The job would show as *INTERRUPTED* or, worse, stay *RUNNING* in a record that no other instance can see. |
| R3 Memory | 2025 peaks at 2–3 GB. Hobby allows 2 GB and Pro 4 GB. |
| R4 Disk | Stage outputs are hundreds of MB, while `/tmp` holds 500 MB and is not shared. The project directory is read-only, so `mkdir` on `pipeline/jobs` fails immediately. |
| R5 Splitting into Workflows | Each Workflow step is still one function invocation with the same limit ([Workflows limits](https://vercel.com/docs/workflows/pricing)). Hobby retains run state for 1 day. Making stages fit would mean chunking the statistical, ML and pattern engines, which is **a change to validation logic**. Rejected under the decision rule. |
| R6 Reproducibility | Functions run Python 3.12+, while runs were produced on 3.11. A Sandbox can use a custom image, so the existing 3.11.9 environment could be reproduced (**UNVERIFIED** whether a Dockerfile-based image can be used). |

**Feasible approach (Vercel only):** use **Vercel Sandbox** as the batch worker.

* `POST /api/batch` keeps all of its existing checks (label pattern, no overwrite, one job at a time). Instead of `Popen`, it creates a Sandbox, writes the job record to Blob and returns at once.
* The Sandbox mounts a Drive holding the prepared inputs and the stage runs that will be reused, or pulls them from Blob. It runs **the unchanged** `python -m pipeline.run` / `pipeline.jobs run` command and streams its log to Blob. On success it uploads the new immutable run directories and the pipeline report.
* Making a new run visible to reviewers requires a **new deployment** under option A (a deploy hook after upload), or a Blob read under option B or C.
* Limits: on **Hobby**, sessions last 45 minutes with 4 vCPU and 8 GB, and the allowance is 5 active-CPU hours per month. The 2023-24 batch (23 min) fits. **The 2025 batch (about 47 min) does not**, unless a stopped session is resumed as a persistent sandbox, which needs the pipeline's existing stage-level resume to work across sessions (**UNVERIFIED**). On **Pro**, sessions last 24 hours with 16 GB, so every batch fits ([Sandbox pricing](https://vercel.com/docs/vercel-sandbox/pricing)).
* Storage: a full 2025 batch writes well over 1 GB, more than Hobby's 1 GB Blob allowance. Hobby Drive storage is 15 GB for the account's lifetime, and Drives are a public beta.

**Closest feasible option if Sandbox is not adopted:** run batches with the existing `docker compose --profile batch` or `python -m pipeline.run` on a team machine, then publish the new runs with a new deployment. This is the documented procedure in `docs/DOCKER.md` today. It keeps the pipeline identical, but **the in-app "Start batch" page would not start jobs on the Vercel deployment.** The page must then say so plainly, as it already does for upload. It must not fail silently. This is a functional compromise that the team must accept explicitly.

---

## 5. Free-tier (Hobby) feasibility

Hobby allowances from the cited pages: 4 active-CPU hours, 360 GB-hours of memory, 1 M invocations, 100 GB Fast Data Transfer, a 300 s function limit, 2 GB of memory, **Blob storage of 1 GB, 10,000 simple and 2,000 advanced operations, and 10 GB of transfer per month**. Once a limit is exceeded, **the feature stops until 30 days have passed**; there is no pay-as-you-go option ([Hobby plan](https://vercel.com/docs/plans/hobby), [Blob pricing](https://vercel.com/docs/vercel-blob/usage-and-pricing)).

| Capability | Free? | Why |
|---|---|---|
| Hosting the UI and API | Yes | Well within the compute allowances for a small team. |
| Serving one V2.2 release (for example 2024, 319 MB) | Probably (**UNVERIFIED**: Large Functions on Hobby, or prebuilt upload) | Fits within 1 GB of Blob staging. |
| Serving all three V2.2 releases (1.41 GB) or legacy runs (2.8 GB) | **No** | More than the 1 GB Blob allowance used for staging. |
| Recording decisions | Only for light use | Each case open and each decision is one Blob `put` (advanced operation). **2,000 per month ≈ 1,000 reviewed cases**, while the 2023-24 "Check now" queue alone has 3,110 cases. When the limit is reached, Blob is locked for 30 days, **which also stops audit writes**. |
| In-app batch, 2023-24 | Marginal | Fits in a 45-minute Sandbox, but outputs exceed 1 GB of Blob. |
| In-app batch, 2025 | **No** | About 47 min is longer than the 45-minute session, and outputs exceed the storage allowance. |
| Access for several named people | **No** (see §6) | Hobby allows one external user and one shareable link. |
| **Licence condition** | Must be confirmed | Hobby is restricted to **"non-commercial personal use only"**. Commercial use includes a deployment made by "a paid employee or consultant writing the code" ([Fair use](https://vercel.com/docs/limits/fair-use-guidelines)). If the internship is paid, or the work is done for MoSPI, Hobby may not be permitted. |

**Conclusion:** a free **demo** is realistic if it is limited to one release, light review traffic and no in-app batch. A deployment that the team uses for real review work is **not realistic on Hobby**. The lowest-cost full option on Vercel is **Pro (US$20/month per Developer seat; Viewer seats are free)** ([Hobby plan](https://vercel.com/docs/plans/hobby)). A Pro trial can be used to test first.

---

## 6. Access control and security

**What the app provides today:** optional bearer tokens with roles. Without a users file, every endpoint is open and anyone can record decisions under any name, flagged as unverified. `docs/DOCKER.md` states that TLS, SSO/MFA, encryption at rest and tamper-proof audit storage are **not** provided.

**What Vercel provides** ([Deployment Protection](https://vercel.com/docs/deployment-protection), [Vercel Authentication](https://vercel.com/docs/deployment-protection/methods-to-protect-deployments/vercel-authentication), [Shareable links](https://vercel.com/docs/deployment-protection/methods-to-bypass-deployment-protection/sharable-links)):

| Feature | Hobby | Pro |
|---|---|---|
| Vercel Authentication with scope **All Deployments** (production included) | Yes | Yes |
| Named team members with access | No team members | Viewer seats are free |
| Access requests from external Vercel users | **One external user per account** | Yes |
| Shareable link ("anyone with the link") | **One link per account** | Yes |
| Password Protection | Not available | US$20/month per project |
| Trusted IPs or your own identity provider | No | No (Enterprise only) |

**Safe way to share, using two layers. Both are mandatory before any survey data is uploaded.**

1. **Platform layer:** Vercel Authentication with **All Deployments**, so that neither the production domain nor preview URLs are public. On Pro, add each team member and the faculty guide as a Viewer. On Hobby, the only options are one external user plus one shareable link. A shareable link is a bearer secret: anyone who receives it can open the app. That is acceptable for a short demo only, and the link should be revoked afterwards.
2. **Application layer:** turn on the existing token authentication, with users supplied through an encrypted environment variable. Give each person their own token and role (supervisor, technical or admin), so the audit trail records **verified names** rather than typed ones. Keep `admin` (batch) for one person.

**Other controls:**

* **Private Blob store only.** Public stores serve any URL to anyone ([Vercel Blob](https://vercel.com/docs/vercel-blob)).
* Choose the **function and Blob region** deliberately; the default is `iad1`, in the US. **UNVERIFIED:** whether an Indian region (for example `bom1`) is available for Functions, Blob and Sandbox on your plan.
* Add a `.vercelignore` before any CLI deployment, so raw PLFS files, runs, users files and keys are never uploaded (§8). Git-based deployments are already safe, because data is git-ignored and none is tracked: 132 tracked files, no Parquet, SQLite or CSV.
* Runtime logs are kept for 1 hour on Hobby and 1 day on Pro. The app does not log record contents, but keep it that way.
* **Precondition, not a Vercel limitation:** this repository's own documentation requires unit-level PLFS data to be stored and transferred "only under the applicable GoI data-handling controls" (`docs/DOCKER.md`). Hosting it with a US-based provider needs written approval from the faculty guide or the data owner **before** any upload.

---

## 7. Recommended architecture (simplest one that respects "Vercel only")

```
Browser (team, faculty guide)
   │  Vercel Authentication (All Deployments)  +  app bearer token per person
   ▼
One Vercel project ─ one Python Function (Fluid compute, Python 3.12)
   │   FastAPI app from fusion.api.create_app()   ← unchanged logic
   │   UI files (fusion/ui) served by the same app ← unchanged
   │   Read-only serving bundle (Parquet + JSON) shipped in the deployment (option A)
   │
   ├──► Vercel Blob (PRIVATE)
   │       audit/<fusion-run>/review_audit.sqlite   ← conditional writes (ifMatch), hash chain unchanged
   │       jobs/<id>.json, jobs/<id>.log            ← batch status
   │       staging/serving-bundle/…                 ← source for builds
   │       runs/<new run>/…                         ← outputs of new batches
   │
   └──► Vercel Sandbox (Pro realistically; optional on Hobby for 2023-24/2024 only)
           unchanged `python -m pipeline.jobs run …`, inputs on a Drive or pulled from Blob,
           outputs → Blob → deploy hook → new deployment that includes the new run
```

* **Mandatory scope:** web app plus read-only data plus Blob audit store plus access control.
* **Second phase:** Sandbox batch launcher. Until it exists, batches run locally exactly as today, and new runs are published by redeploying.
* The local Docker deployment remains supported and unchanged throughout.

---

## 8. Anticipated changes, file by file (not made)

**Mandatory**

| File | Change |
|---|---|
| `.vercelignore` (new) | Exclude everything `.dockerignore` excludes (raw data, `**/runs/`, `EDA/`, media, `*.sqlite`, `users*.json`, keys, `docs/`, `evaluation/runs/`). Prevents uploading survey data with `vercel deploy`. |
| `vercel.json` (new) | `functions` entry for the entrypoint: `maxDuration` (300 on Hobby), `excludeFiles` (tests, docs), `regions`. `fluid: true`. |
| `pyproject.toml` (new) | `[tool.vercel] entrypoint = "<module>:app"`, `requires-python` 3.12. Dependencies kept identical to `requirements.txt`, which stays for Docker. |
| `fusion/vercel_app.py` (new, thin) | `app = create_app(fusion_root, project_root, users=…)` with roots and backends taken from environment variables. No logic. |
| `fusion/review.py` | Add a storage backend: the local file (default, unchanged behaviour) or Blob. The Blob backend downloads to `/tmp`, runs the **existing** `initialise`/`_insert` code, uploads with `ifMatch`, and retries on `BlobPreconditionFailedError`. Reads fetch a fresh copy (ETag-checked). The schema, triggers, hash chain, legacy decision mapping and `verify_chain` stay byte-compatible. |
| `fusion/api.py` | (a) Accept users from an environment variable in addition to `--users-file`. (b) Pass the audit backend to `append_event`, `latest_statuses`, `history`, `all_events` and `verify_chain`. (c) `/healthz` asks the backend whether it can write. (d) Batch endpoints use a pluggable job backend; when none is configured they return an explicit "not available on this deployment" reason instead of an error. |
| `pipeline/jobs.py` | Split *launching* from *job logic*: the current `Popen` path stays the default; add a Sandbox launcher and Blob job-record store. `run_job`, labels, the no-overwrite rule and QA handling stay unchanged. |
| `scripts/export_serving_data.py` | Add `--upload-to-blob` (or a new `scripts/publish_serving_data.py`). It never overwrites an existing audit object, mirroring `--keep-existing`, and writes a SHA-256 manifest. |
| `scripts/vercel_build.py` (new) | Build step: fetch the serving bundle from private Blob into the bundle directory and verify the manifest checksums. The build fails if any file is missing or altered. |
| `requirements.txt` | Add an HTTP client or Blob SDK at runtime (`httpx` is dev-only today). **UNVERIFIED:** whether the `vercel` Python SDK includes a Blob client; otherwise use Blob's REST API. Confirm the pins on 3.12. |
| `fusion/tests/test_review.py` + new tests | Blob backend: concurrent appends keep one intact chain; a conflict triggers a retry; existing files read unchanged; legacy V2.0 files verify. Env-var users. |
| `docs/VERCEL_DEPLOYMENT.md` (new), `README.md` | Operating procedure, access setup, backup and rollback. |

**Optional improvements**

| File | Change |
|---|---|
| `fusion/ui/app.js` | Show "batch runs are started by an administrator on the processing machine" on the Vercel deployment until Sandbox is live. Slow down job polling. |
| `requirements` split | A slimmer serving set if `scipy`/`sklearn` are not imported on the serving path, to stay under 500 MB without Large Functions. |
| `fusion/api.py` `/api/export/queue` | Paged or Blob-backed export, if the payload limit applies to streamed responses. |
| Serving scope | Ship only V2.2 runs plus the two legacy runs that hold decisions, to reduce bundle size. |

**Unchanged:** every engine (`statistical/`, `contextual/`, `ml/`, `pattern/`, `historical/`, `integrity/`, `peer_groups/`, `fusion/engine.py`), `pipeline/run.py`, `pipeline/qa.py`, the rules, `Dockerfile`, `docker-compose*.yml` and every stored run.

---

## 9. Deployment and rollback plan

**Before anything:**

1. Commit the current working tree. There are many uncommitted V2.2 changes and two staged deletions. Tag the commit `v2.2-pre-vercel` and do all Vercel work on a branch (for example `vercel-deploy`). `main` and the Docker path stay as they are.
2. Back up the data without modifying it: copy every `fusion/runs/*/review_audit.sqlite` to a dated folder outside the repository, and record SHA-256 checksums plus `/api/audit/verify` results for each run. Optionally run `scripts/export_serving_data.py --output <new folder>`. It only reads the project and refuses an output equal to the project root.

**Test without touching local data:**

3. Create a **separate private Blob store for previews** and use **Preview deployments** only. Seed the audit objects from the *copies*, not the originals, or start them empty. The local `fusion/runs` files are never opened for writing.
4. Verification spike, with no real data: deploy the branch with a synthetic Fusion run (the kind the test suite builds) to check bundle size on Linux and Python 3.12, cold-start time, DuckDB operation, the response-size behaviour of the export, and Deployment Protection.
5. With approval (§6), deploy one real V2.2 release to Preview. Run a scripted check that compares API responses (`/api/overview`, sample `/api/cases/{id}`, `/api/worklist`) against the local Docker instance for the same run. Then record test decisions in the preview store, run `/api/audit/verify`, and confirm the result is `INTACT`.
6. Concurrency test: send two decisions at the same time from two sessions. Both must be stored and the chain must stay intact.

**Go live:**

7. Seed the production Blob audit objects once from the backed-up files, never overwriting. **From that moment the Vercel store is the system of record for those runs.** Stop recording decisions in the local Docker instance for the same runs (or keep it read-only), otherwise the two audit trails diverge.

**Rollback (code and data are kept):**

* **App:** use Vercel's instant rollback to the previous deployment. With option A, each deployment carries its own immutable data snapshot. To withdraw access completely, delete the Vercel project. Neither step touches the Git history or the local data.
* **Audit trail:** download each `audit/<run>/review_audit.sqlite` from Blob and run `verify_chain`. Before placing a file back into the local `fusion/runs/<run>/`, keep the original as a backup. The file format is unchanged, so the Docker workspace reads it directly. Decisions recorded on Vercel are therefore never lost.
* **Code:** `git checkout v2.2-pre-vercel`. Docker and local serving were never modified.

---

## 10. Unresolved blockers

| # | Blocker | Can Vercel alone meet it? | Closest feasible option |
|---|---|---|---|
| B1 | **Shared writable disk** for audit trails and job state | No. Functions have a read-only filesystem and `/tmp` is per instance; Drives mount only in Sandboxes. | A private Blob object per audit file with conditional writes (new adapter code). |
| B2 | **Long batch jobs** (23–47 min, 2–3 GB) started from the UI | Not on Functions (300/800/1,800 s). On Hobby Sandbox the session limit is 45 minutes, which is shorter than the 2025 batch. | A Sandbox launcher on Pro, or local batches plus redeployment, with the in-app start disabled and labelled as such. |
| B3 | **Data volume** (1.4–2.8 GB read-only) vs Hobby Blob (1 GB), `/tmp` (500 MB) and bundle (500 MB) limits | Only with Large Functions (beta), Pro, or a smaller scope. | One release on Hobby; all V2.2 releases on Pro. |
| B4 | **Named access for the team and faculty guide** | Hobby: one external user plus one shareable link only. | Pro Viewer seats (free) plus app tokens; on Hobby, a revocable shareable link for a time-limited demo. |
| B5 | **Hobby licence** (non-commercial personal use only) | Depends on the project's status. | Confirm with the faculty guide; otherwise use Pro. |
| B6 | **Hosting authority for unit-level PLFS data** with a US-based provider | Not a technical question. | Written approval, a region choice, and a private store. Without approval, deploy with synthetic data only. |
| B7 | **Unverified technical items:** bundle size on Linux/3.12; Large Functions on Hobby; cold-start time with a large bundle; streamed responses over 4.5 MB; whether the 100 MB CLI limit applies to prebuilt uploads; Python Blob client; Sandbox custom image for 3.11.9; Indian region availability | — | Resolve in the spike (§9 step 4) before any adapter code is written. |

---

## 11. Sources (Vercel official documentation, retrieved 9 October 2026)

* Functions limits (duration, memory, bundle size, 4.5 MB payload, Large Functions): <https://vercel.com/docs/functions/limitations>
* Python runtime (versions 3.12–3.14, entrypoints, 500 MB bundle): <https://vercel.com/docs/functions/runtimes/python>
* FastAPI on Vercel (static files, middleware, lifespan, single function): <https://vercel.com/docs/frameworks/backend/fastapi>
* Fluid compute (concurrency, `waitUntil`, defaults by plan): <https://vercel.com/docs/fluid-compute>
* Limits (CLI upload 100 MB Hobby / 1 GB Pro, runtime log retention, deployments): <https://vercel.com/docs/limits>
* Fair use (Hobby allowances, non-commercial clause): <https://vercel.com/docs/limits/fair-use-guidelines>
* Hobby plan (allowances, 30-day pause, no team collaboration): <https://vercel.com/docs/plans/hobby>
* Vercel Blob (private stores, conditional writes, caching, overwrite): <https://vercel.com/docs/vercel-blob>
* Blob pricing and Hobby limits (1 GB, 10k/2k operations, 10 GB transfer): <https://vercel.com/docs/vercel-blob/usage-and-pricing>
* Storage overview (first-party vs Marketplace providers): <https://vercel.com/docs/storage>
* Deployment Protection: <https://vercel.com/docs/deployment-protection>
* Vercel Authentication (who can access; one external user on Hobby): <https://vercel.com/docs/deployment-protection/methods-to-protect-deployments/vercel-authentication>
* Shareable links (one per Hobby account): <https://vercel.com/docs/deployment-protection/methods-to-bypass-deployment-protection/sharable-links>
* Vercel Sandbox pricing and limits (45 min Hobby / 24 h Pro, 8/16 GB): <https://vercel.com/docs/vercel-sandbox/pricing>
* Sandbox Drives (persistent, Sandbox-only mounts, public beta): <https://vercel.com/docs/sandbox/concepts/drives>
* Workflows (Python support) and limits (step bounded by function limits, Hobby retention 1 day): <https://vercel.com/docs/workflows>, <https://vercel.com/docs/workflows/pricing>
* `/tmp` writable scratch space of 500 MB with a read-only filesystem: reported by search against Vercel's runtimes documentation (<https://vercel.com/docs/runtimes>). **Re-check the page directly**, because this figure was not read from the page itself during the audit.

**Measurements in this report** come from this repository on the audit date: `pipeline/runs/*.json` and `pipeline/jobs/*.json` (durations); file sizes of `*/runs/`; the export script's own file list, evaluated without copying; installed package metadata (Windows, Python 3.11.9); and `docs/DOCKER.md` / `docs/V2_COMPLETION_AND_IMPLEMENTATION_REPORT.md` (memory, 2025 batch time).
