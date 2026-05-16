"""End-to-end tests that hit data.gov.au.

Tagged `live` so they don't run by default. Run with:
    pytest -m live
"""
from __future__ import annotations

import pytest

from aihw_mcp import curated, server


pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
async def reset_state():
    await server.reset_client_for_tests()
    server.reset_df_cache_for_tests()
    yield
    await server.reset_client_for_tests()
    server.reset_df_cache_for_tests()


@pytest.mark.asyncio
async def test_live_grim_search():
    curated.reset_registry()
    results = await server.search_datasets("mortality cause of death")
    assert any(s.id == "GRIM_DEATHS" for s in results), [s.id for s in results]


@pytest.mark.asyncio
async def test_live_grim_diabetes_deaths():
    curated.reset_registry()
    r = await server.get_data(
        "GRIM_DEATHS",
        filters={"cause_of_death": "Diabetes", "sex": "persons", "age_group": "Total"},
        measures="deaths",
    )
    assert r.row_count > 50  # multi-decade time series
    assert r.unit == "Deaths"
    assert r.aihw_url.startswith("https://data.gov.au/")


@pytest.mark.asyncio
async def test_live_mort_state_breakdown():
    curated.reset_registry()
    r = await server.get_data(
        "MORT_GEOGRAPHY",
        filters={"category": "state", "sex": "Persons", "year": "2023"},
        measures="age_standardised_rate_per_100000",
    )
    assert r.row_count >= 8  # 8 states/territories + maybe national total


@pytest.mark.asyncio
async def test_live_top_n_causes_of_death():
    curated.reset_registry()
    r = await server.top_n(
        "GRIM_DEATHS", "deaths", n=5,
        filters={"sex": "Persons", "age_group": "Total", "year": "2023"},
    )
    assert r.row_count == 5
    values = [rec.value for rec in r.records]
    assert values == sorted(values, reverse=True)
    # All causes combined should top the list
    top_cause = r.records[0].dimensions.get("cause_of_death")
    assert "All causes" in top_cause or "all causes" in top_cause.lower()


@pytest.mark.asyncio
async def test_live_pubhospitals_register():
    curated.reset_registry()
    r = await server.get_data(
        "PUBLIC_HOSPITALS",
        filters={"state": "NSW", "peer_group_name": "Principal referral"},
        measures="number_of_available_beds",
    )
    assert r.row_count >= 1
    for rec in r.records:
        assert rec.dimensions["state"] == "NSW"
        assert rec.dimensions["peer_group_name"] == "Principal referral"


@pytest.mark.asyncio
async def test_live_discovery_resolves_real_grim_url():
    """The discovery layer must resolve a real data.gov.au URL for GRIM."""
    import asyncio as _asyncio
    from aihw_mcp.client import AIHWClient
    from aihw_mcp.discovery import DiscoveryError, DiscoverySpec, resolve_latest_url

    async def _retry_resolve(client, spec, retries: int = 1):
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return await resolve_latest_url(client, spec)
            except DiscoveryError as e:
                last_err = e
                if attempt < retries:
                    await _asyncio.sleep(0.5)
        raise last_err  # type: ignore[misc]

    async with AIHWClient() as client:
        url = await _retry_resolve(
            client, DiscoverySpec(package_id="grim-books", resource_name="GRIM"),
        )
        assert url.startswith("https://data.gov.au/")
        assert "grim" in url.lower()
