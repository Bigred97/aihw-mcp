"""Tests for the parsed-DataFrame in-process cache in server.py.

The cache makes warm get_data() calls cheap. We probe:
  - Repeated identical calls don't re-parse (counted via mock)
  - Cache key is content-aware: same URL but different bytes → re-parse
  - LRU eviction keeps memory bounded
  - Tests don't leak state via the autouse reset fixture
"""
from __future__ import annotations

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
async def reset_caches():
    server.reset_df_cache_for_tests()
    await server.reset_client_for_tests()
    yield
    server.reset_df_cache_for_tests()
    await server.reset_client_for_tests()


@pytest.fixture
def mocked_fetch_with_counter():
    counts = {"calls": 0}

    async def fake(self, url, *, kind="data"):
        counts["calls"] += 1
        for tag, path in FIXTURE_MAP.items():
            if tag in url:
                return path.read_bytes()
        raise RuntimeError(f"no fixture for {url}")

    with patch.object(AIHWClient, "fetch_resource", fake):
        yield counts


@pytest.fixture
def mocked_read_csv_with_counter():
    """Patches read_csv (used by 6 of 6 datasets) and counts invocations."""
    import aihw_mcp.server as srv
    counts = {"calls": 0}
    original = srv.read_csv

    def counted(*args, **kwargs):
        counts["calls"] += 1
        return original(*args, **kwargs)

    with patch.object(srv, "read_csv", counted):
        yield counts


@pytest.mark.asyncio
async def test_repeat_query_does_not_reparse(mocked_fetch_with_counter, mocked_read_csv_with_counter):
    """Three identical get_data calls → only 1 PARSE."""
    for _ in range(3):
        r = await server.get_data(
            "GRIM_DEATHS",
            filters={"cause_of_death": "Diabetes", "sex": "persons"},
            measures="deaths",
        )
        assert r.row_count >= 0
    assert mocked_read_csv_with_counter["calls"] == 1, (
        f"expected 1 parse, got {mocked_read_csv_with_counter['calls']}"
    )


@pytest.mark.asyncio
async def test_different_filters_share_parsed_df(
    mocked_fetch_with_counter, mocked_read_csv_with_counter,
):
    """Different filters on the same dataset should share the cached DataFrame."""
    await server.get_data("GRIM_DEATHS",
                          filters={"cause_of_death": "Diabetes", "sex": "persons"}, measures="deaths")
    await server.get_data("GRIM_DEATHS",
                          filters={"cause_of_death": "Diabetes", "sex": "female"}, measures="deaths")
    await server.get_data("GRIM_DEATHS",
                          filters={"cause_of_death": "All causes combined", "sex": "persons"}, measures="deaths")
    assert mocked_read_csv_with_counter["calls"] == 1


@pytest.mark.asyncio
async def test_different_datasets_each_get_parsed(
    mocked_fetch_with_counter, mocked_read_csv_with_counter,
):
    """Each dataset has its own cache slot."""
    await server.get_data("GRIM_DEATHS", filters={"sex": "persons"}, measures="deaths")
    await server.get_data("MORT_GEOGRAPHY", filters={"category": "state"}, measures="deaths")
    await server.get_data("HEALTH_EXPENDITURE", filters={"state": "nsw"}, measures="real_expenditure_millions")
    assert mocked_read_csv_with_counter["calls"] == 3


@pytest.mark.asyncio
async def test_lru_eviction_keeps_bounded(
    mocked_fetch_with_counter, mocked_read_csv_with_counter,
):
    """Caching all 6 datasets and re-querying — second pass hits cache."""
    from aihw_mcp.server import _DF_CACHE_MAX_ENTRIES, _df_cache

    queries = [
        ("GRIM_DEATHS", {"sex": "persons", "cause_of_death": "Diabetes"}, "deaths"),
        ("MORT_GEOGRAPHY", {"category": "state"}, "deaths"),
        ("CANCER_INCIDENCE_MORTALITY",
         {"cancer_type": "Breast cancer", "sex": "female"}, "age_50_to_54"),
        ("HEALTH_EXPENDITURE", {"state": "nsw"}, "real_expenditure_millions"),
        ("YOUTH_JUSTICE_DETENTION", {"state": "nsw"}, "avg_nightly_pop"),
        ("PUBLIC_HOSPITALS", {"state": "NSW"}, "number_of_available_beds"),
    ]
    for ds, filters, measure in queries:
        await server.get_data(ds, filters=filters, measures=measure)
    first_parses = mocked_read_csv_with_counter["calls"]
    assert first_parses == 6

    # Second pass — all cache hits
    for ds, filters, measure in queries:
        await server.get_data(ds, filters=filters, measures=measure)
    assert mocked_read_csv_with_counter["calls"] == first_parses

    assert len(_df_cache) <= _DF_CACHE_MAX_ENTRIES


@pytest.mark.asyncio
async def test_cache_invalidates_on_content_change(mocked_read_csv_with_counter):
    """If the byte cache returns different bytes (e.g. AIHW published a refresh),
    the parsed-df cache must invalidate via the body hash."""
    server.reset_df_cache_for_tests()
    body_v1 = (FIXTURE_DIR / "grim_head.csv").read_bytes()
    body_v2 = body_v1 + b"\n# version bump comment\n"

    bodies = iter([body_v1, body_v2])

    async def serve(self, url, *, kind="data"):
        return next(bodies)

    with patch.object(AIHWClient, "fetch_resource", serve):
        await server.get_data("GRIM_DEATHS",
                              filters={"cause_of_death": "Diabetes", "sex": "persons"},
                              measures="deaths")
        first_parses = mocked_read_csv_with_counter["calls"]
        assert first_parses == 1

        # Different bytes → cache must miss → re-parse.
        try:
            await server.get_data("GRIM_DEATHS",
                                  filters={"cause_of_death": "Diabetes", "sex": "persons"},
                                  measures="deaths")
        except Exception:
            pass  # we don't care if parsing the modified body succeeds
        assert mocked_read_csv_with_counter["calls"] > first_parses
