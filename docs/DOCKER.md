# Running the MoSPI survey data validation workspace with Docker

Audience: whoever installs and operates the review workspace (HSD technical staff, system administrators).

## What runs

| Container | Purpose | When |
|---|---|---|
| `app` | The supervisor review workspace: web UI and local API (FastAPI/uvicorn) on port 8000 | Always |
| `seed` | One-shot: copies the stored runs the workspace reads into the data volume | Once, and after new runs are produced |
| `batch` | The batch validation pipeline (same image), writing new immutable runs | Optional |
| `tests` | The automated test suite (image with pytest) | Optional |

One application container is enough: the workspace is a single FastAPI process that serves the static UI and reads stored Parquet runs with DuckDB. Review decisions are written to an append-only SQLite file inside each Fusion run directory. No separate database, web server, queue or worker is needed at the current scale.

**Survey data is never built into the image.** It lives in the Docker volume `mospi-survey-validation_mospi-data`, which is filled from a directory you choose (`MOSPI_DATA_DIR`).

## Prerequisites

* Docker Engine 25 or later with Compose v2.24 or later (Docker Desktop on Windows/macOS, or Docker Engine on Linux). The Compose file uses volume `subpath` mounts.
* About 2 GB of disk for the image and data volume (three survey rounds: the volume is about 0.8 GB), plus up to 3 GB of RAM for the app container.
* The stored runs: either this repository's `*/runs/` directories, or a portable bundle made with `scripts/export_serving_data.py` (see "Moving the data to another machine").

No local Python installation is needed.

## Quick start

From the repository root:

```bash
docker compose build                              # build the image (about 3 minutes the first time)
# To make /healthz report the exact source commit (detects a stale image):
# MOSPI_CODE_VERSION=$(git rev-parse --short=12 HEAD) docker compose build
docker compose --profile seed run --rm seed       # copy the stored runs into the data volume
docker compose up -d                              # start the workspace
```

Open <http://127.0.0.1:8000>. Check readiness:

```bash
curl http://127.0.0.1:8000/healthz
docker compose ps                                 # STATUS shows (healthy)
```

`/healthz` returns `200` with `"status": "ok"` when a Fusion run, all its source runs and a writable audit store are present. Otherwise it returns `503` with the reason. It needs no login and returns no survey records or file paths.

## Configuration

Set these as environment variables or in a `.env` file next to `docker-compose.yml`:

| Variable | Default | Meaning |
|---|---|---|
| `MOSPI_DATA_DIR` | `.` (this repository) | Directory with the run layout `<module>/runs/<run>/…` and `evaluation/results/`, used by `seed` and `batch` |
| `MOSPI_PORT` | `8000` | Host port, always bound to `127.0.0.1` |
| `MOSPI_MEM_LIMIT` | `3g` | Memory limit of the app container (observed: about 110 MB at idle, more during a full export) |
| `MOSPI_USERS_FILE_IN_CONTAINER` | empty | Path *inside the container* of a users file; turns on token authentication (below) |
| `MOSPI_EXTRA_CA_FILE` | empty file | Build time only: CA certificate of a TLS-inspecting proxy or antivirus on the build machine |
| `MOSPI_UID` / `MOSPI_GID` | `10001` | User for the `batch` service and the Linux bind-mount override |
| `MOSPI_BATCH_MEM_LIMIT` | `6g` | Memory limit of the `batch` service |

The server's own settings are fixed in the image (`MOSPI_FUSION_ROOT=/data/fusion/runs`, `MOSPI_PROJECT_ROOT=/data`, `MOSPI_HOST=0.0.0.0`, `MOSPI_PORT=8000`, `MOSPI_CONTAINER=1`).

## Data and persistence

```
mospi-data volume
├── preprocessing/runs/…      read-only in the app
├── statistical/runs/…        read-only
├── contextual/runs/…         read-only
├── ml/runs/…                 read-only
├── pattern/runs/…            read-only
├── historical/runs/…         read-only
├── integrity/runs/…          read-only
├── evaluation/results/…      read-only
└── fusion/runs/<run>/        writable: review_audit.sqlite (decisions and views)
```

* By default `seed` copies the V2 Fusion runs and exactly the source files they reference. That is about 0.8 GB for 2023-24, 2024 and 2025, against about 2.5 GB for all runs in the repository.
* `seed` **never overwrites a file already in the volume**. Re-running it after new runs are produced adds them and keeps every review decision already recorded. The only exception is `evaluation/results/*.json`, which is small and refreshed each time.
* The volume survives `docker compose down`, restarts and image rebuilds. Only `docker compose down -v` or `docker volume rm` deletes it, **including the review audit trails**.
* The app cannot write to stored runs or to its own code: the container root filesystem is read-only.

### Why a volume rather than a direct folder mount

With Docker Desktop on Windows/macOS, folder (bind) mounts pass every file read through a file-sharing layer. Measured with the same data:

| Endpoint | Folder mount (Windows) | Volume |
|---|---:|---:|
| Case page | 20–30 s | 1.1–1.2 s |
| Case list (25 rows with summaries) | 7.8 s | 0.4–0.6 s |
| Overview | 8.5 s | 0.7–0.9 s |

On **Linux** hosts folder mounts are native speed. If you prefer to keep the runs in a host folder there:

```bash
MOSPI_DATA_DIR=/srv/mospi-data MOSPI_UID=$(id -u) MOSPI_GID=$(id -g) \
  docker compose -f docker-compose.yml -f docker-compose.bind.yml up -d
```

`fusion/runs` must then be writable by that user.

## Moving the data to another machine

On a machine that has the runs:

```bash
python scripts/export_serving_data.py --output /path/to/mospi-data     # add --include-v1 for superseded V1 runs
```

On a machine without Python, the same can be done with the image:

```bash
docker run --rm -v "$PWD:/source:ro" -v /path/to/mospi-data:/out mospi-survey-validation:1.0 \
  python scripts/export_serving_data.py --project-root /source --output /out
```

The script exits with code 1 and lists `missing_source_runs` if any referenced run is absent. Copy `/path/to/mospi-data` to the target machine, then:

```bash
MOSPI_DATA_DIR=/path/to/mospi-data docker compose --profile seed run --rm seed
docker compose up -d
```

The bundle contains unit-level PLFS records. Transfer and store it only under the applicable GoI data-handling controls.

## Backing up the review audit trail

```bash
docker compose cp app:/data/fusion/runs/2024_first_visit_v2/review_audit.sqlite ./audit-backup-2024.sqlite
# or the whole writable part of the volume:
docker run --rm -v mospi-survey-validation_mospi-data:/data:ro -v "$PWD:/backup" alpine \
  tar czf /backup/mospi-fusion-runs.tgz -C /data fusion/runs
```

## Stopping, restarting, updating

```bash
docker compose stop                 # stop (data kept)
docker compose start                # start again
docker compose restart app          # restart
docker compose down                 # remove containers and network (volume kept)
docker compose build && docker compose up -d       # after a code update (volume kept)
docker compose logs -f app          # server log
```

The container restarts automatically unless it was stopped by hand (`restart: unless-stopped`).

## Batch processing in the container (optional)

The `batch` service runs the same pipeline as `python -m pipeline.run`. It works on the host folder `MOSPI_DATA_DIR`, which must contain the prepared inputs (`preprocessing/runs`, `peer_groups/runs`, `contextual/runs`):

```bash
docker compose --profile batch run --rm batch python -m pipeline.run --release 2025 --suffix v3
docker compose --profile seed run --rm seed           # make the new runs visible to the workspace
```

On Docker Desktop (Windows/macOS) this is much slower than a native run, because of the folder mount described above. Peak memory for the 2025 delivery (1.15 million persons) is about 2–3 GB.

## Running the tests in the container

```bash
docker compose --profile test build tests
docker compose --profile test run --rm tests          # pytest -q
```

## Security notes (what is and is not provided)

Provided:
* The port is published on `127.0.0.1` only.
* The process runs as non-root uid 10001, with all Linux capabilities dropped, `no-new-privileges`, and a read-only root filesystem (`/tmp` is a tmpfs).
* Stored runs are mounted read-only.
* Security headers are set: CSP `default-src 'self'`, `X-Frame-Options: DENY`, `nosniff`, `no-referrer`.
* There are no external network calls and no API documentation endpoints.

Optional token authentication: mount a users file and point `MOSPI_USERS_FILE_IN_CONTAINER` at it.

```json
{"users": [{"name": "A. Supervisor", "role": "supervisor", "token_sha256": "<sha256 hex of the token>"}]}
```

Roles are `supervisor` (may record decisions), `technical` (read-only) and `admin`. Add the mount with a `docker-compose.override.yml`:

```yaml
services:
  app:
    volumes:
      - ./secrets/users.json:/run/secrets/users.json:ro
```

Then set `MOSPI_USERS_FILE_IN_CONTAINER=/run/secrets/users.json`.

**Not provided, and required before any networked or production use:**
* TLS
* A GoI-approved identity provider or SSO and MFA
* Encryption at rest of the data volume
* Tamper-evident audit storage: the SQLite audit is append-only by application convention, not cryptographically protected
* Centralised logging, backup policy and a security review against the applicable GoI guidelines

Without authentication the server only starts on a non-loopback interface because the container sets `MOSPI_CONTAINER=1` and logs a warning. Do not publish the port beyond `127.0.0.1` without enabling authentication behind an approved TLS reverse proxy.

## Building behind a TLS-inspecting proxy or antivirus

If `docker compose build` fails with `CERTIFICATE_VERIFY_FAILED` while pip downloads packages, a proxy or antivirus is re-signing HTTPS traffic. Export its root certificate in PEM format and build with:

```bash
MOSPI_EXTRA_CA_FILE=/path/to/proxy-root.pem docker compose build
```

The certificate is passed as a BuildKit secret: it is used only during `pip install` and is not stored in the image. On the development machine this was needed for the Avast Web/Mail Shield root.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `cannot access path …/_data/preprocessing/runs` when starting `app` | The volume has not been seeded. Run the `seed` service first. |
| `/healthz` returns 503, `"runs": 0` | No Fusion run in the volume. Seed from a directory that has `fusion/runs/<run>/fused_cases.parquet`. |
| `/healthz` returns 503 with a `false` entry in `source_runs_found` | A source run referenced by the Fusion run is missing. Re-seed from a complete `MOSPI_DATA_DIR`; the seed output lists `missing_source_runs`. |
| `"audit_store_writable": false` | `fusion/runs` is read-only or owned by another user. With the bind override on Linux, set `MOSPI_UID`/`MOSPI_GID` to the folder owner. |
| Pages take 10–30 s on Windows/macOS | You are using `docker-compose.bind.yml`. Use the default volume layout. |
| Port already in use | Set `MOSPI_PORT=8080` (or another free port). |
| Build fails with SSL errors | See "Building behind a TLS-inspecting proxy or antivirus". |
| Browser shows an old page after an update | Hard refresh. Asset URLs carry a version (`?v=…`). |
