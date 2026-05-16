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


# ─── Item 3: error-message sanitization on the client layer ────────────
# AIHWAPIError messages surface up through `_fetch_and_parse` into the
# user-facing ValueError. They must not contain the full CKAN URL.


@pytest.mark.asyncio
@respx.mock
async def test_fetch_resource_500_error_does_not_leak_url(fresh_cache: Cache):
    """5xx error message must not embed the full URL — it's an internal detail."""
    url = "https://data.gov.au/data/api/3/action/some-internal-ckan-path"
    respx.get(url).mock(return_value=httpx.Response(503, text="gone"))
    async with AIHWClient(cache=fresh_cache) as client:
        with pytest.raises(AIHWAPIError) as exc_info:
            await client.fetch_resource(url)
        msg = str(exc_info.value)
        assert "503" in msg  # status code is fine to surface
        assert url not in msg, f"error leaks full URL: {msg}"
        assert "/data/api/3/action/" not in msg, f"error leaks CKAN path: {msg}"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_resource_connection_error_does_not_leak_url(
    fresh_cache: Cache,
):
    """Network-error message must not embed the full URL either."""
    url = "https://data.gov.au/data/api/3/action/some-internal-ckan-path"
    respx.get(url).mock(side_effect=httpx.ConnectError("dns failed"))
    async with AIHWClient(cache=fresh_cache) as client:
        with pytest.raises(AIHWAPIError) as exc_info:
            await client.fetch_resource(url)
        msg = str(exc_info.value)
        assert url not in msg, f"error leaks full URL: {msg}"
        assert "/data/api/3/action/" not in msg, f"error leaks CKAN path: {msg}"


@pytest.mark.asyncio
@respx.mock
async def test_stale_signal_reason_does_not_leak_url(fresh_cache: Cache):
    """Stale fallback reason must not embed the upstream URL — it's user-visible."""
    from aihw_mcp.client import get_stale_signal, reset_stale_signal

    url = "https://data.gov.au/data/api/3/action/some-internal-ckan-path"
    # Prime the cache.
    respx.get(url).mock(return_value=httpx.Response(200, content=b"hello"))
    async with AIHWClient(cache=fresh_cache) as client:
        assert await client.fetch_resource(url) == b"hello"

    # Now make the upstream fail and re-fetch — stale fallback should fire.
    respx.get(url).mock(return_value=httpx.Response(503))
    async with AIHWClient(cache=fresh_cache) as client:
        # Force TTL bypass: stale fallback only triggers when cache.get returns None.
        # Use ttl=0 path via clearing fresh entries, but simplest: just reset signal
        # then directly invoke _fetch_cached with a kind that has expired TTL.
        reset_stale_signal()
        # Use fetch_resource normally — the cached entry is still warm so it'll be
        # served from cache (not stale path). To exercise the stale path, we need
        # to clear the cache TTL. Drop in a new client with a cache whose TTL is 0
        # for "data". Simpler: monkey-patch cache.get to return None.

        async def force_miss(*_a, **_kw):
            return None

        client.cache.get = force_miss  # type: ignore[method-assign]
        body = await client.fetch_resource(url)
        assert body == b"hello"  # stale fallback served
        stale, reason = get_stale_signal()
        assert stale is True
        assert reason is not None
        assert url not in reason, f"stale_reason leaks full URL: {reason}"
        assert "/data/api/3/action/" not in reason, (
            f"stale_reason leaks CKAN path: {reason}"
        )
