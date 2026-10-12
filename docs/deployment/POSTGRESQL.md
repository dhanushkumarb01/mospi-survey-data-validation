# PostgreSQL operational store, Upload & validate, worker and periodic checks

Status 12 Oct 2026: implemented in the V2.2 tree and verified locally on synthetic data. The hosted (Vercel) instance now reaches
this database through a **Cloudflare Tunnel and a signed read-only gateway** (docs/deployment/CLOUDFLARE_TUNNEL.md). That path is
verified locally; it goes live once the Cloudflare account steps in that document are done. PostgreSQL accepts no login from beyond
this computer. The direct connection in §7 is superseded.

## 1. What changed and what did not

* **PostgreSQL holds operational state only**: the review/audit trail (same SHA-256 chain as before), the run registry with
  per-file manifests, datasets and uploaded files, jobs with stage events, integrity-check findings, alerts. It holds no survey rows.
  Parquet and DuckDB remain the analytical store.
* **Unchanged**: every validation engine, the preparation contracts, `mospi.pipeline.run`, QA gates, scoring, queue order,
  stored runs and the original SQLite audit files (copied, never modified).
* SQLite stays the default (`MOSPI_AUDIT_BACKEND=sqlite`). PostgreSQL is chosen by configuration; there is no dual-write mode and
  no silent fallback (if the database is unreachable, writes are refused with HTTP 503).

| Code | Purpose |
|---|---|
| `mospi/db/` | connection pool, migrations (`migrations/*.sql`), roles and grants, PostgreSQL audit store, SQLite to PostgreSQL migration, run registry, backup/restore, remote-access set-up |
| `mospi/ingest/` | upload storage, pre-flight, operations service, worker and scheduler, integrity checks, registration of on-server deliveries |
| `mospi/gateway/` | hosted read gateway (Cloudflare Tunnel origin) and its Vercel client (docs/deployment/CLOUDFLARE_TUNNEL.md) |
| `mospi/app/operations_api.py`, `backends.py` | API routes and backend selection; `ui/app.js` page **Upload & validate** and the status strip under the header |

## 2. Configuration (environment variables only)

Local secrets live in the git-ignored `.env` at the repository root, which is also excluded from Docker and Vercel uploads. It is
never read on Vercel and never read by the test suite unless `--postgres` is given.

| Variable | Used by | Meaning |
|---|---|---|
| `MOSPI_AUDIT_BACKEND` | app | `sqlite` (default) or `postgres`; on Vercel `gateway` |
| `MOSPI_DATABASE_URL` | app, worker | runtime connection (`mospi_app`); not set on Vercel any more |
| `MOSPI_GATEWAY_SECRET` and the other `MOSPI_GATEWAY_*` / `MOSPI_CF_ACCESS_*` | gateway, Vercel | see CLOUDFLARE_TUNNEL.md §3 |
| `MOSPI_DB_ADMIN_URL` | operator tools | migrations, roles, audit migration, backups, remote-access set-up (never the web app) |
| `MOSPI_DB_APP_PASSWORD`, `MOSPI_DB_READER_PASSWORD` | `migrate --roles` | role passwords (24+ characters; generated into `.env`) |
| `MOSPI_DB_CA_FILE` | direct hosted client (superseded) | `deploy/postgres/mospi-db-ca.crt`, the public CA certificate for `sslmode=verify-ca` |
| `MOSPI_KEY_HMAC_SECRET` | pre-flight | key for hashed record keys (overlap detection) |
| `MOSPI_UPLOAD_DIR` | uploads | controlled storage (default `data/uploads`, git-ignored). Prefer a folder outside OneDrive |
| `MOSPI_UPLOAD_MAX_FILE_MB` (2048), `MOSPI_UPLOAD_MAX_FILES` (4), `MOSPI_UPLOAD_MAX_COLUMNS` (1000) | uploads | limits |
| `MOSPI_CHECK_INTERVAL_MINUTES` (360; 0 = off) | worker | periodic integrity check |
| `MOSPI_RERUN_ON_CHANGE` (off), `MOSPI_FULL_RERUN_DAYS` (0 = off) | worker | re-validate changed or aged registered deliveries |
| `MOSPI_JOB_STALE_SECONDS` (180) | worker | heartbeat age after which a running job is INTERRUPTED |
| `MOSPI_DB_MAX_CONNECTIONS` (5), `MOSPI_DB_CONNECT_TIMEOUT` (5 s), `MOSPI_DB_STATEMENT_TIMEOUT_MS` (15000) | all | bounded connections and timeouts |

## 3. Setting up (done on this machine on 11–12 Oct 2026)

```
python -m mospi.db.migrate --roles            # schema "mospi", roles mospi_app / mospi_reader, grants (repeatable)
python -m mospi.db.migrate_audit --dry-run    # then without --dry-run
python -m mospi.db.registry register --fusion-root data/fusion/runs --data-class INTERNAL_REAL
python -m mospi.db.registry register --fusion-root data/demo/fusion/runs --data-class SYNTHETIC --hosted
python -m mospi.app.serve --users-file <users.json>   # MOSPI_AUDIT_BACKEND=postgres from .env
python -m mospi.ingest.worker run                      # separate process: validations, checks, recovery
```

The app refuses to start in PostgreSQL mode while a migration is pending, or while a SQLite store holds review history that was
never migrated or changed after migration.

**Audit migration result (12 Oct 2026).** 13 stores (11 Fusion runs, 2 evaluation runs) and 34 events were copied verbatim. For
every chained store, the PostgreSQL head hash equals the SQLite head hash, and all 13 chains are INTACT. Each of the 5 legacy
(pre-chain) stores received the same `AUDIT_CHAIN_STARTED` seal that `review.py` would add. A second run inserted nothing. The
sources were byte-identical before and after (SHA-256), and their backups are in `%LOCALAPPDATA%\MoSPI\backups\audit-sqlite-*`.

## 4. Roles and privileges

| Role | Can | Cannot |
|---|---|---|
| `mospi_app` (local app, worker; loopback only) | INSERT/SELECT the audit trail; read/write ledgers | UPDATE/DELETE/TRUNCATE audit events; log in from another computer |
| `mospi_reader` (hosted read gateway, loopback only) | SELECT the `hosted_*` views; sessions forced read-only; 20 connections, 15 s statement timeout | read any base table; see runs not cleared for hosting; see comments, evidence snapshots or corrected values |
| `postgres` | operator tools on this computer | log in from another computer (`reject` rule) |

Database triggers also enforce the following: audit events are append-only for every role; a finished job never changes state
(a retry is a new job); a published manifest never changes; `hosted_visible` is only possible for SYNTHETIC or APPROVED_REAL data.

## 5. Upload & validate (local instance, administrators)

1. Choose the layout (`2023_24_first`, `2024_first`, `2025_first`: the contracts the pipeline has release presets for) and the
   files. Use the file picker, the folder picker (non-CSV files are listed and skipped) or drag-and-drop (folders included).
2. Files are streamed to `<upload dir>/<dataset>/files/<server id>.csv`. Client names are display text only. Size cap, SHA-256,
   UTF-8 validity, byte-order mark and NUL bytes are recorded while streaming.
3. The pre-flight check reports counts and column names only. It **blocks** on: non-CSV files, encoding, BOM, binary content,
   duplicate column names, missing documented columns (it names the layout that matches instead), a missing or doubled
   household/person file, unexpected files, rows with extra fields or broken quoting, persons mostly without households, an
   identical earlier file, a re-saved copy of earlier rows, and person records already received in an earlier delivery (keyed
   hashes). It **warns** on column-count differences, blank or duplicate keys (preparation keeps and marks those) and small
   deliveries. Unknown layouts are never mapped automatically. Approved column-mapping profiles (JSON in
   `mospi/ingest/profiles/`, `status: APPROVED`) rewrite only the header row of a derived copy.
4. **Start Validation** needs the tick "I have reviewed the pre-flight report". The request is idempotent (Idempotency-Key), and
   a unique index allows one active validation per dataset.
5. The worker runs the job in its own process: staging (re-verifies SHA-256), the unchanged preparation, the unchanged pipeline
   (one stage event per stage, from the pipeline's own log lines; no invented percentages), then publication (manifest, registry
   `PENDING`→`PUBLISHED`, audit chain started, alert). The run is hidden from the dashboard until it is published, and a failed
   run stays hidden.
6. Reliability: a QA-gate stop is `FAILED_QA_GATE` and is never retried automatically. A job whose heartbeat stops is marked
   `INTERRUPTED` and retried once automatically; completed stages are reused, and partial stage folders are renamed
   `*.incomplete-<time>`, never deleted. Only queued jobs can be cancelled.

## 6. Periodic checks (operation A) and reruns (operation B)

The worker queues an integrity check every `MOSPI_CHECK_INTERVAL_MINUTES`. There is one per interval slot and never two at once.
Admins can also start one with **Run integrity check now** or `python -m mospi.ingest.worker check-now`. A check covers:

* every registered/published run: manifest files present and unchanged, Fusion review outputs complete, unique case ids, and metadata consistent with the registry;
* every audit chain (results are stored in `audit_verifications`, which is how the hosted instance shows verification);
* uploads unchanged (a change is FAILED: tampering) and registered on-server deliveries fingerprinted (a change is CHANGED);
* Fusion runs on disk that are not registered (WARNING).

Any FAILED finding makes the check job FAILED (`INTEGRITY_FINDINGS`) and raises an alert. A full pipeline rerun happens only
when `MOSPI_RERUN_ON_CHANGE=1` and a registered delivery changed (once per content version), or when `MOSPI_FULL_RERUN_DAYS` is
set. Each rerun gets a new label, so earlier runs and decisions are never overwritten. To register a delivery for this:
`python -m mospi.ingest.register --contract 2024_first --input-root data/raw`.

First live check (12 Oct 2026): 75 of 75 checks passed (12 runs, 15 chains). An earlier check that day failed because of a
path defect in the checker, since fixed. That job and its alert remain recorded as they happened.

## 7. Vercel to PostgreSQL on this laptop (direct connection) — SUPERSEDED

**Superseded on 12 Oct 2026 by the Cloudflare Tunnel gateway (docs/deployment/CLOUDFLARE_TUNNEL.md).** `pg_hba.conf` was switched
to `python -m mospi.db.remote_access hba --tunnel-only`: the remote reader rule below is removed and every login from beyond this
computer is rejected. `allow-remote-postgres.ps1` now refuses to open the port. The rest of this section is kept as a record.

Configured with `python -m mospi.db.remote_access tls` and `... hba` (both back up and validate before reloading):

* TLS on (TLS 1.2 minimum; 1.3 negotiated) with a private CA. The CA key is in `%LOCALAPPDATA%\MoSPI\pki` and the public CA
  certificate is in `deploy/postgres/mospi-db-ca.crt` (the only `deploy/` file uploaded to Vercel).
* `pg_hba.conf`: `hostssl mospi_v22 mospi_reader 0.0.0.0/0 scram-sha-256` (and IPv6), then `host all all … reject`. Loopback
  rules are unchanged. The backup is in `%LOCALAPPDATA%\MoSPI\pki\pg_hba.conf.*.bak`.
* Verified through this computer's network interface (10.7.12.102):
  * reader login with `sslmode=verify-ca` succeeds (TLS 1.3);
  * `postgres` and `mospi_app` are rejected;
  * a non-TLS reader login is rejected;
  * the Vercel entrypoint (`VERCEL=1`, environment variables only) reads live and sees only the synthetic run.

Vercel project environment variables (Production; mark the URL as Sensitive):

```
MOSPI_AUDIT_BACKEND=postgres
MOSPI_DB_CA_FILE=deploy/postgres/mospi-db-ca.crt
MOSPI_DATABASE_URL=postgresql://mospi_reader:<MOSPI_DB_READER_PASSWORD>@<public address>:<forwarded port>/mospi_v22?sslmode=verify-ca&connect_timeout=5
MOSPI_USERS_JSON=<as before>
```

**Blocker (verified 11 Oct 2026).** This computer is behind two private NAT layers: 10.7.12.102 → gateway 10.7.0.1 →
172.16.254.1 → public 103.139.191.217. Its egress address is 14.99.239.123. A port forward would have to be set up on
equipment upstream of 10.7.0.1, which normally belongs to the network operator (campus, hostel or ISP; this may be
carrier-grade NAT). Until a forwardable public address exists, Vercel cannot reach this database, and the hosted instance
serves its bundled synthetic data with review history unavailable. The rest of the platform is unaffected. To finish:

1. Get a public IPv4 address that forwards to this computer (a router you control, or a static or forwardable address from the ISP).
   Forward an external TCP port to 10.7.12.102:5432; a non-default external port reduces scanner noise.
2. If the address is dynamic, use a DNS name and re-run `python -m mospi.db.remote_access tls --dns <name>`. `verify-ca` does
   not depend on the name; `verify-full` would.
3. Run `deploy/postgres/allow-remote-postgres.ps1` in an elevated PowerShell. It was **not** run: with no forwarding it would
   only expose port 5432 to the shared local network. The Wi-Fi profile is *Public*.
4. From outside the network, run `python -m mospi.db.remote_access check --host <public address> --port <port>`, then set the
   Vercel variables above and redeploy.

Residual risks to accept explicitly: the port is open to the internet (Vercel has no fixed egress address without the paid
Static IPs add-on, so the rule cannot be narrowed by IP); the laptop must stay on and connected; and real-data runs stay
invisible to the hosted reader until gate G-AUTH clears them (`registry register --data-class APPROVED_REAL --approval <ref> --hosted`).

## 8. Backup and recovery

```
python -m mospi.db.backup create          # pg_dump custom format + SHA-256 + content summary, in %LOCALAPPDATA%\MoSPI\backups
python -m mospi.db.backup verify <dump>   # restore drill into a scratch database; compares row counts and every chain; drops it
python -m mospi.db.backup restore <dump> --target-db mospi_v22_recovered   # recovery: new database, verify, then repoint the URLs
```

The first live drill (12 Oct 2026) reported VERIFIED: 11 tables, 14 chains. A restore never writes into the live database.
Retention: keep dumps until an approved retention rule exists, and copy them off this laptop to approved encrypted storage.
The original SQLite stores remain the rollback source for the audit trail.

## 9. Tests

```
python -m pytest                 # 166 passed, 15 real-data + 21 PostgreSQL skipped (opt-in)
python -m pytest --postgres      # 187 passed, 15 real-data skipped; each test uses a throwaway schema
```

The PostgreSQL tests cover:

* migrations and their repeat run;
* privileges for every role;
* guards against rewriting finished jobs and published runs;
* password redaction;
* SQLite/PostgreSQL hash parity;
* concurrency;
* tamper detection;
* hosted views;
* the audit migration: idempotency, broken or conflicting sources, rollback, and the start-up guard;
* the backup drill;
* pre-flight refusals;
* duplicate and overlap detection;
* the role matrix;
* cancel, interruption and automatic retry with resume;
* scheduler slots and change-driven reruns;
* the full synthetic flow: upload → pre-flight → confirmation → worker → publication → dashboard → decision → audit → hosted reader → integrity checks.

## 10. Not done / still required for production

* The Cloudflare account, tunnel, hostname and Access policy, then the Vercel redeploy (CLOUDFLARE_TUNNEL.md §4): owner steps, not done.
* The Docker image installs `psycopg`, but no Compose worker or PostgreSQL service was added. On this Windows machine, run the worker natively.
* Disk encryption (BitLocker) for the PostgreSQL data folder and backups, off-machine backup copies, and the OneDrive question for `data/`: owner decisions.
* Real deliveries were not uploaded; only synthetic data was used. The real-data integrity check reads stored runs locally only.
