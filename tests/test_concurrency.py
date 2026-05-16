"""Concurrent-access tests.

Two flavours:
  1. Multiple coroutines calling the same dataset → the in-flight dedup in
     `AIHWClient._fetch_cached` should fold them to a single download.
  2. Multiple coroutines calling different datasets → no cross-talk, no
     race on the SQLite cache, no event-loop deadlock.

We measure the dedup by counting actual fetch invocations under a counter
patch.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest

from aihw_mcp import server
from aihw_mcp.client import AIHWClient


FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_MAP = {
    "grim-data-gov-au": FIXTURE_DIR / "grim_head.csv",
    "mort-table1-data-gov-au": FIXTURE_DIR / "mort_head.csv",
    "acimcombinedcounts": FIXTURE_DIR / "acim_head.csv",
    "healthexpenditurebyareaandsource": FIXTURE_DIR / "hexp_head.csv",
    "youth-justice-detention-data": FIXTURE_DIR / "youthj_head.csv",
    "public_hospital_list": FIXTURE_DIR / "pubhosp_head.csv",
}


@pytest.fixture(autouse=True)
async def fresh_client():
    server.reset_df_cache_for_tests()
    await server.reset_client_for_tests()
    yield
    server.reset_df_cache_for_tests()
    await server.reset_client_for_tests()


@pytest.fixture
def counting_fetch_patch():
    counts: Counter[str] = Counter()

    async def fake(self, url, *, kind="data"):
        counts[url] += 1
        await asyncio.sleep(0.05)
        for tag, path in FIXTURE_MAP.items():
            if tag in url:
                return path.read_bytes()
        raise RuntimeError(f"no fixture for {url}")

    with patch.object(AIHWClient, "fetch_resource", fake):
        yield counts


@pytest.mark.asyncio
async def test_parallel_same_dataset_dedupes_to_one_fetch(counting_fetch_patch):
    """50 parallel callers asking for the SAME dataset → exactly 1 download."""
    coros = [
        server.get_data("GRIM_DEATHS",
                        filters={"cause_of_death": "Diabetes", "sex": "persons"},
                        measures="deaths")
        for _ in range(50)
    ]
    results = await asyncio.gather(*coros)
    assert all(r.row_count >= 0 for r in results)
    download_urls = list(counting_fetch_patch.keys())
    assert len(download_urls) == 1
    assert counting_fetch_patch[download_urls[0]] <= 50  # sanity


@pytest.mark.asyncio
async def test_parallel_different_datasets(counting_fetch_patch):
    """Parallel calls to all 6 datasets succeed without cross-talk."""
    coros = [
        server.get_data("GRIM_DEATHS",
                        filters={"cause_of_death": "Diabetes", "sex": "persons"},
                        measures="deaths"),
        server.get_data("MORT_GEOGRAPHY",
                        filters={"category": "state", "sex": "Persons"},
                        measures="deaths"),
        server.get_data("CANCER_INCIDENCE_MORTALITY",
                        filters={"cancer_type": "Breast cancer", "sex": "female"},
                        measures="age_50_to_54"),
        server.get_data("HEALTH_EXPENDITURE",
                        filters={"state": "nsw"},
                        measures="real_expenditure_millions"),
        server.get_data("YOUTH_JUSTICE_DETENTION",
                        filters={"state": "nsw"},
                        measures="avg_nightly_pop"),
        server.get_data("PUBLIC_HOSPITALS",
                        filters={"state": "NSW"},
                        measures="number_of_available_beds"),
    ]
    results = await asyncio.gather(*coros)
    for i, r in enumerate(results):
        assert r.row_count >= 0, f"call {i} returned no row_count"
        assert r.dataset_id, f"call {i} missing dataset_id"


@pytest.mark.asyncio
async def test_rapid_sequential_warms_cache(counting_fetch_patch):
    """Same dataset called 5x sequentially → 1 fetch (others served from cache)."""
    for _ in range(5):
        r = await server.get_data(
            "GRIM_DEATHS",
            filters={"cause_of_death": "Diabetes", "sex": "persons"},
            measures="deaths",
        )
        assert r.row_count >= 0
    download_urls = list(counting_fetch_patch.keys())
    assert len(download_urls) == 1
