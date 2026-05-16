"""Adversarial / fuzz inputs into every public tool.

These probe boundaries the unit-validation tests don't reach: very long
strings, Unicode (emoji, RTL, combining marks), path-traversal attempts,
URL-injection characters in filter values, type confusion (bool vs int,
NaN, infinity), and edge integer values for `limit`.

Goal: every weird input either returns a clean result OR raises a ValueError
with an actionable message. Nothing should crash with a stack trace, a 500,
or silently return wrong data.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from aihw_mcp import curated, server
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


# ---------------------------------------------------------------------------
# search_datasets
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("bad_query", [
    None, 123, 1.5, True, [], {}, object(), bytes(b"mortality"),
])
async def test_search_datasets_rejects_non_string_query(bad_query):
    with pytest.raises(ValueError):
        await server.search_datasets(bad_query)  # type: ignore[arg-type]


@pytest.mark.asyncio
@pytest.mark.parametrize("ws", ["", "   ", "\t\t", "\n\n", " \r\n "])
async def test_search_datasets_rejects_blank(ws):
    with pytest.raises(ValueError, match="query is required"):
        await server.search_datasets(ws)


@pytest.mark.asyncio
async def test_search_datasets_handles_huge_query():
    huge = "mortality " * 2000  # ~20KB
    r = await server.search_datasets(huge, limit=3)
    assert isinstance(r, list)


@pytest.mark.asyncio
async def test_search_datasets_handles_unicode():
    for q in ["死亡率", "🏥 hospital", "Mörtålity", "𝓒𝓪𝓷𝓬𝓮𝓻", "naïve"]:
        r = await server.search_datasets(q, limit=3)
        assert isinstance(r, list)


@pytest.mark.asyncio
async def test_search_datasets_handles_special_chars():
    for q in ["mortality'; DROP TABLE x;--", "<script>alert(1)</script>",
              "../../etc/passwd", "../%2e%2e/passwd", "%00", "\x00mortality"]:
        r = await server.search_datasets(q, limit=3)
        assert isinstance(r, list)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_limit", [0, -1, -100, False, 1.5, "10", None])
async def test_search_datasets_rejects_bad_limit(bad_limit):
    with pytest.raises(ValueError):
        await server.search_datasets("mortality", limit=bad_limit)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_search_datasets_huge_limit_clipped_by_pydantic():
    from pydantic import ValidationError
    try:
        r = await server.search_datasets("mortality", limit=10**6)
        assert len(r) <= len(curated.list_ids())
    except (ValueError, ValidationError):
        pass  # expected


# ---------------------------------------------------------------------------
# describe_dataset
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", [None, 123, 1.5, True, [], {}, b"GRIM"])
async def test_describe_rejects_non_string(bad_id):
    with pytest.raises(ValueError, match="must be a string"):
        await server.describe_dataset(bad_id)  # type: ignore[arg-type]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", [
    "../etc/passwd",
    "GRIM/DEATHS",
    "GRIM%20DEATHS",
    "GRIM DEATHS",
    "grim$deaths",
    "GRIM;DEATHS",
    "GRIM\x00DEATHS",
    "🚀GRIM_DEATHS",
    "?dataset=GRIM_DEATHS",
])
async def test_describe_rejects_invalid_chars(bad_id):
    with pytest.raises(ValueError, match="invalid characters"):
        await server.describe_dataset(bad_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("ws_id", ["", "   ", "\t", "\n"])
async def test_describe_rejects_blank(ws_id):
    with pytest.raises(ValueError, match="empty"):
        await server.describe_dataset(ws_id)


@pytest.mark.asyncio
async def test_describe_case_insensitive():
    d_upper = await server.describe_dataset("GRIM_DEATHS")
    d_lower = await server.describe_dataset("grim_deaths")
    d_mixed = await server.describe_dataset("Grim_Deaths")
    d_padded = await server.describe_dataset("  GRIM_DEATHS  ")
    assert d_upper.id == d_lower.id == d_mixed.id == d_padded.id == "GRIM_DEATHS"


@pytest.mark.asyncio
async def test_describe_every_curated_dataset():
    """No dataset should error on describe — they all have valid YAMLs."""
    for dataset_id in curated.list_ids():
        d = await server.describe_dataset(dataset_id)
        assert d.id == dataset_id
        assert d.name
        assert d.description
        assert d.source_url.startswith("https://")
        assert d.dimensions or d.measures


# ---------------------------------------------------------------------------
# get_data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("bad_filters", [
    "not a dict", ["state", "nsw"], 42, 3.14, True,
])
async def test_get_data_rejects_non_dict_filters(bad_filters):
    with pytest.raises(ValueError, match="filters must be"):
        await server.get_data("GRIM_DEATHS", filters=bad_filters)  # type: ignore[arg-type]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_measures", [
    42, 1.5, True, {"a": "b"}, object(),
])
async def test_get_data_rejects_non_string_measures(bad_measures):
    with pytest.raises(ValueError, match="must be a string or list"):
        await server.get_data("GRIM_DEATHS", measures=bad_measures)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_data_rejects_measure_list_with_non_strings():
    with pytest.raises(ValueError, match="must be strings"):
        await server.get_data("GRIM_DEATHS", measures=["deaths", 42])  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_data_rejects_empty_string_in_measure_list():
    with pytest.raises(ValueError, match="empty string"):
        await server.get_data("GRIM_DEATHS", measures=["deaths", ""])


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_period", [
    "??", "-1", "abcd", "2024'", "2024;",
    "2024/01", "2024.01", "https://evil/2024",
    "𝟚𝟘𝟚𝟜",  # mathematical digits
])
async def test_get_data_rejects_bad_periods(bad_period):
    with pytest.raises(ValueError, match="invalid format"):
        await server.get_data("GRIM_DEATHS", start_period=bad_period)


@pytest.mark.asyncio
async def test_get_data_strips_period_whitespace():
    try:
        await server.get_data("GRIM_DEATHS", start_period="2024 ")
    except ValueError as e:
        assert "invalid format" not in str(e)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_format", ["json", "PARQUET", "table", "PROTOBUF", "", " "])
async def test_get_data_rejects_bad_format(bad_format):
    with pytest.raises(ValueError, match="Unknown format"):
        await server.get_data("GRIM_DEATHS", format=bad_format)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_data_filter_with_url_injection_chars(mocked_client):
    r = await server.get_data(
        "GRIM_DEATHS",
        filters={"cause_of_death": "Diabetes?&=/#"},
        measures="deaths",
    )
    assert r.row_count == 0


@pytest.mark.asyncio
async def test_get_data_filter_with_huge_value(mocked_client):
    r = await server.get_data(
        "GRIM_DEATHS",
        filters={"cause_of_death": "X" * 10000},
        measures="deaths",
    )
    assert r.row_count == 0


@pytest.mark.asyncio
async def test_get_data_filter_with_unicode(mocked_client):
    r = await server.get_data(
        "GRIM_DEATHS",
        filters={"cause_of_death": "Bürger King 🍔 株式会社"},
        measures="deaths",
    )
    assert r.row_count == 0


@pytest.mark.asyncio
async def test_get_data_empty_filter_dict_returns_all(mocked_client):
    """{} filters should NOT raise — it means 'no filter applied'."""
    r = await server.get_data("GRIM_DEATHS", filters={}, measures="deaths")
    assert r.row_count > 50


@pytest.mark.asyncio
async def test_get_data_list_filter_one_match_one_miss(mocked_client):
    r = await server.get_data(
        "GRIM_DEATHS",
        filters={"cause_of_death": ["Diabetes", "DOES NOT EXIST"], "sex": "persons"},
        measures="deaths",
    )
    # Only Diabetes will match — but should return >0 rows, not crash
    assert r.row_count > 0
    causes = {r_.dimensions["cause_of_death"] for r_ in r.records}
    assert causes == {"Diabetes"}


@pytest.mark.asyncio
async def test_get_data_periods_equal_allowed(mocked_client):
    r = await server.get_data(
        "GRIM_DEATHS", start_period="2010", end_period="2010", measures="deaths",
    )
    assert isinstance(r.row_count, int)


@pytest.mark.asyncio
async def test_get_data_period_swap_caught():
    with pytest.raises(ValueError, match="before start_period"):
        await server.get_data(
            "GRIM_DEATHS", start_period="2025", end_period="2020",
        )


# ---------------------------------------------------------------------------
# latest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_latest_unknown_dataset_raises():
    with pytest.raises(ValueError, match="not a curated"):
        await server.latest("DOES_NOT_EXIST")


@pytest.mark.asyncio
async def test_latest_passes_validation_through(mocked_client):
    with pytest.raises(ValueError, match="filters must be"):
        await server.latest("GRIM_DEATHS", filters="bad")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# list_curated
# ---------------------------------------------------------------------------

def test_list_curated_idempotent():
    ids1 = server.list_curated()
    ids2 = server.list_curated()
    assert ids1 == ids2
    assert ids1 == sorted(ids1)


def test_list_curated_returns_six():
    assert len(server.list_curated()) == 6
