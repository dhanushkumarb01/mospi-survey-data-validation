# Hosted (Vercel) to PostgreSQL on this laptop through a Cloudflare Tunnel

Status 12 Oct 2026: the gateway, the Vercel client and the access controls are implemented and verified locally on synthetic data
(§6). The Cloudflare account, tunnel, hostname and Access policy are **not set up yet**: they need your Cloudflare account (§4).
Nothing is reachable from the internet until you complete §4. This replaces the direct-connection plan in POSTGRESQL.md §7, which
was blocked by double NAT.

## 1. How it works

```
Vercel function ──HTTPS──▶ Cloudflare edge ──(Access: service token required)──▶ tunnel ◀──outbound── cloudflared (Windows service)
                                                                                                         │ http://127.0.0.1:8787
                                                                                    gateway (python -m mospi.gateway serve)
                                                                                                         │ loopback, role mospi_reader
                                                                                                PostgreSQL 17 (hosted_* views only)
```

* **No inbound port.** `cloudflared` makes only outbound connections to Cloudflare, so no router port forward or firewall rule is needed.
* **PostgreSQL is not exposed.** The tunnel routes one hostname, and only paths under `/v1/`, to the gateway on `127.0.0.1:8787`.
  `pg_hba.conf` now rejects every login from beyond this computer (`python -m mospi.db.remote_access hba --tunnel-only`).
* **The gateway has a fixed set of read-only routes.** They match what the hosted app already read directly:

  | Route (GET only) | Hosted use |
  |---|---|
  | `/v1/status` | "database reachable" signal (role, TLS) |
  | `/v1/summary` | status strip: cleared runs, last integrity check, chain verifications, failed jobs |
  | `/v1/runs/{run}/statuses`, `/events`, `/verification` | review status per case, decision events, last recorded chain check |
  | `/v1/runs/{run}/cases/{case}/history` | one case's audit history |

  Each route returns exactly what the hosted reader returned before. Comments, evidence snapshots, corrected values and uncleared
  runs are excluded by the `hosted_*` views, which the reader role is limited to.

## 2. Access controls (each layer works on its own)

| Layer | Control |
|---|---|
| Cloudflare Access | Requests without the Vercel service token (`CF-Access-Client-Id/Secret`) are stopped at the edge (403). |
| cloudflared ingress | One hostname, path `^/v1/`, one origin (`127.0.0.1:8787`); everything else gets 404 from cloudflared. |
| Gateway | Listens on 127.0.0.1 only and refuses a non-loopback peer. Every request needs an HMAC-SHA256 signature over method, exact path, time and nonce (`MOSPI_GATEWAY_SECRET`, 32+ characters, never sent). Requests are accepted within ±120 s, and each nonce once (no replay). GET only (405 otherwise), no request body, ids checked against a pattern, no docs or OpenAPI, 600 requests per minute, and 429 after 30 failed signatures per minute. Unsigned requests get 401 before routing or any database call. Logs record method, path, status, time and cf-ray, never headers. |
| Database | The gateway refuses to start unless it is logged in as `mospi_reader` with a read-only session on a loopback host. That role can SELECT only the `hosted_*` views. Database triggers keep audit events append-only. |
| Vercel client | Requires `https://`. Never follows redirects (an Access login redirect counts as a failure). Every failure becomes "database unavailable" with a reason, never with a secret. |

## 3. Environment variables

Laptop (git-ignored `.env`; `MOSPI_GATEWAY_SECRET` is already generated there):

| Variable | Meaning |
|---|---|
| `MOSPI_GATEWAY_SECRET` | request-signing secret (same value in Vercel). Generate with `python -m mospi.gateway secret` |
| `MOSPI_GATEWAY_SECRET_PREVIOUS` | optional, accepted during rotation |
| `MOSPI_GATEWAY_PORT` (8787), `MOSPI_GATEWAY_RATE_PER_MINUTE` (600), `MOSPI_GATEWAY_DB_CONNECTIONS` (4) | limits |
| `MOSPI_GATEWAY_HOSTNAME` | optional: the public hostname. Other `Host` headers then get 421 |
| `MOSPI_GATEWAY_DATABASE_URL` | optional: by default the reader URL is derived from `MOSPI_DATABASE_URL` + `MOSPI_DB_READER_PASSWORD` (loopback only) |
| `MOSPI_GATEWAY_URL`, `MOSPI_CF_ACCESS_CLIENT_ID`, `MOSPI_CF_ACCESS_CLIENT_SECRET` | only for `python -m mospi.gateway check` from this laptop |

Vercel project (Production). Mark every secret as **Sensitive**:

```
MOSPI_AUDIT_BACKEND=gateway
MOSPI_GATEWAY_URL=https://<gateway hostname>
MOSPI_GATEWAY_SECRET=<same value as in .env>                 # Sensitive
MOSPI_CF_ACCESS_CLIENT_ID=<service token Client ID>          # Sensitive
MOSPI_CF_ACCESS_CLIENT_SECRET=<service token Client Secret>  # Sensitive
MOSPI_USERS_JSON=<as before>
# optional: MOSPI_GATEWAY_TIMEOUT=8, MOSPI_GATEWAY_CACHE_SECONDS=5
```

Delete `MOSPI_DATABASE_URL` and `MOSPI_DB_CA_FILE` from Vercel if they were added. Vercel no longer holds any database credential.

## 4. What you set up (Cloudflare account, hostname, tokens)

You need a Cloudflare account (the free plan is enough) and a domain whose DNS is on Cloudflare. The gateway hostname is a
subdomain of it, for example `mospi-gateway.<your-domain>`. Zero Trust must be enabled once (the free plan, up to 50 users).

1. **Install cloudflared**: `winget install --id Cloudflare.cloudflared`.
2. **Create the tunnel** in the Zero Trust dashboard: Networks → Tunnels → Create a tunnel → *Cloudflared* → name it
   `mospi-gateway` → Windows. In an elevated PowerShell, run the `cloudflared.exe service install <TOKEN>` command it shows. The token
   is stored only in the Windows service; do not put it in the repository or `.env`. The tunnel should then show *Healthy*.
3. **Route the hostname** (in the tunnel's *Public hostname* / *Published application routes* tab): subdomain `mospi-gateway`,
   your domain, path `^/v1/`, service type **HTTP**, URL `127.0.0.1:8787`. Add no other routes. Never add a TCP route or port 5432.
   (For a locally managed tunnel, use `deploy/cloudflare/config.example.yml` instead.)
4. **Service token**: Access → Service auth → Service Tokens → *Create* `mospi-vercel`. Copy the Client ID and Client Secret; the
   secret is shown only once.
5. **Access application**: Access → Applications → Add → *Self-hosted* → domain `mospi-gateway.<your-domain>` (whole host) → one
   policy, action **Service Auth**, include **Service Token = mospi-vercel**. Add no Allow/Bypass policy for people or "Everyone".
6. **Run the gateway**: `powershell -ExecutionPolicy Bypass -File deploy\cloudflare\install-gateway-task.ps1` (starts it now and at
   each log-on), or `python -m mospi.gateway serve` in a terminal.
7. **Verify before Vercel**: add `MOSPI_GATEWAY_URL=https://mospi-gateway.<your-domain>`, `MOSPI_CF_ACCESS_CLIENT_ID` and
   `MOSPI_CF_ACCESS_CLIENT_SECRET` to `.env`, then run `python -m mospi.gateway check`. Every line must be `ok` and the verdict
   `PASSED`:
   * `no_credentials_refused`: HTTP 403 from Access. If it is 401 or 200, the Access application is missing or wrong. **Stop here.**
   * `access_token_without_signature_refused` (401), `wrong_secret_refused`, `replayed_request_refused`, `unknown_route_refused`, `write_method_refused`;
   * `database_role: mospi_reader`, and `runs_visible_to_hosted` lists only SYNTHETIC (or approved) runs.

   From a browser, `https://mospi-gateway.<your-domain>/v1/status` must show a Cloudflare Access block page, not data.
8. **Vercel**: set the variables in §3, remove the old ones, and redeploy (`vercel --prod`, or redeploy the latest deployment in the dashboard).

## 5. Verifying the hosted connection

1. `https://<vercel app>/healthz` returns `"audit_backend": "postgres"` and `"audit_store": "read-only"`.
2. Sign in on the hosted workspace. The status strip says *Operational records: PostgreSQL (read live from the processing machine)*.
   `GET /api/operations` (with your bearer token) shows `"database": {"reachable": true, "role": "mospi_reader", "via": "gateway"}`
   and only cleared runs.
3. On the laptop, record a decision on a case of the synthetic run (local app). Within about 5 s the hosted case shows it in its
   history, without the comment.
4. The gateway log (`%LOCALAPPDATA%\MoSPI\logs\gateway.log` when run as the task) shows `GET /v1/... -> 200` lines with a `cf-ray` id. Requests from Vercel always have one.
5. Failure drill: stop the gateway (`Stop-ScheduledTask "MoSPI hosted read gateway"`). The hosted status strip then says
   *unreachable* and review-dependent API calls return 503 ("The hosted read gateway did not answer (502: the tunnel is up but the gateway is not running)"). Start it again
   and the hosted app recovers without a redeploy.

## 6. Verified locally (12 Oct 2026, synthetic data only)

* `python -m pytest`: 11 new gateway tests (signing window, replay, rotation, unsigned/wrong-secret/replay refusals with no database
  call, fixed routes, 404 for unknown or invalid ids including `__operations__`, 405 for every write method, body refused, loopback-peer
  and host checks, rate and failure limits, 503 without detail on database outage, client error mapping for 302/403/429/503/530 and
  timeouts, https enforcement, the Vercel entrypoint through the gateway and with it down or misconfigured).
* `python -m pytest --postgres`: 2 more tests against the real reader role. Through the gateway the results equal the direct hosted
  reader's. The uncleared run, comments and snapshots stay invisible. The gateway refuses to start as `mospi_app` or on a
  non-loopback host.
* Live: `python -m mospi.gateway serve` on the operational database, then `python -m mospi.gateway check --url http://127.0.0.1:8787`
  gave PASSED. Only `2024_first_visit_demo (SYNTHETIC)` was visible, as `mospi_reader`. The Vercel entrypoint (`VERCEL=1`,
  environment only) read live through the gateway. With the gateway stopped, it returned 503 with a clear reason and still refused
  writes and uploads.
* `pg_hba.conf` was switched to tunnel-only (backup in `%LOCALAPPDATA%\MoSPI\pki\pg_hba.conf.20261011T193048Z.bak`). A reader login
  through this laptop's LAN address 10.7.12.102 is now rejected; loopback is unchanged. `deploy/postgres/allow-remote-postgres.ps1`
  now refuses to open port 5432.

## 7. Rotation, revocation and residual risks

* **Gateway secret**: generate a new one. Put the old value in `MOSPI_GATEWAY_SECRET_PREVIOUS` and the new one in `MOSPI_GATEWAY_SECRET`
  on the laptop, restart the gateway, update Vercel and redeploy, then remove `..._PREVIOUS`.
* **Service token**: create a new one, add it to the Access policy, update Vercel, redeploy, then revoke the old one. Revoking
  a token, or deleting the tunnel route, cuts hosted access at once.
* **Residual risks**: the laptop must stay on and connected (otherwise the hosted app shows "unreachable"). Cloudflare terminates TLS
  and can see responses: these are decision metadata of cleared runs only, never comments, survey values or uncleared runs.
  PostgreSQL still has `listen_addresses='*'`; with tunnel-only `pg_hba` and no firewall rule this is not reachable, but setting it to
  `localhost` (needs a service restart) removes the listener entirely.
