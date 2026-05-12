"""Discovery module tests.

Discovery is the auto-update path: it resolves a fresh CKAN URL at fetch
time so when AIHW publishes a refreshed file, the curated YAML doesn't
need a code change. The contract is strict:

  - On success: return the freshest matching URL.
  - On any failure (network, malformed CKAN, no match, off-host URL):
    raise DiscoveryError. Callers MUST fall back to the YAML default.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from aihw_mcp.cache import Cache
from aihw_mcp.client import AIHWAPIError, AIHWClient
from aihw_mcp.discovery import (
    DiscoveryError,
    DiscoverySpec,
    _is_data_gov_au,
    _pick_resource,
    _year_from_text,
    resolve_latest_url,
)


@pytest.fixture
def fresh_cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "cache.db")


# ---------------------------------------------------------------------------
# Helper unit tests (no network)
# ---------------------------------------------------------------------------

def test_year_from_text_extracts_highest():
    assert _year_from_text("Taxation Statistics 2022-23") == 2022
    assert _year_from_text("2023-24 Report") == 2023
    assert _year_from_text("Released 2019, covers 2024 data") == 2024
    assert _year_from_text("no year here") is None
    assert _year_from_text("") is None
    assert _year_from_text(None) is None  # type: ignore[arg-type]


def test_pick_resource_exact_name_match():
    resources = [
        {"name": "GRIM_OLD", "url": "https://data.gov.au/data/a/file.csv"},
        {"name": "GRIM",     "url": "https://data.gov.au/data/a/grim.csv"},
        {"name": "MORT_TABLE_1", "url": "https://data.gov.au/data/a/mort.csv"},
    ]
    spec = DiscoverySpec(package_id="x", resource_name="GRIM")
    m = _pick_resource(resources, spec)
    assert m is not None
    assert m["url"] == "https://data.gov.au/data/a/grim.csv"


def test_pick_resource_pattern_picks_highest_year():
    resources = [
        {"name": "Hospital list 2014-15", "url": "https://data.gov.au/data/a/2014.csv"},
        {"name": "Hospital list 2016-17", "url": "https://data.gov.au/data/a/2016.csv"},
        {"name": "Hospital list 2015-16", "url": "https://data.gov.au/data/a/2015.csv"},
    ]
    spec = DiscoverySpec(package_id="x", resource_name_pattern=r"Hospital list")
    m = _pick_resource(resources, spec)
    assert m is not None
    assert m["url"] == "https://data.gov.au/data/a/2016.csv"


def test_pick_resource_no_match_returns_none():
    resources = [{"name": "Other Resource", "url": "https://data.gov.au/data/a/other.csv"}]
    spec = DiscoverySpec(package_id="x", resource_name="Missing One")
    assert _pick_resource(resources, spec) is None


def test_pick_resource_skips_non_dict_entries():
    resources = [
        "not a dict",  # type: ignore[list-item]
        None,
        {"name": "Right One", "url": "https://data.gov.au/data/a/file.csv"},
    ]
    spec = DiscoverySpec(package_id="x", resource_name="Right One")
    m = _pick_resource(resources, spec)
    assert m is not None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_requires_package_id_or_pattern(fresh_cache: Cache):
    async with AIHWClient(cache=fresh_cache) as client:
        with pytest.raises(DiscoveryError, match="package_id"):
            await resolve_latest_url(client, DiscoverySpec(resource_name="x"))


@pytest.mark.asyncio
async def test_resolve_requires_resource_name_or_pattern(fresh_cache: Cache):
    async with AIHWClient(cache=fresh_cache) as client:
        with pytest.raises(DiscoveryError, match="resource_name"):
            await resolve_latest_url(client, DiscoverySpec(package_id="x"))


@pytest.mark.asyncio
async def test_resolve_package_pattern_requires_org_id(fresh_cache: Cache):
    async with AIHWClient(cache=fresh_cache) as client:
        with pytest.raises(DiscoveryError, match="organization_id"):
            await resolve_latest_url(
                client,
                DiscoverySpec(
                    package_id_pattern=r"^foo-(\d{4})$",
                    resource_name="x",
                ),
            )


# ---------------------------------------------------------------------------
# Happy paths via respx
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_resolve_with_exact_package_id_and_name(fresh_cache: Cache):
    respx.get(
        url__startswith="https://data.gov.au/data/api/3/action/package_show",
    ).mock(
        return_value=httpx.Response(200, json={
            "success": True,
            "result": {
                "name": "grim-books",
                "resources": [
                    {"name": "GRIM_OLD", "url": "https://data.gov.au/data/x/old.csv"},
                    {"name": "GRIM",     "url": "https://data.gov.au/data/x/grim.csv"},
                ],
            },
        })
    )
    async with AIHWClient(cache=fresh_cache) as client:
        url = await resolve_latest_url(
            client, DiscoverySpec(package_id="grim-books", resource_name="GRIM"),
        )
    assert url == "https://data.gov.au/data/x/grim.csv"


@pytest.mark.asyncio
@respx.mock
async def test_resolve_with_package_pattern_picks_latest_year(fresh_cache: Cache):
    respx.get(
        url__startswith="https://data.gov.au/data/api/3/action/package_search",
    ).mock(
        return_value=httpx.Response(200, json={
            "success": True,
            "result": {
                "results": [
                    {"name": "aihw-report-2020-21"},
                    {"name": "aihw-report-2022-23"},
                    {"name": "aihw-report-2021-22"},
                    {"name": "unrelated-dataset"},
                ],
            },
        })
    )
    respx.get(
        url__startswith="https://data.gov.au/data/api/3/action/package_show",
    ).mock(
        return_value=httpx.Response(200, json={
            "success": True,
            "result": {
                "name": "aihw-report-2022-23",
                "resources": [
                    {"name": "Data", "url": "https://data.gov.au/data/x/latest.csv"},
                ],
            },
        })
    )
    async with AIHWClient(cache=fresh_cache) as client:
        url = await resolve_latest_url(
            client,
            DiscoverySpec(
                organization_id="aihw",
                package_id_pattern=r"^aihw-report-(\d{4})-\d{2}$",
                resource_name="Data",
            ),
        )
    assert url == "https://data.gov.au/data/x/latest.csv"


# ---------------------------------------------------------------------------
# Failure paths — every one MUST raise DiscoveryError.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_resolve_404_raises_discovery_error(fresh_cache: Cache):
    respx.get(
        url__startswith="https://data.gov.au/data/api/3/action/package_show",
    ).mock(return_value=httpx.Response(404))
    async with AIHWClient(cache=fresh_cache) as client:
        with pytest.raises(DiscoveryError):
            await resolve_latest_url(
                client, DiscoverySpec(package_id="missing-pkg", resource_name="anything"),
            )


@pytest.mark.asyncio
@respx.mock
async def test_resolve_no_matching_resource_raises(fresh_cache: Cache):
    respx.get(
        url__startswith="https://data.gov.au/data/api/3/action/package_show",
    ).mock(
        return_value=httpx.Response(200, json={
            "success": True,
            "result": {
                "name": "grim-books",
                "resources": [{"name": "Other Resource", "url": "https://data.gov.au/x/other.csv"}],
            },
        })
    )
    async with AIHWClient(cache=fresh_cache) as client:
        with pytest.raises(DiscoveryError, match="no resource matched"):
            await resolve_latest_url(
                client, DiscoverySpec(package_id="grim-books", resource_name="Missing"),
            )


@pytest.mark.asyncio
@respx.mock
async def test_resolve_no_matching_package_pattern_raises(fresh_cache: Cache):
    respx.get(
        url__startswith="https://data.gov.au/data/api/3/action/package_search",
    ).mock(
        return_value=httpx.Response(200, json={
            "success": True,
            "result": {"results": [{"name": "other-org-dataset"}]},
        })
    )
    async with AIHWClient(cache=fresh_cache) as client:
        with pytest.raises(DiscoveryError, match="no package matched"):
            await resolve_latest_url(
                client,
                DiscoverySpec(
                    organization_id="aihw",
                    package_id_pattern=r"^aihw-(\d{4})-\d{2}$",
                    resource_name="Anything",
                ),
            )


@pytest.mark.asyncio
@respx.mock
async def test_resolve_malformed_url_raises(fresh_cache: Cache):
    respx.get(
        url__startswith="https://data.gov.au/data/api/3/action/package_show",
    ).mock(
        return_value=httpx.Response(200, json={
            "success": True,
            "result": {
                "name": "x",
                "resources": [{"name": "Right One", "url": "file:///etc/passwd"}],
            },
        })
    )
    async with AIHWClient(cache=fresh_cache) as client:
        with pytest.raises(DiscoveryError, match="invalid url"):
            await resolve_latest_url(
                client, DiscoverySpec(package_id="x", resource_name="Right One"),
            )


# ---------------------------------------------------------------------------
# Host pinning — discovery must only accept data.gov.au origins.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_resolve_off_host_url_rejected(fresh_cache: Cache):
    respx.get(
        url__startswith="https://data.gov.au/data/api/3/action/package_show",
    ).mock(
        return_value=httpx.Response(200, json={
            "success": True,
            "result": {
                "name": "x",
                "resources": [{"name": "Right One", "url": "https://attacker.com/evil.csv"}],
            },
        })
    )
    async with AIHWClient(cache=fresh_cache) as client:
        with pytest.raises(DiscoveryError, match="not on data.gov.au"):
            await resolve_latest_url(
                client, DiscoverySpec(package_id="x", resource_name="Right One"),
            )


@pytest.mark.asyncio
@respx.mock
async def test_resolve_data_gov_au_subdomain_allowed(fresh_cache: Cache):
    respx.get(
        url__startswith="https://data.gov.au/data/api/3/action/package_show",
    ).mock(
        return_value=httpx.Response(200, json={
            "success": True,
            "result": {
                "name": "x",
                "resources": [{"name": "Right One", "url": "https://www.data.gov.au/data/path/file.csv"}],
            },
        })
    )
    async with AIHWClient(cache=fresh_cache) as client:
        url = await resolve_latest_url(
            client, DiscoverySpec(package_id="x", resource_name="Right One"),
        )
    assert url.startswith("https://www.data.gov.au/")


def test_is_data_gov_au_host_check():
    assert _is_data_gov_au("https://data.gov.au/data/x.csv") is True
    assert _is_data_gov_au("https://www.data.gov.au/data/x.csv") is True
    assert _is_data_gov_au("https://cdn.data.gov.au/data/x.csv") is True
    assert _is_data_gov_au("https://DATA.gov.au/data/x.csv") is True  # case-insensitive
    # Off-host
    assert _is_data_gov_au("https://attacker.com/evil.csv") is False
    assert _is_data_gov_au("https://data.gov.au.attacker.com/x.csv") is False
    assert _is_data_gov_au("https://notdata.gov.au/x.csv") is False
    assert _is_data_gov_au("https://ev.il/data.gov.au") is False
    # Garbage
    assert _is_data_gov_au("not a url") is False
    assert _is_data_gov_au("") is False


# ---------------------------------------------------------------------------
# Server-side fallback: discovery failure must NOT break get_data.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_server_falls_back_to_yaml_url_when_discovery_fails(tmp_path: Path):
    """When CKAN is unreachable, _resolve_download_url must return cd.download_url."""
    from unittest.mock import patch

    from aihw_mcp.server import _resolve_download_url
    from aihw_mcp import curated as cmod

    cmod.reset_registry()
    cd = cmod.get("GRIM_DEATHS")
    cache = Cache(tmp_path / "test.db")
    async with AIHWClient(cache=cache) as client:
        async def boom(*a, **kw):
            raise AIHWAPIError("mocked failure")
        with patch.object(AIHWClient, "fetch_package", boom), \
             patch.object(AIHWClient, "_fetch_cached", boom):
            url = await _resolve_download_url(cd, client)
    assert url == cd.download_url
