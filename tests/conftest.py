"""Shared pytest fixtures.

Test fixtures load real AIHW sample files from `tests/fixtures/`. Fixtures
are intentionally small (a few hundred rows each, not the full multi-MB
files) so the unit suite stays fast. Full-file parsing is exercised via
the `live` marker tests against data.gov.au.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from aihw_mcp import curated


FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def reset_curated_registry():
    """Force a fresh load of curated YAMLs before each test."""
    curated.reset_registry()
    yield
    curated.reset_registry()


@pytest.fixture
def fixture_dir() -> Path:
    return FIXTURE_DIR
