"""Shared pytest options.

Real-data smoke tests read the stored PLFS runs (not in git) and are opt-in:
    python -m pytest -m realdata --realdata
"""
import pytest


def pytest_addoption(parser):
    parser.addoption("--realdata", action="store_true", default=False, help="run smoke tests against the stored PLFS runs")


def pytest_configure(config):
    config.addinivalue_line("markers", "realdata: smoke test against stored PLFS runs (opt-in with --realdata)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--realdata"):
        return
    skip = pytest.mark.skip(reason="real-data smoke test; run with --realdata")
    for item in items:
        if "realdata" in item.keywords:
            item.add_marker(skip)
