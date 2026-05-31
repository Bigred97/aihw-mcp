"""Async fetcher for data.gov.au CSV/XLSX resources and CKAN package metadata.

Two endpoints:
- `fetch_resource(url)`  — pulls a static CSV/XLSX file by URL. Cached as "data".
- `fetch_package(name)`  — CKAN `package_show` for a dataset slug. Cached as "catalog".

data.gov.au is CKAN under the Drupal wrapper. The CKAN API path is
`/data/api/3/action/...`. Public, no auth, no documented rate limit. We send
a courteous User-Agent and dedupe concurrent in-flight requests for the
same URL so a burst of `latest()` calls fans in to one HTTP request.
"""
from __future__ import annotations

import asyncio
import json
import time
from contextvars import ContextVar
from typing import Any

import httpx

from .cache import TTL, Cache, CacheKind

DEFAULT_BASE_URL = "https://data.gov.au"
DEFAULT_TIMEOUT = httpx.Timeout(120.0, connect=15.0)  # GRIM CSV is ~25MB; allow time

# MyHospitals flat-data-extract paginates at a hard top=1000 cap. With
# server-side filter push-down (server.py) keeping the row count small, the
# remaining pages are fetched concurrently at this bound. Kept modest (6) so we
# stay polite to the AIHW API — the unfiltered ~700-page walk throttled at high
# concurrency, but a push-down-filtered ~30-page fetch at 6-in-flight does not.
_MYHOSPITALS_PAGE_CONCURRENCY = 6


# ─── stale signal (graceful-degradation reporting per CLAUDE.md dim #4) ─
# When the upstream data.gov.au endpoint is unreachable, _fetch_cached
# falls back to the cached payload regardless of TTL and records the
# staleness in this ContextVar. Server-side tool wrappers read it after
# the request chain and set DataResponse.stale / .stale_reason. ContextVar
# (not instance attr) so concurrent MCP tool calls each see their own state.
_stale_signal: ContextVar[tuple[bool, str | None]] = ContextVar(
    "aihw_mcp_stale_signal", default=(False, None)
)


def reset_stale_signal() -> None:
    """Clear the stale state. Call once at the start of each tool call."""
    _stale_signal.set((False, None))


def get_stale_signal() -> tuple[bool, str | None]:
    """Return (stale, reason) for the most recent fetch chain in this context."""
    return _stale_signal.get()


def _mark_stale(reason: str) -> None:
    """Record that a stale-cache fallback was served this context.

    If multiple fetches in one chain are stale, we keep the FIRST reason
    (it's usually the most informative — the originating upstream failure).
    """
    cur_stale, _ = _stale_signal.get()
    if not cur_stale:
        _stale_signal.set((True, reason))


class AIHWAPIError(Exception):
    """Raised when data.gov.au returns non-2xx or the request fails."""


class AIHWClient:
    def __init__(
        self,
        cache: Cache | None = None,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache = cache or Cache()
        self._http = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            transport=transport,
            headers={
                "User-Agent": "aihw-mcp/0.1 (+https://github.com/Bigred97/aihw-mcp)",
            },
            follow_redirects=True,
        )
        self._in_flight: dict[str, asyncio.Future[bytes]] = {}
        self._in_flight_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AIHWClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def fetch_resource(
        self, url: str, *, kind: CacheKind = "data"
    ) -> bytes:
        """Fetch a static CSV/XLSX file by URL. Cached. In-flight deduped."""
        if not url.startswith(("http://", "https://")):
            raise AIHWAPIError(f"Refusing to fetch non-http(s) URL: {url!r}")
        return await self._fetch_cached(url, kind=kind)

    async def fetch_myhospitals_extract(
        self,
        base_url: str,
        *,
        kind: CacheKind = "data",
        page_size: int = 1000,
        max_pages: int = 1000,
        concurrency: int = _MYHOSPITALS_PAGE_CONCURRENCY,
    ) -> bytes:
        """Fetch every page of an AIHW MyHospitals flat-data-extract endpoint.

        The API caps each call to 1000 records via `top`, paginated by `skip`.
        Page 0's `result.pagination.total_results_available` reports the row
        count up front, so we fetch page 0 then pull the remaining pages
        CONCURRENTLY (bounded by `concurrency`) instead of walking them one by
        one. Combined with server-side filter push-down (server.py) — which
        keeps the row count small — this brings the previously-unservable bulk
        extracts well under budget. If the API doesn't report a total we fall
        back to a sequential walk-until-short-page. The concatenated record list
        is serialised as `{"records": [...]}` JSON bytes and cached against
        `base_url`, so a warm call reuses the whole walk via one cache hit.

        Raises AIHWAPIError on any non-2xx page or unparseable payload. Graceful
        degradation: if the FIRST page errors and a cached concatenated payload
        exists, we serve it and mark stale. A failure on any later page is a
        hard error — partial data would corrupt the cached concatenation.
        """
        import json as _json

        if not base_url.startswith(("http://", "https://")):
            raise AIHWAPIError(f"Refusing to fetch non-http(s) URL: {base_url!r}")

        cached = await self.cache.get(base_url, ttl=TTL[kind])
        if cached is not None:
            return cached

        sep = "&" if "?" in base_url else "?"

        async def _get_page(page: int) -> tuple[list[dict[str, Any]], int | None]:
            """Fetch one page -> (records, total_results_available_or_None).

            Retries transient throttling/server errors with backoff so a single
            flaky page doesn't fail the whole (parallel) walk."""
            page_url = f"{base_url}{sep}skip={page * page_size}&top={page_size}"
            resp = None
            for attempt in range(4):
                resp = await self._http.get(page_url)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                break
            assert resp is not None
            resp.raise_for_status()
            try:
                payload = json.loads(resp.content.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise AIHWAPIError(
                    f"MyHospitals API non-JSON response on page {page}: {e}"
                ) from e
            result = payload.get("result") if isinstance(payload, dict) else None
            records = result.get("data") if isinstance(result, dict) else None
            if not isinstance(records, list):
                raise AIHWAPIError(
                    f"MyHospitals API page {page}: missing result.data list"
                )
            total = None
            if isinstance(result, dict):
                pag = result.get("pagination")
                if isinstance(pag, dict):
                    total = pag.get("total_results_available")
            return records, (total if isinstance(total, int) else None)

        # ── Page 0 (the only page eligible for the stale-cache fallback) ──
        try:
            first_records, total = await _get_page(0)
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            fallback = await self.cache.get_stale(base_url)
            if fallback is not None:
                payload, cached_at = fallback
                age_min = max(0, int((time.time() - cached_at) / 60))
                if isinstance(e, httpx.HTTPStatusError):
                    upstream = f"AIHW MyHospitals API returned {e.response.status_code}"
                else:
                    upstream = f"AIHW MyHospitals API unreachable ({type(e).__name__})"
                _mark_stale(
                    f"{upstream}; serving cached payload from ~{age_min} minute(s) ago"
                )
                return payload
            if isinstance(e, httpx.HTTPStatusError):
                raise AIHWAPIError(
                    f"MyHospitals API returned {e.response.status_code} on page 0"
                ) from e
            raise AIHWAPIError(
                f"MyHospitals API request failed on page 0 ({type(e).__name__})"
            ) from e

        all_records: list[dict[str, Any]] = list(first_records)

        if len(first_records) == page_size:
            try:
                if isinstance(total, int) and total > page_size:
                    # Known total -> fetch the remaining pages CONCURRENTLY.
                    n_pages = min(-(-total // page_size), max_pages)  # ceil
                    sem = asyncio.Semaphore(max(1, concurrency))

                    async def _guarded(p: int) -> tuple[int, list[dict[str, Any]]]:
                        async with sem:
                            recs, _ = await _get_page(p)
                            return p, recs

                    gathered = await asyncio.gather(
                        *(_guarded(p) for p in range(1, n_pages))
                    )
                    for _p, recs in sorted(gathered, key=lambda t: t[0]):
                        all_records.extend(recs)
                else:
                    # No total reported -> sequential walk-until-short-page.
                    for page in range(1, max_pages):
                        recs, _ = await _get_page(page)
                        all_records.extend(recs)
                        if len(recs) < page_size:
                            break
                    else:
                        raise AIHWAPIError(
                            f"MyHospitals API exceeded max_pages={max_pages} "
                            f"({len(all_records)} records) at {base_url!r}"
                        )
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                # Any later-page failure is a hard error (partial walk).
                raise AIHWAPIError(
                    f"MyHospitals API request failed mid-walk ({type(e).__name__})"
                ) from e

        concatenated = _json.dumps({"records": all_records}).encode("utf-8")
        await self.cache.set(base_url, concatenated, kind=kind)
        return concatenated

    async def fetch_package(self, package_id: str) -> dict[str, Any]:
        """Fetch CKAN package_show for a dataset slug. Returns the result dict.

        `package_id` is the data.gov.au dataset slug (e.g. 'grim-books').
        Raises AIHWAPIError if the dataset doesn't exist or CKAN returns success=false.
        """
        if "/" in package_id or "?" in package_id or "&" in package_id:
            raise AIHWAPIError(f"Bad package id: {package_id!r}")
        url = f"{self.base_url}/data/api/3/action/package_show?id={package_id}"
        body = await self._fetch_cached(url, kind="catalog")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise AIHWAPIError(f"CKAN returned non-JSON for {package_id!r}: {e}") from e
        if not payload.get("success"):
            err = payload.get("error", {})
            raise AIHWAPIError(f"CKAN error for {package_id!r}: {err}")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise AIHWAPIError(f"CKAN result missing for {package_id!r}")
        return result

    async def _fetch_cached(self, url: str, *, kind: CacheKind) -> bytes:
        cached = await self.cache.get(url, ttl=TTL[kind])
        if cached is not None:
            return cached

        async with self._in_flight_lock:
            existing = self._in_flight.get(url)
            if existing is None:
                future: asyncio.Future[bytes] = (
                    asyncio.get_running_loop().create_future()
                )
                self._in_flight[url] = future

        if existing is not None:
            return await existing

        try:
            try:
                resp = await self._http.get(url)
                resp.raise_for_status()
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                # Graceful degradation: when upstream is unreachable, fall
                # back to the most-recent cached payload (regardless of TTL)
                # rather than raising and breaking the agent's chain of
                # reasoning. Staleness is surfaced via _stale_signal and
                # ends up in DataResponse.stale / stale_reason.
                fallback = await self.cache.get_stale(url)
                if fallback is not None:
                    payload, cached_at = fallback
                    age_min = max(0, int((time.time() - cached_at) / 60))
                    if isinstance(e, httpx.HTTPStatusError):
                        upstream = f"AIHW API returned {e.response.status_code}"
                    else:
                        upstream = f"AIHW API unreachable ({type(e).__name__})"
                    # Don't include the full URL in stale_reason — surfaced
                    # verbatim in DataResponse.stale_reason and would leak
                    # internal CKAN paths.
                    _mark_stale(
                        f"{upstream}; serving cached payload from "
                        f"~{age_min} minute(s) ago"
                    )
                    future.set_result(payload)
                    return payload
                # Genuinely no cache to fall back to — preserve original behaviour.
                # Don't echo the upstream URL in error text: it leaks internal
                # CKAN paths to MCP clients and clutters the agent's reasoning
                # chain. The status / error class is sufficient context.
                if isinstance(e, httpx.HTTPStatusError):
                    raise AIHWAPIError(
                        f"data.gov.au returned {e.response.status_code}"
                    ) from e
                raise AIHWAPIError(
                    f"data.gov.au request failed ({type(e).__name__})"
                ) from e
            await self.cache.set(url, resp.content, kind=kind)
            future.set_result(resp.content)
            return resp.content
        except BaseException as e:
            if not future.done():
                future.set_exception(e)
            raise
        finally:
            async with self._in_flight_lock:
                self._in_flight.pop(url, None)
