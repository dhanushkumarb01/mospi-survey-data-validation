"""Shared pytest options.

Real-data smoke tests read the stored PLFS runs (not in git) and are opt-in:
    python -m pytest -m realdata --realdata

PostgreSQL tests are opt-in too and never touch the operational schema: each test gets a throwaway schema in the
database named by MOSPI_DB_ADMIN_URL (from the environment or the local, git-ignored .env), dropped afterwards:
    python -m pytest --postgres
"""
import os

import pytest

# The suite never picks up a developer's local .env implicitly (it would switch the audit backend under the tests).
os.environ["MOSPI_NO_ENV_FILE"] = "1"


def pytest_addoption(parser):
    parser.addoption("--realdata", action="store_true", default=False, help="run smoke tests against the stored PLFS runs")
    parser.addoption("--postgres", action="store_true", default=False, help="run tests against PostgreSQL (throwaway schemas)")


def pytest_configure(config):
    config.addinivalue_line("markers", "realdata: smoke test against stored PLFS runs (opt-in with --realdata)")
    config.addinivalue_line("markers", "postgres: needs PostgreSQL (opt-in with --postgres)")


def pytest_collection_modifyitems(config, items):
    for option, marker in (("--realdata", "realdata"), ("--postgres", "postgres")):
        if config.getoption(option):
            continue
        skip = pytest.mark.skip(reason=f"{marker} test; run with {option}")
        for item in items:
            if marker in item.keywords:
                item.add_marker(skip)
