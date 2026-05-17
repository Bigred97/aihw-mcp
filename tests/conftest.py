"""Shared pytest fixtures.

Test fixtures load small AIHW CSV samples from `tests/fixtures/` (a few hundred
rows each, trimmed from the live data.gov.au CSVs). The unit suite uses these
to exercise parsing/shaping/filtering without touching the network. Full-file
parsing is exercised via the `live` marker tests against data.gov.au.
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


@pytest.fixture(autouse=True)
def isolate_parquet_cache_dir(tmp_path_factory, monkeypatch):
    """Redirect the Parquet on-disk cache to a per-session tmp dir.

    Without this, tests would write to `~/.aihw-mcp/parquet-cache/`
    (the real user dir) and cache hits would leak between test runs
    and across developer machines.
    """
    target = tmp_path_factory.mktemp("aihw_parquet_cache")
    monkeypatch.setenv("AIHW_MCP_PARQUET_CACHE_DIR", str(target))
    yield


@pytest.fixture
def fixture_dir() -> Path:
    return FIXTURE_DIR


@pytest.fixture
def grim_csv() -> bytes:
    """GRIM deaths — 400 rows for All causes / Diabetes / All neoplasms / CHD, Total age band."""
    return (FIXTURE_DIR / "grim_head.csv").read_bytes()


@pytest.fixture
def mort_csv() -> bytes:
    """MORT geography — ~600 rows for YEAR=2023 across all region categories."""
    return (FIXTURE_DIR / "mort_head.csv").read_bytes()


@pytest.fixture
def acim_csv() -> bytes:
    """ACIM cancer — 210 rows covering Breast/Bowel/Lung/Melanoma/Prostate, 2005+."""
    return (FIXTURE_DIR / "acim_head.csv").read_bytes()


@pytest.fixture
def hexp_csv() -> bytes:
    """Health expenditure — 800 rows covering 2009-10..2011-12 financial years."""
    return (FIXTURE_DIR / "hexp_head.csv").read_bytes()


@pytest.fixture
def youthj_csv() -> bytes:
    """Youth justice detention — 500 rows for 2016 and 2017."""
    return (FIXTURE_DIR / "youthj_head.csv").read_bytes()


@pytest.fixture
def pubhosp_csv() -> bytes:
    """Public hospitals — 250 rows (the full register has ~700)."""
    return (FIXTURE_DIR / "pubhosp_head.csv").read_bytes()
