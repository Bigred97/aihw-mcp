"""Network-failure resilience tests via respx.

These exercise the error paths in `client.py`:
- 404 → AIHWAPIError with helpful message
- 5xx → AIHWAPIError
- Connection timeout → AIHWAPIError
- Connection refused / DNS failure → AIHWAPIError
- Malformed JSON from CKAN package_show → AIHWAPIError
- file://, javascript: URLs rejected at the boundary
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
import respx

from aihw_mcp.cache import Cache
from aihw_mcp.client import AIHWAPIError, AIHWClient


@pytest.fixture
def fresh_cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "cache.db")


@pytest.mark.asyncio
@respx.mock
async def test_fetch_resource_404(fresh_cache: Cache):
    url = "https://data.gov.au/test/file.csv"
    respx.get(url).mock(return_value=httpx.Response(404))
    async with AIHWClient(cache=fresh_cache) as client:
        with pytest.raises(AIHWAPIError, match="404"):
            await client.fetch_resource(url)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_resource_500(fresh_cache: Cache):
    url = "https://data.gov.au/test/file.csv"
    respx.get(url).mock(return_value=httpx.Response(503, text="upstream gone"))
    async with AIHWClient(cache=fresh_cache) as client:
        with pytest.raises(AIHWAPIError, match="503"):
            await client.fetch_resource(url)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_resource_timeout(fresh_cache: Cache):
    url = "https://data.gov.au/test/file.csv"
    respx.get(url).mock(side_effect=httpx.ConnectTimeout("timed out"))
    async with AIHWClient(cache=fresh_cache) as client:
        with pytest.raises(AIHWAPIError, match="request failed"):
            await client.fetch_resource(url)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_resource_dns_failure(fresh_cache: Cache):
    url = "https://data.gov.au/test/file.csv"
    respx.get(url).mock(side_effect=httpx.ConnectError("dns lookup failed"))
    async with AIHWClient(cache=fresh_cache) as client:
        with pytest.raises(AIHWAPIError, match="request failed"):
            await client.fetch_resource(url)


@pytest.mark.asyncio
async def test_fetch_resource_rejects_non_http_url(fresh_cache: Cache):
    """file:// / javascript: / data: URLs must be refused at the boundary."""
    async with AIHWClient(cache=fresh_cache) as client:
        for url in (
            "file:///etc/passwd",
            "javascript:alert(1)",
            "data:text/plain,hello",
            "ftp://example.org/file.csv",
            "",
        ):
            with pytest.raises(AIHWAPIError, match="non-http"):
                await client.fetch_resource(url)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_package_malformed_json(fresh_cache: Cache):
    url_pattern = "https://data.gov.au/data/api/3/action/package_show"
    respx.get(url__startswith=url_pattern).mock(
        return_value=httpx.Response(200, text="<html>not json</html>")
    )
    async with AIHWClient(cache=fresh_cache) as client:
        with pytest.raises(AIHWAPIError, match="non-JSON"):
            await client.fetch_package("grim-books")


@pytest.mark.asyncio
@respx.mock
async def test_fetch_package_success_false(fresh_cache: Cache):
    url_pattern = "https://data.gov.au/data/api/3/action/package_show"
    respx.get(url__startswith=url_pattern).mock(
        return_value=httpx.Response(
            200, json={"success": False, "error": {"message": "not found"}}
        )
    )
    async with AIHWClient(cache=fresh_cache) as client:
        with pytest.raises(AIHWAPIError, match="CKAN error"):
            await client.fetch_package("does-not-exist")


@pytest.mark.asyncio
async def test_fetch_package_rejects_bad_id_chars(fresh_cache: Cache):
    async with AIHWClient(cache=fresh_cache) as client:
        for bad in ("with/slash", "with?question", "with&ampersand"):
            with pytest.raises(AIHWAPIError, match="Bad package id"):
                await client.fetch_package(bad)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_resource_cache_hit_does_not_refetch(fresh_cache: Cache):
    url = "https://data.gov.au/test/file.csv"
    route = respx.get(url).mock(return_value=httpx.Response(200, content=b"hello"))
    async with AIHWClient(cache=fresh_cache) as client:
        assert await client.fetch_resource(url) == b"hello"
        assert await client.fetch_resource(url) == b"hello"
        assert await client.fetch_resource(url) == b"hello"
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_fetch_resource_in_flight_dedup(fresh_cache: Cache):
    """Parallel callers for the same URL → exactly 1 actual HTTP request."""
    url = "https://data.gov.au/test/file.csv"

    async def slow_response(request):
        await asyncio.sleep(0.05)
        return httpx.Response(200, content=b"hello")

    route = respx.get(url).mock(side_effect=slow_response)
    async with AIHWClient(cache=fresh_cache) as client:
        results = await asyncio.gather(*(client.fetch_resource(url) for _ in range(10)))
    assert all(r == b"hello" for r in results)
    assert route.call_count == 1
