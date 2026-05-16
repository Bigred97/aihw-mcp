"""Tests for the top_n convenience tool.

top_n ranks rows by a measure and returns the top (or bottom) N. It's the
most common agent workflow — "show me the top 10 X by Y" — collapsed into
a single server-side call.
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


async def _fake_fetch(self, url, *, kind="data"):
    for tag, path in FIXTURE_MAP.items():
        if tag in url:
            return path.read_bytes()
    raise RuntimeError(f"no fixture for {url}")


@pytest.fixture(autouse=True)
async def reset_caches():
    server.reset_df_cache_for_tests()
    await server.reset_client_for_tests()
    yield
    server.reset_df_cache_for_tests()
    await server.reset_client_for_tests()


@pytest.fixture
def mocked_client():
    with patch.object(AIHWClient, "fetch_resource", _fake_fetch):
        yield


@pytest.mark.asyncio
async def test_top_n_default_top_5(mocked_client):
    """Top 5 causes of death by absolute deaths (all years pooled)."""
    r = await server.top_n("GRIM_DEATHS", "deaths", n=5,
                            filters={"sex": "persons"})
    assert r.row_count == 5
    values = [rec.value for rec in r.records]
    assert values == sorted(values, reverse=True)


@pytest.mark.asyncio
async def test_top_n_bottom_direction(mocked_client):
    r = await server.top_n("GRIM_DEATHS", "deaths", n=5,
                            filters={"sex": "persons"}, direction="bottom")
    assert r.row_count == 5
    values = [rec.value for rec in r.records]
    assert values == sorted(values)


@pytest.mark.asyncio
async def test_top_n_with_filter(mocked_client):
    """MORT geography: top 10 by deaths in NSW state category."""
    r = await server.top_n(
        "MORT_GEOGRAPHY", "deaths", n=10,
        filters={"category": "state", "sex": "Persons"},
    )
    assert r.row_count <= 10
    assert all(rec.dimensions.get("category") == "State and territory" for rec in r.records)
    values = [rec.value for rec in r.records]
    assert values == sorted(values, reverse=True)


@pytest.mark.asyncio
async def test_top_n_caps_at_available_rows(mocked_client):
    """If the filter yields fewer than n rows, return what's available."""
    r = await server.top_n(
        "HEALTH_EXPENDITURE", "real_expenditure_millions",
        n=10_000, filters={"state": "act"},
    )
    assert 1 <= r.row_count < 10_000


@pytest.mark.asyncio
async def test_top_n_skips_null_values(mocked_client):
    """Some rows may have null measure values. They must not appear in rankings."""
    r = await server.top_n("GRIM_DEATHS", "age_standardised_rate_per_100000",
                            n=10, filters={"sex": "persons"})
    assert all(rec.value is not None for rec in r.records)


@pytest.mark.asyncio
async def test_top_n_envelope_preserved(mocked_client):
    """The DataResponse envelope must come through unchanged."""
    r = await server.top_n("GRIM_DEATHS", "deaths", n=3,
                            filters={"sex": "persons"})
    assert r.unit == "Deaths"
    assert r.source == "Australian Institute of Health and Welfare"
    assert "Creative Commons" in r.attribution
    assert r.aihw_url.startswith("https://data.gov.au/")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_top_n_unknown_dataset_raises():
    with pytest.raises(ValueError, match="not a curated"):
        await server.top_n("DOES_NOT_EXIST", "x", n=5)


@pytest.mark.asyncio
async def test_top_n_rejects_non_string_measure():
    with pytest.raises(ValueError, match="measure is required"):
        await server.top_n("GRIM_DEATHS", "", n=5)


@pytest.mark.asyncio
async def test_top_n_rejects_bad_direction():
    with pytest.raises(ValueError, match="direction must be"):
        await server.top_n("GRIM_DEATHS", "deaths", n=5,
                            direction="sideways")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_top_n_rejects_n_zero():
    with pytest.raises(ValueError, match=">= 1"):
        await server.top_n("GRIM_DEATHS", "deaths", n=0)


@pytest.mark.asyncio
async def test_top_n_rejects_n_bool():
    with pytest.raises(ValueError, match="positive integer"):
        await server.top_n("GRIM_DEATHS", "deaths", n=True)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_top_n_rejects_unknown_measure(mocked_client):
    """Unknown measure name → ValueError listing valid measures."""
    with pytest.raises(ValueError, match="Unknown measure"):
        await server.top_n("GRIM_DEATHS", "not_a_measure", n=5)


@pytest.mark.asyncio
async def test_top_n_caches_across_queries(mocked_client):
    """Two top_n calls on the same dataset → only 1 parse via the df cache."""
    import aihw_mcp.server as srv
    original_read_csv = srv.read_csv
    parse_count = {"calls": 0}

    def counted(*args, **kwargs):
        parse_count["calls"] += 1
        return original_read_csv(*args, **kwargs)

    with patch.object(srv, "read_csv", counted):
        await server.top_n("GRIM_DEATHS", "deaths", n=5, filters={"sex": "persons"})
        await server.top_n("GRIM_DEATHS", "deaths", n=10, filters={"sex": "persons"})
        await server.top_n("GRIM_DEATHS", "deaths", n=20,
                            filters={"sex": "persons"}, direction="bottom")
    assert parse_count["calls"] == 1, (
        f"expected 1 parse for 3 top_n calls, got {parse_count['calls']}"
    )
