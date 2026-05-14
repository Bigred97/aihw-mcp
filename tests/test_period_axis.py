"""v0.1.1 — tests for period_dimension-aware filtering and sorting on wide datasets.

Before v0.1.1 there were two real bugs hitting customers on wide-layout datasets:

  1. `latest()` returned whatever row happened to be last in source order.
     For GRIM that's incidentally the most-recent year because AIHW publishes
     it year-sorted ascending, but it was fragile — a re-sorted release would
     silently start returning a 1907 row.

  2. `start_period`/`end_period` on get_data were silently ignored. Customer
     wrote `get_data("GRIM_DEATHS", start_period="2000", end_period="2010")`
     expecting a time-range filter and got every year back.

This module verifies the v0.1.1 fix end-to-end against real GRIM fixture data.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from aihw_mcp import curated, parsing, server, shaping
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
async def reset_state():
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
# period_dimension is declared on all five time-series datasets
# ---------------------------------------------------------------------------

def test_period_dimension_set_on_time_series_datasets():
    expected = {
        "GRIM_DEATHS": "year",
        "MORT_GEOGRAPHY": "YEAR",
        "CANCER_INCIDENCE_MORTALITY": "year",
        "HEALTH_EXPENDITURE": "financial_year",
        "YOUTH_JUSTICE_DETENTION": "year",
    }
    for dataset_id, period_dim in expected.items():
        cd = curated.get(dataset_id)
        assert cd is not None
        assert cd.period_dimension == period_dim, (
            f"{dataset_id}: expected period_dimension={period_dim!r}, "
            f"got {cd.period_dimension!r}"
        )


def test_period_dimension_unset_on_register():
    """PUBLIC_HOSPITALS is a register, not a time series."""
    cd = curated.get("PUBLIC_HOSPITALS")
    assert cd is not None
    assert cd.period_dimension is None


def test_period_dimension_references_a_real_column():
    """If declared, period_dimension must match a curated column key."""
    for cd in curated.list_all():
        if cd.period_dimension is None:
            continue
        col_keys = {c.key for c in cd.columns.values()}
        assert cd.period_dimension in col_keys, (
            f"{cd.id}: period_dimension={cd.period_dimension!r} not in columns"
        )


# ---------------------------------------------------------------------------
# Bug fix #1: latest() must return the MOST RECENT period, not source-order last
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_latest_grim_returns_most_recent_year(mocked_client):
    """latest() on GRIM must return the row with the highest `year`."""
    r = await server.latest(
        "GRIM_DEATHS",
        filters={"cause_of_death": "Diabetes", "sex": "persons"},
        measures="deaths",
    )
    assert r.row_count == 1
    year = r.records[0].dimensions["year"]
    # Fixture spans 1907→2023; latest must be the max year present.
    assert year == "2023", f"expected latest year 2023, got {year!r}"


@pytest.mark.asyncio
async def test_latest_grim_per_measure_returns_most_recent(mocked_client):
    """With multiple measures, latest returns the most-recent per measure."""
    r = await server.latest(
        "GRIM_DEATHS",
        filters={"cause_of_death": "All causes combined", "sex": "persons"},
        measures=["deaths", "crude_rate_per_100000"],
    )
    assert r.row_count == 2  # one row per measure
    years = {rec.dimensions["year"] for rec in r.records}
    assert years == {"2023"}


@pytest.mark.asyncio
async def test_latest_works_with_shuffled_source_order(mocked_client):
    """latest() must NOT rely on source row order — even if AIHW shuffles rows."""
    # Build a synthetic shuffled fixture by sorting reverse
    cd = curated.get("GRIM_DEATHS")
    df = parsing.read_csv((FIXTURE_DIR / "grim_head.csv").read_bytes())
    # Reverse-sort by year so the oldest row comes last in source order
    df_shuffled = df.sort_values("year", ascending=False).reset_index(drop=True)
    # Build_response directly to exercise the period-aware sort
    df_shuffled = parsing.drop_blank_rows(
        df_shuffled, [c.source_column for c in cd.columns.values() if c.role == "dimension"]
    )
    resp = shaping.build_response(
        cd=cd, df=df_shuffled,
        filters={"cause_of_death": "Diabetes", "sex": "persons"},
        measures="deaths",
        start_period=None, end_period=None,
        fmt="records", user_query={}, last_n=1,
    )
    assert resp.row_count == 1
    assert resp.records[0].dimensions["year"] == "2023"


# ---------------------------------------------------------------------------
# Bug fix #2: start_period / end_period now filter wide datasets
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_data_period_range_filters_wide_dataset(mocked_client):
    """start_period and end_period must narrow the result on GRIM (was silently ignored)."""
    r = await server.get_data(
        "GRIM_DEATHS",
        filters={"cause_of_death": "Diabetes", "sex": "persons"},
        measures="deaths",
        start_period="2000",
        end_period="2010",
    )
    assert r.row_count > 0
    years = {rec.dimensions["year"] for rec in r.records}
    # Every returned year must fall in [2000, 2010]
    assert all(2000 <= int(y) <= 2010 for y in years), f"out-of-range years: {years}"
    # And we should see multiple years in the window
    assert len(years) >= 5


@pytest.mark.asyncio
async def test_get_data_start_period_only(mocked_client):
    r = await server.get_data(
        "GRIM_DEATHS",
        filters={"cause_of_death": "Diabetes", "sex": "persons"},
        measures="deaths",
        start_period="2020",
    )
    assert r.row_count > 0
    for rec in r.records:
        assert int(rec.dimensions["year"]) >= 2020


@pytest.mark.asyncio
async def test_get_data_end_period_only(mocked_client):
    r = await server.get_data(
        "GRIM_DEATHS",
        filters={"cause_of_death": "Diabetes", "sex": "persons"},
        measures="deaths",
        end_period="1920",
    )
    assert r.row_count > 0
    for rec in r.records:
        assert int(rec.dimensions["year"]) <= 1920


@pytest.mark.asyncio
async def test_get_data_period_range_on_financial_year(mocked_client):
    """Financial-year format ('2009-10') must work via the lenient parser."""
    r = await server.get_data(
        "HEALTH_EXPENDITURE",
        filters={"state": "nsw"},
        measures="real_expenditure_millions",
        start_period="2010",
        end_period="2011",
    )
    assert r.row_count > 0
    for rec in r.records:
        fy = rec.dimensions["financial_year"]
        # Lenient parse: "2010-11" → "2010", "2011-12" → "2011". Both in range.
        assert fy in ("2010-11", "2011-12"), fy


@pytest.mark.asyncio
async def test_get_data_period_range_register_dataset_silently_ignored(mocked_client):
    """PUBLIC_HOSPITALS has no period_dimension — start/end_period must be
    silently ignored, not error. Backward-compat with pre-0.1.1 behavior."""
    r = await server.get_data(
        "PUBLIC_HOSPITALS",
        filters={"state": "NSW"},
        measures="number_of_available_beds",
        start_period="2010",
        end_period="2020",
    )
    # Should return data (period args are ignored for register datasets)
    assert r.row_count > 0


@pytest.mark.asyncio
async def test_get_data_no_period_args_returns_full_history(mocked_client):
    """Sanity: without period args, the result is the full history."""
    r = await server.get_data(
        "GRIM_DEATHS",
        filters={"cause_of_death": "Diabetes", "sex": "persons"},
        measures="deaths",
    )
    years = {int(rec.dimensions["year"]) for rec in r.records}
    # Fixture covers 1907 → 2023
    assert min(years) <= 1910
    assert max(years) >= 2020


# ---------------------------------------------------------------------------
# Fuzzy "did you mean" suggestions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_typo_in_filter_value_suggests_correction(mocked_client):
    """Customer types 'femal' instead of 'female' → error includes the suggestion."""
    with pytest.raises(ValueError, match="Did you mean") as exc_info:
        await server.get_data(
            "GRIM_DEATHS",
            filters={"cause_of_death": "Diabetes", "sex": "femal"},
            measures="deaths",
        )
    msg = str(exc_info.value)
    assert "female" in msg.lower()


@pytest.mark.asyncio
async def test_typo_in_measure_suggests_correction(mocked_client):
    """Typo in measure name surfaces a suggestion."""
    with pytest.raises(ValueError, match="Did you mean") as exc_info:
        await server.get_data(
            "GRIM_DEATHS",
            filters={"cause_of_death": "Diabetes", "sex": "persons"},
            measures="death",  # missing the trailing 's'
        )
    msg = str(exc_info.value)
    assert "deaths" in msg


@pytest.mark.asyncio
async def test_typo_in_filter_key_suggests_correction(mocked_client):
    """Typo in filter key surfaces a suggestion."""
    with pytest.raises(ValueError, match="Did you mean") as exc_info:
        await server.get_data(
            "GRIM_DEATHS",
            filters={"caus_of_death": "Diabetes"},  # missing 'e'
            measures="deaths",
        )
    msg = str(exc_info.value)
    assert "cause_of_death" in msg


@pytest.mark.asyncio
async def test_far_off_input_no_misleading_suggestion(mocked_client):
    """Wildly different input should NOT produce a 'did you mean' suggestion."""
    with pytest.raises(ValueError) as exc_info:
        await server.get_data(
            "GRIM_DEATHS",
            filters={"sex": "xyzqwerty"},
            measures="deaths",
        )
    # No 'Did you mean' — just the 'Try one of' fallback
    assert "Did you mean" not in str(exc_info.value)
    assert "Try one of" in str(exc_info.value)


# ---------------------------------------------------------------------------
# top_n still works alongside period filtering (period args dropped by top_n)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_top_n_with_period_filter_in_filters_dict(mocked_client):
    """Customer can still narrow top_n by year using a dimension filter."""
    r = await server.top_n(
        "GRIM_DEATHS", "deaths", n=3,
        filters={"sex": "persons", "year": "2023"},
    )
    assert r.row_count <= 3
    for rec in r.records:
        assert rec.dimensions["year"] == "2023"
