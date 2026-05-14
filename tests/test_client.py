"""Client-level tests for stale-cache fallback (graceful degradation).

When data.gov.au is unreachable and there's a cached payload past its TTL,
we serve the cached payload and surface the staleness via the ContextVar
so server tool wrappers can set DataResponse.stale / stale_reason.

See CLAUDE.md quality dimension #4 (Reliability + Caching).
"""
from __future__ import annotations

import time
from pathlib import Path

import aiosqlite
import httpx
import pytest
import respx

from aihw_mcp.cache import Cache
from aihw_mcp.client import (
    AIHWAPIError,
    AIHWClient,
    get_stale_signal,
    reset_stale_signal,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "cache.db"


async def _prime_stale_cache(
    db_path: Path, url: str, payload: bytes, age_hours: float
) -> None:
    """Put `payload` into the cache as if it was fetched `age_hours` ago.

    A regular `cache.get()` with a normal TTL will miss this row (because
    cached_at is older than the TTL window), but `cache.get_stale()` will
    still return it — which is exactly what the fallback path uses.
    """
    cache = Cache(db_path)
    await cache._ensure_init()
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO http_cache (cache_key, payload, cached_at, kind) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(cache_key) DO UPDATE SET "
            "payload=excluded.payload, cached_at=excluded.cached_at",
            (url, payload, time.time() - age_hours * 3600, "data"),
        )
        await conn.commit()


@pytest.mark.asyncio
@respx.mock
async def test_stale_fallback_serves_cached_payload_on_5xx(db_path: Path) -> None:
    """When upstream data.gov.au returns 5xx and we have a cached payload past
    its TTL, serve the cached payload and mark the response as stale. Agents
    continue reasoning rather than crashing."""
    url = "https://data.gov.au/some/aihw.csv"
    payload = b"col_a,col_b\n1,2\n3,4\n"

    # Prime an 8-day-old cache entry — past the 7-day data TTL, so cache.get()
    # misses but cache.get_stale() will still return it.
    await _prime_stale_cache(db_path, url, payload, age_hours=8 * 24)

    respx.get(url).mock(return_value=httpx.Response(503, text="Service Unavailable"))

    reset_stale_signal()
    cache = Cache(db_path)
    async with AIHWClient(cache=cache) as client:
        body = await client.fetch_resource(url)
        assert body == payload, "fallback must return the cached bytes"
        stale, reason = get_stale_signal()
        assert stale is True, "stale flag must be set after 5xx fallback"
        assert reason and "503" in reason, f"stale_reason should mention the 5xx: {reason}"
        assert "minute" in reason.lower(), f"stale_reason should report age: {reason}"


@pytest.mark.asyncio
@respx.mock
async def test_stale_fallback_serves_cached_on_request_error(db_path: Path) -> None:
    """Same as 5xx test but for httpx.RequestError (DNS / connection refused / etc.)."""
    url = "https://data.gov.au/some/aihw.csv"
    payload = b"col_a,col_b\n1,2\n"
    await _prime_stale_cache(db_path, url, payload, age_hours=8 * 24)

    respx.get(url).mock(side_effect=httpx.ConnectError("simulated DNS failure"))

    reset_stale_signal()
    cache = Cache(db_path)
    async with AIHWClient(cache=cache) as client:
        body = await client.fetch_resource(url)
        assert body == payload
        stale, reason = get_stale_signal()
        assert stale is True
        assert reason and "ConnectError" in reason


@pytest.mark.asyncio
@respx.mock
async def test_raises_when_no_stale_cache_to_fall_back_to(db_path: Path) -> None:
    """Empty cache + upstream 5xx → still raises AIHWAPIError (original
    behaviour when there's nothing to gracefully degrade to)."""
    url = "https://data.gov.au/some/aihw.csv"
    respx.get(url).mock(return_value=httpx.Response(503, text="Service Unavailable"))

    reset_stale_signal()
    cache = Cache(db_path)
    async with AIHWClient(cache=cache) as client:
        with pytest.raises(AIHWAPIError, match="503"):
            await client.fetch_resource(url)


@pytest.mark.asyncio
async def test_cache_get_stale_returns_payload_and_timestamp(db_path: Path) -> None:
    """Cache.get_stale() returns (payload, cached_at) regardless of TTL —
    the building block for the client's stale-fallback path."""
    from datetime import timedelta

    cache = Cache(db_path)
    await cache.set("https://example.org/x", b"hello", kind="data")
    # Normal `get` with a tiny TTL should miss
    fresh = await cache.get("https://example.org/x", ttl=timedelta(seconds=0))
    assert fresh is None
    # `get_stale` should return regardless of TTL
    stale = await cache.get_stale("https://example.org/x")
    assert stale is not None
    payload, cached_at = stale
    assert payload == b"hello"
    assert cached_at > 0
    # Non-existent key → None
    miss = await cache.get_stale("https://example.org/missing")
    assert miss is None
