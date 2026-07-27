"""Round-trip tests through the REAL FastMCP protocol path.

Every other test in this suite calls the tool's underlying async function
directly with a Python `dict` — that never crosses the JSON-RPC boundary,
so it can't catch a bug where FastMCP's Pydantic argument validation
rejects a value *before* the function body (and its lenient
`_validate_filters` helper) ever runs.

This file uses fastmcp's in-process `Client` to send arguments the way a
real MCP client actually does: `filters` arrives as a JSON-encoded STRING
(since MCP tool-call arguments are transmitted as JSON and many clients —
and the `mcp` SDK's own argument coercion in some paths — serialize dict
params to text rather than leaving them as a nested JSON object). Before
the fix, `filters: Annotated[dict[str, Any] | None, ...]` caused Pydantic
to reject the incoming string with a raw `dict_type` validation error,
never reaching `_validate_filters`. The fix widens the annotation to
`dict[str, Any] | str | None` so the string reaches the function body,
where `_validate_filters` already knows how to `json.loads()` it.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastmcp import Client

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
async def test_get_data_filters_as_json_string_over_protocol(mocked_client):
    """A JSON-encoded STRING `filters` arg must survive real MCP validation.

    This is the exact shape a spec-compliant MCP client sends when it
    serializes tool arguments to text. Pre-fix, this raised a Pydantic
    `dict_type` error at the transport boundary before `_validate_filters`
    (which already handles strings) ever ran.
    """
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "get_data",
            {
                "dataset_id": "GRIM_DEATHS",
                "filters": '{"cause_of_death": "Diabetes"}',
                "measures": "deaths",
            },
        )
    assert not result.is_error
    assert result.data.row_count > 0
    # result.data is deserialized from the wire JSON (structuredContent), so
    # records come back as plain dicts, not re-hydrated `Observation` objects.
    causes = {r["dimensions"]["cause_of_death"] for r in result.data.records}
    assert causes == {"Diabetes"}


@pytest.mark.asyncio
async def test_latest_filters_as_json_string_over_protocol(mocked_client):
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "latest",
            {
                "dataset_id": "GRIM_DEATHS",
                "filters": '{"cause_of_death": "Diabetes"}',
            },
        )
    assert not result.is_error
    assert result.data.row_count > 0


@pytest.mark.asyncio
async def test_top_n_filters_as_json_string_over_protocol(mocked_client):
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "top_n",
            {
                "dataset_id": "GRIM_DEATHS",
                "measure": "deaths",
                "n": 5,
                "filters": '{"sex": "Persons"}',
            },
        )
    assert not result.is_error
    assert result.data.row_count <= 5


@pytest.mark.asyncio
async def test_get_data_filters_as_malformed_json_string_over_protocol(mocked_client):
    """A malformed JSON string should surface the friendly ValueError hint,
    not a raw Pydantic validation error, and not crash the transport.
    """
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "get_data",
            {"dataset_id": "GRIM_DEATHS", "filters": "{not valid json"},
            raise_on_error=False,
        )
    assert result.is_error
    error_text = " ".join(
        getattr(block, "text", "") for block in result.content
    )
    assert "filters must be a JSON object" in error_text


@pytest.mark.asyncio
async def test_get_data_filters_as_dict_still_works_over_protocol(mocked_client):
    """Regression guard: widening the type to include `str` must not break
    the existing (and far more common) plain-dict calling convention.
    """
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "get_data",
            {
                "dataset_id": "GRIM_DEATHS",
                "filters": {"cause_of_death": "Diabetes"},
                "measures": "deaths",
            },
        )
    assert not result.is_error
    assert result.data.row_count > 0
