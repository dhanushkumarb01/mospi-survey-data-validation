"""Configuration of uploads, the worker and the scheduler (environment variables; safe defaults)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from mospi.db.config import int_setting
from mospi.paths import data_root

# Only first-visit contracts that the batch pipeline has a release preset for can be validated end to end
# (mospi.pipeline.run.PRESETS); revisit files are inputs of their first-visit release, not standalone deliveries.
UPLOADABLE_CONTRACTS = ("2023_24_first", "2024_first", "2025_first")
LABEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{0,23}$")


@dataclass(frozen=True)
class Settings:
    upload_root: Path
    max_file_bytes: int
    max_files: int
    max_columns: int
    small_delivery_persons: int
    check_interval_minutes: int
    full_rerun_days: int
    rerun_on_change: bool
    stale_seconds: int
    poll_seconds: int
    full_hash_checks: bool
    mapping_profile_dir: Path

    @property
    def uploads_enabled(self) -> bool:
        return os.environ.get("MOSPI_UPLOADS_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def settings() -> Settings:
    upload = os.environ.get("MOSPI_UPLOAD_DIR", "").strip()
    profiles = os.environ.get("MOSPI_MAPPING_PROFILE_DIR", "").strip()
    return Settings(
        upload_root=Path(upload) if upload else data_root() / "uploads",
        max_file_bytes=int_setting("MOSPI_UPLOAD_MAX_FILE_MB", 2048) * 1024 * 1024,
        max_files=int_setting("MOSPI_UPLOAD_MAX_FILES", 4),
        max_columns=int_setting("MOSPI_UPLOAD_MAX_COLUMNS", 1000),
        small_delivery_persons=int_setting("MOSPI_SMALL_DELIVERY_PERSONS", 1000),
        check_interval_minutes=int_setting("MOSPI_CHECK_INTERVAL_MINUTES", 360),
        full_rerun_days=int_setting("MOSPI_FULL_RERUN_DAYS", 0),
        rerun_on_change=os.environ.get("MOSPI_RERUN_ON_CHANGE", "").strip().lower() in {"1", "true", "yes", "on"},
        stale_seconds=int_setting("MOSPI_JOB_STALE_SECONDS", 180),
        poll_seconds=int_setting("MOSPI_WORKER_POLL_SECONDS", 5),
        full_hash_checks=os.environ.get("MOSPI_CHECK_FULL_HASH", "").strip().lower() in {"1", "true", "yes", "on"},
        mapping_profile_dir=Path(profiles) if profiles else Path(__file__).with_name("profiles"),
    )


def sanitise(message: object, limit: int = 500) -> str:
    """An error message fit for the ledger and alerts: no absolute paths, no connection strings, bounded length."""
    from mospi.db.connection import redact
    text = redact(str(message))
    text = re.sub(r"[A-Za-z]:\\[^\s'\"]+|(?<![\w.])/(?:[\w.-]+/)+[\w.-]+", "<path>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]
