"""Local FastAPI surface for the MoSPI survey data validation review workspace.

Security boundary (see docs/stages/fusion/README.md): the service binds to 127.0.0.1 by
default and sends nothing to external services.  Sign-in with named accounts
(``users``: mospi/auth, routes in auth_api.py) assigns each request a user and
one of three roles (admin, supervisor, analyst); the audit trail records that
signed-in name.  It is not a substitute for the GoI-approved identity, network
and hosting controls required before deployment.

Deployment modes (docs/deployment/VERCEL_REVIEW_ONLY_DEPLOYMENT.md):
* ``review_only`` - no batch can be started, listed or queued; enforced here on the
  server, not only in the UI.
* ``audit_read_only`` - for hosts without a durable, shared disk: recorded decisions
  and audit history are read, but nothing is appended (decisions, case-opened events
  and the logged CSV export are refused with an explicit reason instead of being
  written to temporary storage).
* ``require_authentication`` - every /api request is refused until an account
  store is configured.  Without a store and without this flag the API is open
  (tests and the synthetic anonymous demo only; the servers always pass a store).
"""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
import logging
from typing import Any, Callable, Iterator

import duckdb
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from mospi.pipeline.stages.fusion import labels as L
from mospi.pipeline.stages.fusion.evidence_card import build_evidence_card
from mospi.pipeline.stages.fusion.explain import PATTERN_KEYS, UNUSUAL, SourceResolver, build_story, pattern_item, pattern_rows, summarise_rows
from mospi.pipeline.stages.fusion.feedback import recalibration_report
from mospi.pipeline.stages.fusion.review import REASON_CODES, VERIFICATION_SOURCES, DecisionConflict
from mospi.pipeline.stages.fusion.story import build_lane_story
from mospi.db.audit import SqliteAuditStore
from mospi.db.connection import DatabaseUnavailable
from mospi.paths import data_root
from mospi.survey_rules.plfs import period_label
from mospi.pipeline.jobs import JobError, JobManager
from mospi.auth import UserStore, can
from mospi.auth.sessions import SessionSigner, signer_from_env

from .auth_api import NOT_CONFIGURED, PASSWORD_CHANGE_REQUIRED, PASSWORD_ROUTES, PUBLIC_ROUTES, Authenticator, resolve_user, session_payload
from .auth_api import register as register_auth

CODE_VERSION = os.environ.get("MOSPI_CODE_VERSION", "").strip() or None


CASE_FIELDS = ["case_id", "source_observation_id", "release", "observation_type", "visit", "month", "state", "sector", "stratum", "fsu",
               "statistical_rank", "contextual_rank", "ml_rank", "historical_rank", "pattern_rank", "risk_score", "influence_score", "raw_influence",
               "influence_target", "priority_score", "priority_rank", "priority_band", "override_applied", "rule_violation", "rule_error_count",
               # lane design (fusion v2.1)
               "case_level", "household_key", "district", "tier", "lane", "lanes", "tier_reason", "queue_position", "value_p", "value_lead_variable",
               "value_lead_mechanism", "value_lead_direction", "value_lead_observed", "value_lead_typical", "value_variables_assessed", "coding_p",
               "coding_code", "impact_se", "fsu_q_value", "fsu_notable", "rule_ids", "rule_warning_count"]
CASE_COLUMNS = ", ".join(CASE_FIELDS)  # kept for compatibility; queries use the columns a run actually has
# Additional stored fields needed to write plain-language list summaries.
SUMMARY_FIELDS = ["target_variable", "percentile_position", "peer_group_size", "ml_statement", "pattern_statement", "pattern_notable_checks",
                  "contextual_status", "provenance_json"]
ALLOWED_FILTERS = {"priority_band", "state", "sector", "stratum", "fsu", "release", "visit", "month", "tier", "case_level", "district", "household_key"}
LANE_CODES = {"RULE", "RULE_SOFT", "VALUE", "CODING"}
REVIEW_FILTERS = {"UNREVIEWED", "REVIEWED", *L.DECISIONS}
# Requests that change state must carry this header: a page on another site cannot add it without a CORS preflight,
# which this API never grants (cross-site request forgery).
REQUEST_HEADER = "x-mospi-request"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
REVIEW_ONLY_REASON = ("This instance is review-only. Validation batches are run separately on the processing machine and published "
                      "here as finished runs; they cannot be started from this instance.")
AUDIT_READ_ONLY_REASON = ("This instance has no durable audit store, so decisions cannot be recorded here, and CSV exports (which are "
                          "logged in the audit trail) are not offered. Recorded decisions and audit history are shown read-only.")
HOSTED_READ_ONLY_REASON = ("Decisions are recorded on the processing machine; recorded decisions and audit history are shown here "
                           "read-only.")
EXPORT_REASON = "CSV export is not offered on this instance; it is available on the processing machine."
DECISION_NOT_SAVED_REASON = ("Your decision could not be saved just now, and nothing was recorded. Please try again in a minute; "
                             "if it keeps happening, tell the administrator.")
NO_USERS_REASON = "Sign-in is required on this deployment, but no account store is configured. No data is served until it is."
DATABASE_DOWN_REASON = ("The review database cannot be reached just now, so this page cannot be shown and nothing was changed. "
                        "Please try again in a minute; if it keeps happening, tell the administrator.")
# Routes that describe the instance itself and need no review data.
NO_DATA_ROUTES = {"/api/session", "/api/session/required", "/api/deployment", "/api/labels", "/api/version", "/api/auth/login", "/api/auth/logout",
                  "/api/auth/password", "/api/users"}
LOG = logging.getLogger("MoSPI.api")


def _columns(path: Path) -> set[str]:
    with duckdb.connect() as connection:
        return set(connection.execute("SELECT * FROM read_parquet(?) LIMIT 0", [str(path)]).fetchdf().columns)


def _select(path: Path, fields: list[str]) -> str:
    available = _columns(path)
    return ", ".join(f'"{f}"' for f in fields if f in available)


class FusionRepository:
    def __init__(self, root: Path, audit: Any = None, hidden_runs: Any = None) -> None:
        self.root = root
        self.audit = audit or SqliteAuditStore()
        # Runs the registry says are not reviewable (still being produced, failed or withdrawn) are never listed.
        self.hidden_runs = hidden_runs or (lambda: set())

    def runs(self) -> list[dict[str, Any]]:
        rows = []
        hidden = self.hidden_runs()
        for directory in sorted(self.root.glob("*"), reverse=True):
            metadata_path = directory / "run_metadata.json"
            if directory.name not in hidden and metadata_path.is_file() and (directory / "fused_cases.parquet").is_file():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                rows.append({"directory": directory.name, **metadata})
        # Current-method (lane) runs first, then the latest survey round; superseded runs after them.
        rows.sort(key=lambda r: ("lanes" in str(r.get("fusion_version", "")), str(r.get("release", "")), str(r.get("directory", ""))), reverse=True)
        return rows

    def path(self, run: str | None) -> Path:
        available = self.runs()
        if not available:
            raise HTTPException(404, "No Fusion run is available. Run `python -m mospi.pipeline.stages.fusion.cli` first.")
        selected = run or available[0]["directory"]
        directory = self.root / selected
        if directory not in [self.root / item["directory"] for item in available]:
            raise HTTPException(404, "Unknown Fusion run.")
        return directory

    @staticmethod
    def query(path: Path, sql: str, values: list[Any] | None = None) -> list[dict[str, Any]]:
        with duckdb.connect() as connection:
            result = connection.execute(sql, [str(path), *(values or [])]).fetchdf()
        return json.loads(result.to_json(orient="records"))

    @staticmethod
    def metadata(directory: Path) -> dict[str, Any]:
        return json.loads((directory / "run_metadata.json").read_text(encoding="utf-8"))

    def where(self, directory: Path, *, query: str | None, filters: dict[str, Any]) -> tuple[str, list[Any]]:
        clauses, values = [], []
        for name, value in filters.items():
            if value and name in ALLOWED_FILTERS:
                clauses.append(f'"{name}" = ?')
                values.append(value)
        evidence_source = filters.get("evidence_source")
        if evidence_source in {"statistical", "contextual", "ml", "pattern", "historical"}:
            clauses.append(f'"{evidence_source}_status" = \'ASSESSABLE\'')
        lane = filters.get("lane")
        if lane in LANE_CODES and "lanes" in _columns(directory / "fused_cases.parquet"):
            clauses.append("list_contains(string_split(COALESCE(lanes, ''), ','), ?)")
            values.append(lane)
        strong_source = filters.get("strong_source")
        if strong_source in {"statistical", "contextual", "ml", "historical"} and f"{strong_source}_rank" in _columns(directory / "fused_cases.parquet"):
            clauses.append(f'"{strong_source}_rank" >= {UNUSUAL}')
        if query:
            clauses.append("(source_observation_id ILIKE ? OR case_id ILIKE ? OR fsu ILIKE ?)")
            values.extend([f"%{query}%"] * 3)
        review = filters.get("review_status")
        if review in REVIEW_FILTERS:
            statuses = self.audit.latest_statuses(directory)
            if review == "UNREVIEWED":
                reviewed = list(statuses)
                if reviewed:
                    clauses.append("case_id NOT IN (SELECT UNNEST(?))")
                    values.append(reviewed)
            else:
                chosen = [case for case, decision in statuses.items() if review == "REVIEWED" or decision == review]
                clauses.append("case_id IN (SELECT UNNEST(?))")
                values.append(chosen or ["__none__"])
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), values

    def case_rows(self, directory: Path, *, offset: int, limit: int, query: str | None, filters: dict[str, Any],
                  summaries: bool = False) -> tuple[list[dict[str, Any]], int]:
        where, values = self.where(directory, query=query, filters=filters)
        parquet = directory / "fused_cases.parquet"
        total = self.query(parquet, f"SELECT COUNT(*) AS total FROM read_parquet(?){where}", values)[0]["total"]
        columns = _select(parquet, CASE_FIELDS + (SUMMARY_FIELDS if summaries else []))
        rows = self.query(parquet, f"SELECT {columns} FROM read_parquet(?){where} ORDER BY priority_score DESC NULLS LAST, source_observation_id LIMIT ? OFFSET ?", [*values, limit, offset])
        statuses = self.audit.latest_statuses(directory)
        for index, row in enumerate(rows):
            row["review_status"] = statuses.get(row["case_id"], "UNREVIEWED")
            row["review_label"] = L.DECISIONS.get(row["review_status"], row["review_status"])
            row["position"] = offset + index + 1
        return rows, int(total)


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def create_app(fusion_root: Path | None = None, project_root: Path | None = None, batch_datasets: dict[str, dict[str, Any]] | None = None, *,
               users: UserStore | None = None, session_signer: SessionSigner | None = None, review_only: bool = False,
               audit_read_only: bool = False, require_authentication: bool = False, audit_store: Any = None, operations: Any = None,
               before_data: Callable[[], None] | None = None, health_check: Callable[[], tuple[dict[str, Any], int]] | None = None,
               hosted: bool = False, allow_export: bool | None = None) -> FastAPI:
    """``users`` is the account store (mospi/auth); with it every /api request but sign-in needs a session cookie signed by
    ``session_signer`` (default: from ``MOSPI_SESSION_SECRET``; required when ``hosted``).  ``before_data`` runs after
    authentication and before any data route (the hosted instance fetches its review data from the database there, so an
    unauthenticated request never causes a download); ``health_check`` replaces the file-based /healthz; ``hosted`` keeps
    database error details out of responses (they are logged instead); ``allow_export`` (default: whenever decisions can be
    recorded) offers the logged CSV export."""
    app = FastAPI(title="MoSPI Survey Data Validation", docs_url=None, redoc_url=None, openapi_url=None)
    fusion_root = Path(fusion_root) if fusion_root is not None else data_root() / "fusion" / "runs"
    audit = audit_store or SqliteAuditStore()
    if not audit.writable:
        audit_read_only = True
    exports = (not audit_read_only) if allow_export is None else (allow_export and not audit_read_only)
    read_only_reason = HOSTED_READ_ONLY_REASON if hosted else AUDIT_READ_ONLY_REASON
    repository = FusionRepository(fusion_root, audit, operations.hidden_runs if operations is not None else None)
    root = Path(project_root) if project_root else Path(fusion_root).resolve().parent.parent
    # Source runs live beside fusion/ in the project root (<root>/fusion/runs).
    resolver = SourceResolver(root)
    auth = None
    if users is not None:
        auth = Authenticator(users, session_signer if session_signer is not None else signer_from_env(required=hosted), hosted=hosted)
    # In review-only mode no job manager exists, so no code path can start or list a batch.
    jobs = None if review_only else JobManager(root, batch_datasets)
    manifest_path = root / "SERVING_DATA_MANIFEST.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    except (OSError, ValueError):
        manifest = {}
    data_notice = manifest.get("notice") if manifest.get("synthetic") else None

    def database_down(error: Exception) -> JSONResponse:
        # No silent fallback: nothing is written elsewhere, and the message never carries credentials.  The hosted
        # instance gives the plain message only (host names and driver errors go to the log).
        if hosted:
            LOG.error("Database unavailable: %s", error)
            return JSONResponse({"detail": DATABASE_DOWN_REASON, "database_unavailable": True}, status_code=503)
        return JSONResponse({"detail": f"The operational database is unavailable, so this request was not completed. {error}"}, status_code=503)

    @app.exception_handler(DatabaseUnavailable)
    async def database_unavailable(request: Request, error: DatabaseUnavailable) -> JSONResponse:
        return database_down(error)

    @app.middleware("http")
    async def security(request: Request, call_next):
        user = None
        path = request.url.path
        is_api = path.startswith("/api/") and path != "/api/session/required"
        if is_api and require_authentication and auth is None:
            return JSONResponse({"detail": NO_USERS_REASON}, status_code=503)
        if auth is not None and is_api:
            if request.method not in SAFE_METHODS and request.headers.get(REQUEST_HEADER) != "1":
                return JSONResponse({"detail": "This request was refused: it did not come from the workspace."}, status_code=403)
            if auth.signer is None:
                return JSONResponse({"detail": NOT_CONFIGURED}, status_code=503)
            try:
                user = await resolve_user(auth, request)
            except DatabaseUnavailable as error:
                return database_down(error)
            if user is None and path not in PUBLIC_ROUTES and path != "/api/auth/logout":
                return JSONResponse({"detail": "Authentication required."}, status_code=401)
            if user is not None and user["must_change_password"] and path not in PUBLIC_ROUTES | PASSWORD_ROUTES:
                return JSONResponse({"detail": PASSWORD_CHANGE_REQUIRED, "password_change_required": True}, status_code=403)
            if request.method == "POST" and path.endswith("/events") and not can(user, "decide"):
                return JSONResponse({"detail": "Your role cannot record review decisions."}, status_code=403)
            if request.method == "POST" and path == "/api/batch" and not can(user, "run"):
                return JSONResponse({"detail": "Only an administrator can start a batch validation."}, status_code=403)
        if review_only and path.startswith("/api/batch") and request.method not in ("GET", "HEAD"):
            return JSONResponse({"detail": REVIEW_ONLY_REASON, "review_only": True}, status_code=403)
        if before_data is not None and is_api and path not in NO_DATA_ROUTES and not path.startswith("/api/users/"):
            try:
                await run_in_threadpool(before_data)
            except DatabaseUnavailable as error:
                return database_down(error)
            except Exception as error:   # noqa: BLE001 - e.g. a failed checksum: never serve partial data
                LOG.error("Review data could not be prepared: %s: %s", type(error).__name__, error)
                return JSONResponse({"detail": "The review data could not be loaded completely, so it is not shown. Please try again in a minute; "
                                               "if it keeps happening, tell the administrator.", "database_unavailable": True}, status_code=503)
        request.state.user = user
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def queue_filters(**values: Any) -> dict[str, Any]:
        return {k: v for k, v in values.items() if v not in (None, "")}

    def source_dir(directory: Path, module: str) -> Path | None:
        metadata = repository.metadata(directory)
        return resolver.run_dir(module, str(metadata["release"]), str(metadata["observation"]), metadata.get("source_runs", {}).get(module))

    @app.get("/api/session/required")
    def session_required() -> dict[str, Any]:
        return {"authentication": auth is not None or require_authentication}

    @app.get("/api/session")
    def session(request: Request) -> dict[str, Any]:
        return session_payload(auth, getattr(request.state, "user", None))

    register_auth(app, auth)

    @app.get("/api/deployment")
    def deployment() -> dict[str, Any]:
        """What this instance allows, so the UI can say so plainly (the server enforces it either way)."""
        return {"review_only": review_only, "batch_reason": REVIEW_ONLY_REASON if review_only else None,
                "audit_writable": not audit_read_only, "exports": exports, "audit_reason": read_only_reason if audit_read_only else None,
                "data_notice": data_notice, "audit_backend": audit.backend,
                "notes_shown": not getattr(audit, "hosted", False),   # the hosted views leave out reviewers' notes
                "uploads": operations is not None and not getattr(operations, "hosted", True) and not review_only}

    @app.get("/api/runs")
    def list_runs() -> list[dict[str, Any]]:
        return repository.runs()

    @app.get("/api/labels")
    def code_labels() -> dict[str, Any]:
        return {"states": L.STATES, "sectors": L.SECTORS, "bands": L.PRIORITY_BANDS, "decisions": L.DECISIONS, "lanes": L.LANES,
                "reason_codes": {decision: {code: L.REASON_CODES[code] for code in sorted(codes)} for decision, codes in REASON_CODES.items()},
                "verification_sources": {code: L.VERIFICATION_SOURCES[code] for code in sorted(VERIFICATION_SOURCES)}}

    @app.get("/api/summary")
    def summary(run: str | None = None) -> dict[str, Any]:
        directory = repository.path(run)
        report = json.loads((directory / "fusion_report.json").read_text(encoding="utf-8"))
        return {"run": directory.name, "metadata": repository.metadata(directory), "report": report}

    @app.get("/api/overview")
    def overview(run: str | None = None) -> dict[str, Any]:
        """Supervisor-level counts: priority bands, review progress, group alerts."""
        directory = repository.path(run)
        parquet = directory / "fused_cases.parquet"
        report = json.loads((directory / "fusion_report.json").read_text(encoding="utf-8"))
        bands = {row["priority_band"]: row["records"] for row in repository.query(parquet, "SELECT priority_band, COUNT(*) AS records FROM read_parquet(?) GROUP BY 1")}
        statuses = audit.latest_statuses(directory)
        available = _columns(parquet)
        lanes_method = "tier" in available
        top_band = "CHECK_NOW" if lanes_method else "CRITICAL"
        decisions = {key: 0 for key in ("CONFIRMED_ERROR", "VALID_BUT_UNUSUAL", "NEEDS_FIELD_VERIFICATION", "CANNOT_VERIFY", "ESCALATE")}
        for decision in statuses.values():
            decisions[decision] = decisions.get(decision, 0) + 1
        events = audit.all_events(directory)
        viewed = {event["case_id"] for event in events if event["event_type"] == "CASE_VIEWED"}
        last = max((event["event_timestamp_utc"] for event in events if event["event_type"] == "DECISION_MADE"), default=None)
        groups = repository.query(directory / "group_priorities.parquet", "SELECT group_priority_band, COUNT(*) AS groups FROM read_parquet(?) GROUP BY 1") \
            if (directory / "group_priorities.parquet").is_file() else []
        top_unreviewed, _ = repository.case_rows(directory, offset=0, limit=1, query=None, filters={"review_status": "UNREVIEWED"})
        # Decided cases per priority group, so progress can be shown against each group.
        reviewed_by_band = {row["priority_band"]: row["records"] for row in repository.query(
            parquet, "SELECT priority_band, COUNT(*) AS records FROM read_parquet(?) WHERE case_id IN (SELECT UNNEST(?)) GROUP BY 1",
            [list(statuses) or ["__none__"]])}
        # Where the highest-priority records sit, with each State/UT's total for context.
        states = repository.query(parquet, f"SELECT state, COUNT(*) FILTER (WHERE priority_band = '{top_band}') AS highest, COUNT(*) AS records "
                                           "FROM read_parquet(?) GROUP BY 1 HAVING highest > 0 ORDER BY highest DESC, state LIMIT 10")
        # Why the highest-priority records are there: how many have each record-level source at the
        # "unusual" display threshold.  A record can count under several sources (they overlap).
        reason_sql = {name: f"COUNT(*) FILTER (WHERE {column} >= {UNUSUAL})" for name, column in
                      (("statistical", "statistical_rank"), ("historical", "historical_rank"), ("ml", "ml_rank"), ("contextual", "contextual_rank"))
                      if column in available}
        if "rule_violation" in available:
            reason_sql["rules"] = "COUNT(*) FILTER (WHERE rule_violation)"
        if reason_sql:
            strong = [f"COALESCE({c}, 0) >= {UNUSUAL}" for c in ("statistical_rank", "historical_rank", "ml_rank", "contextual_rank") if c in available]
            strong += ["COALESCE(rule_violation, FALSE)"] if "rule_violation" in available else []
            reason_sql["combined_only"] = f"COUNT(*) FILTER (WHERE NOT ({' OR '.join(strong)}))"
        if lanes_method:
            reason_sql = {lane.lower(): f"COUNT(*) FILTER (WHERE list_contains(string_split(COALESCE(lanes, ''), ','), '{lane}'))" for lane in LANE_CODES}
        highest_reasons = repository.query(parquet, f"SELECT {', '.join(f'{v} AS {k}' for k, v in reason_sql.items())} FROM read_parquet(?) WHERE priority_band = '{top_band}'")[0] \
            if reason_sql else {}
        report_queue = report.get("queue", {})
        return {
            "run": directory.name, "metadata": repository.metadata(directory),
            "highest_reasons": {k: int(v or 0) for k, v in highest_reasons.items()}, "unusual_threshold": UNUSUAL,
            "method": "lanes" if lanes_method else "superseded_v2_0",
            "records_processed": report["records_processed"],
            "priority_rows": report.get("priority_rows", report["records_processed"] - int(bands.get("NOT_ASSESSABLE", 0))),
            "not_prioritised": int(bands.get("NOT_ASSESSABLE", 0)) if lanes_method else report["records_processed"] - report["priority_rows"],
            "rule_violation_records": report.get("rule_violation_records", (report.get("rule_findings") or {}).get("persons_with_hard_rule")),
            "household_rule_cases": (report.get("rule_findings") or {}).get("households_with_hard_rule"),
            "budget": report_queue, "burden": report.get("burden"), "coverage": report.get("coverage"),
            "bands": [{"band": band, "label": L.PRIORITY_BANDS[band], "records": int(bands.get(band, 0)),
                       "reviewed": int(reviewed_by_band.get(band, 0))}
                      for band in (("CHECK_NOW", "CHECK_IF_TIME", "NOT_FLAGGED", "NOT_ASSESSABLE") if lanes_method else ("CRITICAL", "HIGH", "MEDIUM", "LOW", "NOT_ASSESSABLE"))],
            "highest_by_state": [{"state": L.clean(row["state"]), "label": L.state_name(row["state"]), "highest": int(row["highest"]),
                                  "records": int(row["records"])} for row in states],
            "review": {"decided": len(statuses), "decisions": decisions, "opened_without_decision": len(viewed - set(statuses)), "last_decision_utc": last},
            "groups": [{"band": row["group_priority_band"], "label": L.GROUP_BANDS.get(row["group_priority_band"], L.PRIORITY_BANDS.get(row["group_priority_band"], row["group_priority_band"])),
                        "groups": row["groups"]} for row in groups],
            "first_unreviewed_position": None if not top_unreviewed else _position_of(repository, directory, top_unreviewed[0]["case_id"]),
            "parameters": repository.metadata(directory).get("parameters", {}),
            "aggregate_alerts": _aggregate_alert_count(source_dir(directory, "historical")),
        }

    @app.get("/api/cases")
    def cases(run: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200), q: str | None = None,
              priority_band: str | None = None, state: str | None = None, sector: str | None = None, stratum: str | None = None,
              fsu: str | None = None, release: str | None = None, visit: str | None = None, month: str | None = None,
              evidence_source: str | None = None, review_status: str | None = None, strong_source: str | None = None, summaries: bool = False,
              tier: str | None = None, lane: str | None = None, case_level: str | None = None, district: str | None = None) -> dict[str, Any]:
        directory = repository.path(run)
        filters = queue_filters(priority_band=priority_band, state=state, sector=sector, stratum=stratum, fsu=fsu, release=release,
                                visit=visit, month=month, evidence_source=evidence_source, review_status=review_status, strong_source=strong_source,
                                tier=tier, lane=lane, case_level=case_level, district=district)
        rows, total = repository.case_rows(directory, offset=offset, limit=limit, query=q, filters=filters, summaries=summaries)
        if summaries:
            metadata = repository.metadata(directory)
            summarise_rows(rows, resolver, str(metadata["release"]), str(metadata["observation"]))
        return {"rows": rows, "total": total, "offset": offset, "limit": limit}

    @app.get("/api/cases/{case_id}")
    def case_detail(case_id: str, run: str | None = None, story: bool = True) -> dict[str, Any]:
        directory = repository.path(run)
        parquet = directory / "fused_cases.parquet"
        rows = repository.query(parquet, "SELECT * FROM read_parquet(?) WHERE case_id=?", [case_id])
        if not rows:
            raise HTTPException(404, "Case not found.")
        row = rows[0]
        card_rows = []
        card_file = directory / "evidence_cards.parquet"
        if card_file.is_file():
            card_rows = repository.query(card_file, "SELECT evidence_card_json FROM read_parquet(?) WHERE case_id=?", [case_id])
        for field in [f for f in list(row) if f.endswith("_json")]:
            row[field.removesuffix("_json")] = json.loads(row.pop(field) or "{}")
        row["evidence_card"] = json.loads(card_rows[0]["evidence_card_json"]) if card_rows else build_evidence_card(pd.Series({**row, "provenance_json": json.dumps(row.get("provenance", {}))}))
        row["audit_history"] = audit.history(directory, case_id)
        statuses = audit.latest_statuses(directory)
        row["review_status"] = statuses.get(case_id, "UNREVIEWED")
        row["review_label"] = L.DECISIONS.get(row["review_status"], row["review_status"])
        if story:
            position = total = None
            if row.get("priority_score") is not None:
                position = repository.query(parquet, "SELECT COUNT(*) + 1 AS n FROM read_parquet(?) WHERE priority_score > ?", [row["priority_score"]])[0]["n"]
                total = repository.query(parquet, "SELECT COUNT(*) AS n FROM read_parquet(?) WHERE priority_score IS NOT NULL")[0]["n"]
            weight_share = None
            weight_column = "final_weight" if "final_weight" in row else "design_weight"
            try:
                weight = float(row.get(weight_column))
            except (TypeError, ValueError):
                weight = None
            if weight is not None:
                weight_share = repository.query(parquet, f"SELECT AVG(CASE WHEN w < $2 THEN 1.0 WHEN w = $2 THEN 0.5 ELSE 0.0 END) AS s "
                                                         f"FROM (SELECT TRY_CAST({weight_column} AS DOUBLE) AS w FROM read_parquet($1)) WHERE w IS NOT NULL", [weight])[0]["s"]
            if row.get("tier") is not None:
                row["story"] = build_lane_story(row, resolver, directory)
            else:   # superseded V2.0 run, shown for the record
                row["story"] = build_story(row, resolver, priority_position=position, priority_total=total, weight_share=weight_share)
                row["story"]["superseded_method"] = True
        return row

    @app.get("/api/queue/position")
    def queue_position(position: int = Query(..., ge=1), run: str | None = None, q: str | None = None, priority_band: str | None = None,
                       state: str | None = None, sector: str | None = None, stratum: str | None = None, fsu: str | None = None,
                       release: str | None = None, visit: str | None = None, month: str | None = None, evidence_source: str | None = None,
                       review_status: str | None = None, strong_source: str | None = None, tier: str | None = None, lane: str | None = None,
                       case_level: str | None = None, district: str | None = None) -> dict[str, Any]:
        """Return the case at a 1-based position in a filtered, priority-ordered list."""
        directory = repository.path(run)
        filters = queue_filters(priority_band=priority_band, state=state, sector=sector, stratum=stratum, fsu=fsu, release=release,
                                visit=visit, month=month, evidence_source=evidence_source, review_status=review_status, strong_source=strong_source,
                                tier=tier, lane=lane, case_level=case_level, district=district)
        rows, total = repository.case_rows(directory, offset=position - 1, limit=1, query=q, filters=filters)
        return {"case_id": rows[0]["case_id"] if rows else None, "position": position, "total": total}

    @app.post("/api/cases/{case_id}/events")
    def record_event(case_id: str, payload: dict[str, Any], request: Request, run: str | None = None) -> dict[str, Any]:
        if audit_read_only:
            raise HTTPException(503, read_only_reason)
        directory = repository.path(run)
        evidence = repository.query(directory / "fused_cases.parquet", "SELECT * FROM read_parquet(?) WHERE case_id=?", [case_id])
        if not evidence:
            raise HTTPException(404, "Case not found.")
        event_type = str(payload.get("event_type", "CASE_VIEWED"))
        if event_type not in {"CASE_VIEWED", "DECISION_MADE"}:
            raise HTTPException(422, "Unknown event type.")
        user = getattr(request.state, "user", None)
        if user is None and (require_authentication or hosted):   # the middleware already refuses this; never fall back to a typed name
            raise HTTPException(401, "Authentication required.")
        # Without sign-in the typed name is recorded but marked as unverified (plan N10).
        actor = user["name"] if user else str(payload.get("actor") or "local-supervisor")[:120]
        snapshot = build_evidence_card(pd.Series(evidence[0]))
        lane = (str(evidence[0].get("lanes") or "").split(",") or [None])[0] or None
        # Optional optimistic check: the client sends the last decision it saw (null = none).
        expected = {"expected_last_decision_id": payload.get("expected_last_decision_id")} if "expected_last_decision_id" in payload else {}
        try:
            return audit.append(directory, case_id=case_id, event_type=event_type, actor=actor,
                                decision=payload.get("decision"), comment=payload.get("comment"), evidence_snapshot=snapshot,
                                reason_code=payload.get("reason_code"), verification_source=payload.get("verification_source"),
                                corrected_field=payload.get("corrected_field"), corrected_value=payload.get("corrected_value"),
                                lane=lane, opened_at_utc=payload.get("opened_at_utc"), actor_authenticated=user is not None,
                                actor_role=user["role"] if user else None, **expected)
        except DecisionConflict as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except PermissionError as error:      # the audit store's own refusals are written for the reviewer
            raise HTTPException(503, str(error)) from error
        except Exception as error:            # noqa: BLE001 - unreachable database or a refused grant: plain reason here, detail in the log
            if not hosted:
                raise
            LOG.error("Decision not saved: %s: %s", type(error).__name__, error)
            raise HTTPException(503, DECISION_NOT_SAVED_REASON) from None

    @app.get("/api/reviews")
    def reviews(run: str | None = None, decision: str | None = None) -> dict[str, Any]:
        """Latest decision per reviewed case, newest first, with record context."""
        directory = repository.path(run)
        events = [e for e in audit.all_events(directory) if e["event_type"] == "DECISION_MADE"]
        latest: dict[str, dict[str, Any]] = {}
        for event in events:
            latest[event["case_id"]] = event
        chosen = [e for e in latest.values() if not decision or e["decision"] == decision]
        chosen.sort(key=lambda e: e["event_id"], reverse=True)
        context = {}
        if chosen:
            parquet = directory / "fused_cases.parquet"
            rows = repository.query(parquet, f"SELECT {_select(parquet, CASE_FIELDS)} FROM read_parquet(?) WHERE case_id IN (SELECT UNNEST(?))", [[e["case_id"] for e in chosen]])
            context = {r["case_id"]: r for r in rows}
        output = []
        for event in chosen:
            row = context.get(event["case_id"], {})
            key, _, person = str(row.get("source_observation_id", "")).partition("|person=")
            output.append({
                "case_id": event["case_id"], "decision": event["decision"], "decision_label": L.DECISIONS.get(event["decision"], event["decision"]),
                "actor": event["actor"], "actor_verified": bool(event.get("actor_authenticated")), "comment": event["comment"],
                "reason_code": event.get("reason_code"), "reason_label": L.REASON_CODES.get(event.get("reason_code"), event.get("reason_code")),
                "verification_source": event.get("verification_source"), "corrected_field": event.get("corrected_field"),
                "corrected_value": event.get("corrected_value"), "seconds_on_case": event.get("seconds_on_case"), "decided_at_utc": event["event_timestamp_utc"],
                "record_label": f"FSU {row.get('fsu')} · Household {key.split('|')[-1] if key else '—'} · Person {person or '—'}",
                "location_label": f"{L.state_name(row.get('state'))} · {L.sector_name(row.get('sector'))}",
                "band": row.get("priority_band"),
                "band_label": L.PRIORITY_BANDS.get(row.get("priority_band"), row.get("priority_band")),
                "decision_count": sum(1 for e in events if e["case_id"] == event["case_id"]),
            })
        return {"rows": output, "total": len(output)}

    @app.get("/api/patterns")
    def patterns(run: str | None = None, limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
        directory = repository.path(run)
        rows = repository.query(directory / "group_priorities.parquet", "SELECT * FROM read_parquet(?) ORDER BY group_priority_score DESC NULLS LAST LIMIT ?", [limit])
        return {"rows": rows}

    @app.get("/api/groups")
    def groups(run: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100), band: str | None = None,
               state: str | None = None) -> dict[str, Any]:
        """FSU-level group alerts with the strongest stored pattern described in plain language."""
        directory = repository.path(run)
        path = directory / "group_priorities.parquet"
        if not path.is_file():
            return {"rows": [], "total": 0, "offset": offset, "limit": limit, "pattern_available": False}
        clauses, values = [], []
        if band == "ALERTS":   # the FSUs with a group difference (clear or some)
            clauses.append("group_priority_band IN ('HIGH', 'MEDIUM')")
        elif band:
            clauses.append("group_priority_band = ?"); values.append(band)
        if state:
            clauses.append("state = ?"); values.append(state)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        total = repository.query(path, f"SELECT COUNT(*) AS n FROM read_parquet(?){where}", values)[0]["n"]
        rows = repository.query(path, f"SELECT * FROM read_parquet(?){where} ORDER BY group_priority_score DESC NULLS LAST, fsu LIMIT ? OFFSET ?", [*values, limit, offset])
        pattern_dir = source_dir(directory, "pattern")
        top: dict[tuple, list] = {}
        if rows and pattern_dir is not None:
            evidence_path = pattern_dir / "pattern_evidence.parquet"
            order = "q_value ASC NULLS LAST, evidence_rank DESC NULLS LAST" if "q_value" in _columns(evidence_path) else "evidence_rank DESC NULLS LAST"
            evidence = repository.query(evidence_path, f"SELECT * FROM read_parquet(?) WHERE fsu IN (SELECT UNNEST(?)) AND assessability_status='ASSESSABLE' ORDER BY {order}",
                                        [[r["fsu"] for r in rows]])
            for item in evidence:
                top.setdefault(tuple(L.clean(item.get(k)) for k in PATTERN_KEYS), []).append(item)
        for row in rows:
            items = [pattern_item(i) for i in top.get(tuple(L.clean(row.get(k)) for k in PATTERN_KEYS), [])]
            notable = [i for i in items if i["notable"]] or items[:1]
            row["location_label"] = f"{L.state_name(row.get('state'))} · {L.sector_name(row.get('sector'))} · Stratum {row.get('stratum')}"
            row["band_label"] = L.GROUP_BANDS.get(row.get("group_priority_band"), L.PRIORITY_BANDS.get(row.get("group_priority_band"), row.get("group_priority_band")))
            row["patterns"] = [{"title": p["title"], "text": p["text"], "strength": p["strength"], "notable": p["notable"]} for p in notable[:3]]
        return {"rows": rows, "total": int(total), "offset": offset, "limit": limit, "pattern_available": pattern_dir is not None}

    @app.get("/api/groups/{fsu}")
    def group_detail(fsu: str, run: str | None = None, state: str | None = None) -> dict[str, Any]:
        directory = repository.path(run)
        path = directory / "group_priorities.parquet"
        clause, values = ("fsu = ?", [fsu]) if not state else ("fsu = ? AND state = ?", [fsu, state])
        rows = repository.query(path, f"SELECT * FROM read_parquet(?) WHERE {clause}", values) if path.is_file() else []
        if not rows:
            raise HTTPException(404, "FSU not found in this run.")
        group = rows[0]
        pattern_dir = source_dir(directory, "pattern")
        items = [pattern_item(r) for r in pattern_rows(pattern_dir, group)]
        group["location_label"] = f"{L.state_name(group.get('state'))} · {L.sector_name(group.get('sector'))} · Stratum {group.get('stratum')}"
        group["band_label"] = L.GROUP_BANDS.get(group.get("group_priority_band"), L.PRIORITY_BANDS.get(group.get("group_priority_band"), group.get("group_priority_band")))
        return {"group": group, "patterns": items, "pattern_available": pattern_dir is not None}

    @app.get("/api/aggregates")
    def aggregates(run: str | None = None, level: str = Query("state", pattern="^(national|state|district)$"), indicator: str | None = None,
                   state: str | None = None, notable_only: bool = False, limit: int = Query(500, ge=1, le=5000)) -> dict[str, Any]:
        """Weighted CWS indicators by area and period, with screened period-on-period changes (historical layer)."""
        directory = repository.path(run)
        hist = source_dir(directory, "historical")
        path = hist / "aggregate_indicators.parquet" if hist else None
        if path is None or not path.is_file():
            return {"available": False, "rows": [], "notable": []}
        clauses, values = ["level = ?"], [level]
        if indicator:
            clauses.append("indicator = ?"); values.append(indicator)
        if state:
            clauses.append("state = ?"); values.append(state)
        if notable_only:
            clauses.append("notable_change")
        rows = repository.query(path, f"SELECT * FROM read_parquet(?) WHERE {' AND '.join(clauses)} ORDER BY indicator, state, district, sector, period_index LIMIT ?", [*values, limit])
        notable = repository.query(path, "SELECT * FROM read_parquet(?) WHERE notable_change ORDER BY ABS(robust_z) DESC")
        for row in rows + notable:
            row["area_label"] = (L.state_name(row.get("state")) if row.get("state") else "All India") + (f" · district {row['district']}" if row.get("district") else "") + f" · {L.sector_name(row.get('sector'))}"
        indicators = repository.query(path, "SELECT DISTINCT indicator, indicator_label FROM read_parquet(?) ORDER BY 1")
        report = json.loads((hist / "historical_report.json").read_text(encoding="utf-8")) if (hist / "historical_report.json").is_file() else {}
        return {"available": True, "rows": rows, "notable": notable, "indicators": indicators, "limitations": report.get("limitations", []),
                "periods": report.get("periods_in_pool", []), "design_period": repository.metadata(directory).get("design_period")}

    @app.get("/api/case-areas")
    def case_areas(run: str | None = None, state: str | None = None) -> dict[str, Any]:
        """Read-only counts for the Area trends page: records and cases by area, sector, interview period, list and reasons.

        One row per State/UT (or district of ``state``) x sector x period x list x stored reason set, so every record is
        counted exactly once; ``decided`` counts the cases of that row that have a decision.  Other current-method rounds
        of the same observation are summarised for comparison.  Nothing here changes a list, a case or a decision."""
        directory = repository.path(run)
        parquet = directory / "fused_cases.parquet"
        available = _columns(parquet)
        metadata = repository.metadata(directory)
        area = "district" if state else "state"
        if area not in available:
            return {"available": False, "rows": [], "reason": "This run has no district codes." if state else "This run has no State/UT codes."}
        period = "period_index" if "period_index" in available else "NULL"
        reasons = "COALESCE(lanes, '')" if "lanes" in available else "''"
        decided = list(audit.latest_statuses(directory)) or ["__none__"]
        rows = repository.query(parquet, f"SELECT {area} AS area, sector, {period} AS period_index, priority_band AS band, {reasons} AS lanes, "
                                         "COUNT(*) AS records, COUNT(*) FILTER (WHERE case_id IN (SELECT UNNEST($2))) AS decided "
                                         f"FROM read_parquet($1){' WHERE state = $3' if state else ''} GROUP BY ALL",
                                [decided, *([state] if state else [])])
        design = str(metadata.get("design_period") or "")
        out = [{"area": L.clean(r["area"]), "area_label": (f"District {L.clean(r['area'])}" if state else L.state_name(r["area"])),
                "sector": L.clean(r["sector"]), "period_index": None if pd.isna(r["period_index"]) else int(r["period_index"]),
                "band": r["band"], "lanes": [x for x in str(r["lanes"]).split(",") if x], "records": int(r["records"]), "decided": int(r["decided"])}
               for r in rows]
        periods = sorted({r["period_index"] for r in out if r["period_index"] is not None})
        result = {"available": True, "run": directory.name, "level": area, "state": state, "rows": out,
                  "periods": [{"index": p, "label": period_label(design, p)} for p in periods],
                  "budget": json.loads((directory / "fusion_report.json").read_text(encoding="utf-8")).get("queue", {}),
                  "method": "lanes" if "tier" in available else "superseded_v2_0"}
        if not state:
            rounds = []
            for item in repository.runs():
                if "lanes" not in str(item.get("fusion_version", "")) or item.get("observation") != metadata.get("observation"):
                    continue
                other = repository.root / item["directory"]
                counts = repository.query(other / "fused_cases.parquet",
                                          "SELECT COUNT(*) AS records, COUNT(*) FILTER (WHERE priority_band = 'CHECK_NOW') AS check_now, "
                                          "COUNT(*) FILTER (WHERE priority_band = 'CHECK_IF_TIME') AS check_if_time, "
                                          "COUNT(*) FILTER (WHERE priority_band = 'NOT_ASSESSABLE') AS not_assessable FROM read_parquet(?)")[0]
                covered = [r["p"] for r in repository.query(other / "fused_cases.parquet", "SELECT DISTINCT period_index AS p FROM read_parquet(?) "
                                                            "WHERE period_index IS NOT NULL ORDER BY 1")] if "period_index" in _columns(other / "fused_cases.parquet") else []
                queue = json.loads((other / "fusion_report.json").read_text(encoding="utf-8")).get("queue", {})
                rounds.append({"run": item["directory"], "release": item.get("release"), "fusion_version": item.get("fusion_version"),
                               **{k: int(v or 0) for k, v in counts.items()}, "budget_cases": queue.get("budget_cases"),
                               "review_budget_share": queue.get("review_budget_share"),
                               "periods": [period_label(str(item.get("design_period") or ""), int(p)) for p in covered]})
            result["rounds"] = sorted(rounds, key=lambda r: str(r["release"]))
        return result

    @app.get("/api/worklist")
    def worklist(run: str | None = None, state: str | None = None, district: str | None = None, fsu: str | None = None,
                 tier: str = Query("A", pattern="^(A|B|AB)$"), offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)) -> dict[str, Any]:
        """Queued cases grouped by FSU and household (verification is done per household visit or call; plan W8.1)."""
        directory = repository.path(run)
        parquet = directory / "fused_cases.parquet"
        if "tier" not in _columns(parquet):
            raise HTTPException(409, "This run uses the superseded V2.0 method and has no tiered worklist.")
        tiers = ["A", "B"] if tier == "AB" else [tier]
        clauses, values = ["tier IN (SELECT UNNEST(?))"], [tiers]
        for name, value in (("state", state), ("district", district), ("fsu", fsu)):
            if value:
                clauses.append(f'"{name}" = ?'); values.append(value)
        where = " WHERE " + " AND ".join(clauses)
        groups = repository.query(parquet, f"SELECT state, sector, fsu, COUNT(*) AS cases, MIN(queue_position) AS first_position, "
                                           f"MAX(CAST(fsu_notable AS INTEGER)) AS fsu_alert FROM read_parquet(?){where} GROUP BY 1, 2, 3 "
                                           f"ORDER BY first_position LIMIT ? OFFSET ?", [*values, limit, offset])
        total = repository.query(parquet, f"SELECT COUNT(*) AS n FROM (SELECT DISTINCT state, sector, fsu FROM read_parquet(?){where})", values)[0]["n"]
        statuses = audit.latest_statuses(directory)
        if groups:
            keys = [f"{g['state']}|{g['sector']}|{g['fsu']}" for g in groups]
            columns = _select(parquet, CASE_FIELDS)
            rows = repository.query(parquet, f"SELECT {columns} FROM read_parquet(?){where} AND (state || '|' || sector || '|' || fsu) IN (SELECT UNNEST(?)) "
                                             f"ORDER BY queue_position", [*values, keys])
            by_fsu: dict[str, dict[str, list]] = {}
            for row in rows:
                row["review_status"] = statuses.get(row["case_id"], "UNREVIEWED")
                row["review_label"] = L.DECISIONS.get(row["review_status"], row["review_status"])
                row["lane_labels"] = [L.LANES.get(x, x) for x in str(row.get("lanes") or "").split(",") if x]
                household = row.get("household_key") or str(row["source_observation_id"]).split("|person=")[0].removesuffix("|household")
                by_fsu.setdefault(f"{row['state']}|{row['sector']}|{row['fsu']}", {}).setdefault(household, []).append(row)
            for group in groups:
                households = by_fsu.get(f"{group['state']}|{group['sector']}|{group['fsu']}", {})
                group["location_label"] = f"{L.state_name(group['state'])} · {L.sector_name(group['sector'])}"
                group["households"] = [{"household_key": key, "household": key.split("|")[-1], "cases": cases} for key, cases in households.items()]
                group["decided"] = sum(1 for cases in households.values() for c in cases if c["review_status"] != "UNREVIEWED")
        return {"rows": groups, "total": int(total), "offset": offset, "limit": limit}

    @app.get("/api/feedback")
    def feedback(run: str | None = None) -> dict[str, Any]:
        """Decision-based recalibration report (proposals only; nothing is applied)."""
        directory = repository.path(run)
        parquet = directory / "fused_cases.parquet"
        if "tier" not in _columns(parquet):
            return {"available": False, "reason": "Superseded V2.0 run: no lanes or tiers."}
        statuses = audit.latest_statuses(directory)
        cases = pd.DataFrame(repository.query(parquet, "SELECT case_id, tier, lane FROM read_parquet(?) WHERE tier IN ('A', 'B') OR case_id IN (SELECT UNNEST(?))",
                                              [list(statuses) or ["__none__"]]))
        events = [e for e in audit.all_events(directory) if e["event_type"] == "DECISION_MADE" and e.get("seconds_on_case") is not None]
        seconds = sorted(float(e["seconds_on_case"]) for e in events)
        report = recalibration_report(cases, statuses) if len(cases) else {"decided_cases": 0}
        report["median_minutes_per_decided_case"] = round(seconds[len(seconds) // 2] / 60, 1) if seconds else None
        return {"available": True, **report}

    @app.get("/api/audit/verify")
    def audit_verify(run: str | None = None) -> dict[str, Any]:
        """Recompute the audit hash chain of a run's review store."""
        directory = repository.path(run)
        return audit.verify(directory)

    @app.get("/api/version")
    def version() -> dict[str, Any]:
        return {"code_version": CODE_VERSION or "not set (MOSPI_CODE_VERSION)"}

    @app.get("/api/integrity")
    def integrity(run: str | None = None) -> dict[str, Any]:
        directory = repository.path(run)
        folder = source_dir(directory, "integrity")
        if folder is None or not (folder / "integrity_report.json").is_file():
            return {"available": False}
        return {"available": True, **json.loads((folder / "integrity_report.json").read_text(encoding="utf-8"))}

    @app.get("/api/evaluation")
    def evaluation() -> dict[str, Any]:
        folder = root / "evaluation" / "results"
        results = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))} if folder.is_dir() else {}
        # Current method: pre-registered protocol (docs/evaluation/PROTOCOL.md).  Seeds 1-5 on fold A are development
        # runs; seeds 6-20 on fold B are confirmation runs.  A short summary per run; the full JSON stays on disk.
        protocol = []
        for path in sorted((folder / "protocol_v1").glob("*.json")) if (folder / "protocol_v1").is_dir() else []:
            report = json.loads(path.read_text(encoding="utf-8"))
            designs = report.get("designs_capi_pass", {})
            protocol.append({"run": path.stem, "release": report.get("release"), "fold": report.get("fold"), "seed": report.get("seed"),
                             "kind": "confirmation" if report.get("fold") == "B" and int(report.get("seed", 0)) >= 6 else "development",
                             "capi_pass_records": report.get("capi_pass_records"), "code_version": report.get("code_version"),
                             "recall_at_1pct": {name: (m.get("at_0.01") or {}).get("recall") for name, m in designs.items()},
                             "precision_at_1pct": {name: (m.get("at_0.01") or {}).get("precision") for name, m in designs.items()},
                             "paired_differences": report.get("paired_comparisons_recall_at_1pct"), "group_level": report.get("group_level"),
                             "rule_list": report.get("rule_list")})
        return {"available": bool(results), "results": results, "protocol_v1": protocol}

    # ---------------------------------------------------------------- batch validation (W8.7)

    @app.get("/api/batch/inputs")
    def batch_inputs(request: Request) -> dict[str, Any]:
        user = getattr(request.state, "user", None)
        if jobs is None:
            return {"inputs": [], "stages": [], "can_start": False, "review_only": True, "reason": REVIEW_ONLY_REASON,
                    "upload": {"available": False, "reason": REVIEW_ONLY_REASON}}
        return {"inputs": jobs.inputs(), "stages": ["peer", "statistical", "contextual", "ml", "pattern", "historical", "integrity", "fusion"],
                "can_start": auth is None or can(user, "run"),
                "upload": {"available": False, "reason": "Survey files are prepared on the server (python -m mospi.pipeline.stages.preprocessing.cli ...), which checks the "
                                                         "release layout, before they can be validated here. Uploading raw files from the browser is not offered."}}

    @app.get("/api/batch")
    def batch_jobs() -> dict[str, Any]:
        if jobs is None:
            return {"jobs": [], "review_only": True, "reason": REVIEW_ONLY_REASON}
        return {"jobs": [{k: v for k, v in job.items() if k not in ("inputs", "traceback", "log_tail", "roots", "log")} for job in jobs.list()]}

    @app.get("/api/batch/{job_id}")
    def batch_job(job_id: str) -> dict[str, Any]:
        if jobs is None:
            raise HTTPException(404, REVIEW_ONLY_REASON)
        try:
            job = jobs.get(job_id)
        except JobError as error:
            raise HTTPException(error.status, str(error)) from error
        return {k: v for k, v in job.items() if k not in ("roots", "log", "inputs")}

    @app.post("/api/batch")
    def start_batch(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        if jobs is None:   # also refused by the middleware; kept here so the route itself never starts one
            raise HTTPException(403, REVIEW_ONLY_REASON)
        user = getattr(request.state, "user", None)
        rerun = payload.get("rerun") or []
        if not isinstance(rerun, list) or len(rerun) > 8:
            raise HTTPException(422, "rerun must be a list of stage names.")
        actor = user["name"] if user else str(payload.get("actor") or "")[:120]
        try:
            job = jobs.start(str(payload.get("release") or ""), str(payload.get("label") or ""), actor=actor, actor_verified=user is not None,
                             reuse_label=str(payload.get("reuse_label") or "") or None, rerun=[str(x) for x in rerun])
        except JobError as error:
            raise HTTPException(error.status, str(error)) from error
        return {k: v for k, v in job.items() if k not in ("roots", "log", "inputs")}

    @app.post("/api/validate/record")
    def validate_record(payload: dict[str, Any], run: str | None = None) -> dict[str, Any]:
        """Online check of one submitted record (e.g. from CAPI/eSigma) against documented rules and stored comparison groups.

        Nothing is stored.  ``record`` uses concept names: cws_status, age,
        earnings_salaried, earnings_self_employed, day7_hours, state, sector,
        occupation_code, education, industry_code.
        """
        from mospi.pipeline.stages.integrity.engine import evaluate as evaluate_rules, load_rules
        directory = repository.path(run)
        submitted = payload.get("record", {})
        if not isinstance(submitted, dict) or len(submitted) > 50 or any(len(str(k)) > 64 or len(str(v)) > 100 for k, v in submitted.items()):
            raise HTTPException(422, "A record must be an object with at most 50 fields of at most 100 characters.")
        record = {str(k): ("" if v is None else str(v)) for k, v in submitted.items()}
        frame = pd.DataFrame([{**record, "source_observation_id": "submitted", "record_key": "submitted", "person_serial": "1"}])
        violations = evaluate_rules(frame, load_rules()).drop(columns=["source_observation_id"]).to_dict(orient="records")
        comparisons = _online_comparisons(source_dir(directory, "statistical"), record)
        return {"reference_run": directory.name, "rule_violations": violations, "comparisons": comparisons,
                "note": "Online screening against stored reference distributions; the record is not stored and no decision is implied."}

    @app.get("/api/export/queue")
    def export_queue(run: str | None = None, q: str | None = None, priority_band: str | None = None, state: str | None = None,
                     sector: str | None = None, stratum: str | None = None, fsu: str | None = None, release: str | None = None,
                     visit: str | None = None, month: str | None = None, evidence_source: str | None = None,
                     review_status: str | None = None, strong_source: str | None = None, tier: str | None = None, lane: str | None = None,
                     case_level: str | None = None, district: str | None = None, request: Request = None) -> StreamingResponse:
        """Stream the complete filtered list as CSV (no truncation), in priority order.  Logged in the audit trail."""
        if not exports:   # every export is logged; it is offered only where the audit store takes that entry
            raise HTTPException(503, AUDIT_READ_ONLY_REASON if audit_read_only and not hosted else EXPORT_REASON)
        directory = repository.path(run)
        user = getattr(request.state, "user", None) if request is not None else None
        if auth is not None and not can(user, "export"):
            raise HTTPException(403, "Your role cannot export case lists.")
        filters = queue_filters(priority_band=priority_band, state=state, sector=sector, stratum=stratum, fsu=fsu, release=release,
                                visit=visit, month=month, evidence_source=evidence_source, review_status=review_status, strong_source=strong_source,
                                tier=tier, lane=lane, case_level=case_level, district=district)
        audit.append(directory, case_id="*", event_type="EXPORT", actor=user["name"] if user else "local-user",
                     comment=json.dumps({"filters": filters, "query": q}, sort_keys=True), actor_authenticated=user is not None,
                     actor_role=user["role"] if user else None)
        where, values = repository.where(directory, query=q, filters=filters)
        parquet = directory / "fused_cases.parquet"
        columns = _select(parquet, CASE_FIELDS)
        statuses = audit.latest_statuses(directory)

        def rows() -> Iterator[str]:
            with duckdb.connect() as connection:
                cursor = connection.execute(f"SELECT {columns} FROM read_parquet(?){where} ORDER BY priority_score DESC NULLS LAST, source_observation_id",
                                            [str(parquet), *values])
                names = [d[0] for d in cursor.description]
                buffer = io.StringIO(); writer = csv.writer(buffer)
                writer.writerow(["position", *names, "review_status"]); yield buffer.getvalue()
                position = 0
                while True:
                    chunk = cursor.fetchmany(20_000)
                    if not chunk:
                        break
                    buffer = io.StringIO(); writer = csv.writer(buffer)
                    for record in chunk:
                        position += 1
                        case_id = record[names.index("case_id")]
                        writer.writerow([position, *record, statuses.get(case_id, "UNREVIEWED")])
                    yield buffer.getvalue()

        return StreamingResponse(rows(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=mospi-review-queue.csv"})

    # ---------------------------------------------------------------- upload & validate, jobs, checks, alerts (PostgreSQL)

    from .operations_api import register as register_operations
    register_operations(app, operations=operations, signed_in=auth is not None, review_only=review_only)

    @app.get("/healthz", include_in_schema=False)
    def health() -> JSONResponse:
        """Readiness without authentication: reports only whether data and the audit store are usable, never paths or records."""
        if health_check is not None:
            body, status_code = health_check()
            return JSONResponse({**body, "code_version": CODE_VERSION or "not set (MOSPI_CODE_VERSION)", "review_only": review_only}, status_code=status_code)
        try:
            available = repository.runs()
        except (OSError, ValueError):
            available = []
        if not available:
            return JSONResponse({"status": "unavailable", "runs": 0, "detail": "No Fusion run found in the data directory."}, status_code=503)
        directory = repository.root / available[0]["directory"]
        metadata = repository.metadata(directory)
        sources = {module: source_dir(directory, module) is not None for module in metadata.get("source_runs", {})}
        # The preparation run is referenced by its own key in Fusion metadata.
        sources["preprocessing"] = resolver.run_dir("preprocessing", str(metadata["release"]), str(metadata["observation"]), metadata.get("input_preprocessing_run_id")) is not None
        if audit.backend == "postgres":
            try:
                database = operations.database_status() if operations is not None else {"reachable": True}
            except DatabaseUnavailable:
                database = {"reachable": False}
            audit_writable = not audit_read_only and bool(database.get("reachable"))
        else:
            audit_writable = not audit_read_only and os.access(directory, os.W_OK)
        status = "ok" if all(sources.values()) and (audit_writable or audit_read_only) else "degraded"
        return JSONResponse({"status": status, "code_version": CODE_VERSION or "not set (MOSPI_CODE_VERSION)", "fusion_version": metadata.get("fusion_version"),
                             "runs": len(available), "default_run": available[0]["directory"], "source_runs_found": sources,
                             "audit_store_writable": audit_writable, "audit_store": "read-only" if audit_read_only else ("postgres" if audit.backend == "postgres" else "local file"),
                             "audit_backend": audit.backend,
                             "review_only": review_only, "evaluation_results": (root / "evaluation" / "results").is_dir()},
                            status_code=200 if status == "ok" else 503)

    static = Path(__file__).parent / "ui"
    app.mount("/assets", StaticFiles(directory=static), name="assets")

    @app.get("/{path:path}", response_class=HTMLResponse)
    def workspace(path: str = "") -> str:
        return (static / "index.html").read_text(encoding="utf-8")

    return app


def _aggregate_alert_count(hist: Path | None) -> int | None:
    if hist is None or not (hist / "aggregate_indicators.parquet").is_file():
        return None
    with duckdb.connect() as connection:
        return int(connection.execute("SELECT COUNT(*) FROM read_parquet(?) WHERE notable_change", [str(hist / "aggregate_indicators.parquet")]).fetchone()[0])


def _online_comparisons(stat_dir: Path | None, record: dict[str, str]) -> list[dict[str, Any]]:
    """Position of submitted values within the stored comparison group (most detailed group with >= 30 records)."""
    if stat_dir is None or not (stat_dir / "statistical_evidence.parquet").is_file():
        return []
    from mospi.survey_rules import APPLICABLE, applicability
    occupation = record.get("occupation_code", "")
    industry = record.get("industry_code", "")
    base = {"state": record.get("state", "").zfill(2) if record.get("state") else "", "sector": record.get("sector", ""), "cws_status": record.get("cws_status", "")}
    detail = {"occupation_major_group": occupation[:1] if len(occupation) == 3 and occupation.isdigit() else "", "education": record.get("education", ""),
              "industry_division": industry[:2] if industry.isdigit() and len(industry) in (4, 5) else ""}
    plans = {"cws_earnings_salaried": ("earnings_salaried", [["occupation_major_group", "education"], ["occupation_major_group"], []]),
             "cws_earnings_self_employed": ("earnings_self_employed", [["occupation_major_group", "education"], ["occupation_major_group"], []]),
             "day7_total_hours": ("day7_hours", [["industry_division"], []])}
    path = stat_dir / "statistical_evidence.parquet"
    output = []
    for target, (concept, levels) in plans.items():
        raw = record.get(concept, "")
        try:
            value = float(raw)
        except ValueError:
            continue
        if applicability(target, base["cws_status"]) != APPLICABLE:
            output.append({"target": target, "status": "NOT_APPLICABLE_FOR_CWS_STATUS"})
            continue
        for extra in levels:
            keys = {**base, **{k: detail[k] for k in extra}}
            if any(not v for v in keys.values()):
                continue
            clause = " AND ".join(f"json_extract_string(grouping_values, '$.{k}') = ?" for k in keys)
            with duckdb.connect() as connection:
                values = [r[0] for r in connection.execute(
                    # Every member of a valid comparison cell carries these keys in its stored
                    # grouping values (members of a coarser cell were assigned at that or a finer level).
                    f"SELECT observed_value FROM read_parquet(?) WHERE target_variable = ? AND statistical_assessability_status = 'ASSESSABLE' AND {clause}",
                    [str(path), target, *keys.values()]).fetchall()]
            if len(values) < 30:
                continue
            import numpy as np
            reference = np.sort(np.asarray(values, dtype=float))
            below = np.searchsorted(reference, value, "left"); equal = np.searchsorted(reference, value, "right") - below
            q05, q25, q50, q75, q95 = np.quantile(reference, [.05, .25, .5, .75, .95])
            output.append({"target": target, "status": "ASSESSED", "comparison_group": keys, "comparison_size": len(reference),
                           "percentile": float((below + .5 * equal) / len(reference)), "median": float(q50), "q05": float(q05), "q25": float(q25),
                           "q75": float(q75), "q95": float(q95), "position": "UPPER_TAIL" if value > q95 else "LOWER_TAIL" if value < q05 else "CENTRAL_REFERENCE_RANGE"})
            break
        else:
            output.append({"target": target, "status": "NO_STORED_COMPARISON_GROUP_WITH_30_RECORDS"})
    return output


def _position_of(repository: FusionRepository, directory: Path, case_id: str) -> int | None:
    """1-based position of a case in the unfiltered priority order."""
    rows = repository.query(directory / "fused_cases.parquet",
                            "SELECT position FROM (SELECT case_id, ROW_NUMBER() OVER (ORDER BY priority_score DESC NULLS LAST, source_observation_id) AS position FROM read_parquet(?)) WHERE case_id = ?", [case_id])
    return rows[0]["position"] if rows else None
