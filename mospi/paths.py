"""Where the platform keeps its data.

The data root holds the stored runs in the layout ``<stage>/runs/<run_id>/`` (plus ``pipeline/``, ``evaluation/`` and
``fusion/`` records); the raw survey deliveries sit under ``<data root>/raw``.  By default it is the ``data`` folder of this
repository; ``MOSPI_DATA_DIR`` points it elsewhere (a bundle made by scripts/export_serving_data.py, or a mounted host folder).
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def data_root() -> Path:
    value = os.environ.get("MOSPI_DATA_DIR", "").strip()
    return Path(value) if value else REPO_ROOT / "data"


def raw_root() -> Path:
    """The supplied survey deliveries (``2023-June2024``, ``Jan-Dec2024``, ``Post2025``): input only, never written."""
    return data_root() / "raw"
