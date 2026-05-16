"""Realistic multi-step customer flows.

Some run with mocked fixtures (fast), others hit live data.gov.au (tagged
`live`, skipped by default). These act as the customer would: start with a
vague question, discover the right dataset, describe it, query it, and
confirm the result is meaningful.
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
# Unit-level flows (mocked, fast)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flow_public_health_diabetes_trend(mocked_client):
    """Customer: 'How have diabetes deaths changed over time?'

    Agent journey:
      1. search_datasets("diabetes deaths")
      2. describe_dataset → confirm measures
      3. get_data with cause filter
    """
    results = await server.search_datasets("diabetes deaths")
    assert any(s.id == "GRIM_DEATHS" for s in results), [s.id for s in results]

    detail = await server.describe_dataset("GRIM_DEATHS")
    measure_keys = {m.key for m in detail.measures}
    assert "deaths" in measure_keys
    assert "age_standardised_rate_per_100000" in measure_keys

    data = await server.get_data(
        "GRIM_DEATHS",
        filters={"cause_of_death": "Diabetes", "sex": "persons"},
        measures="deaths",
    )
    assert data.row_count > 10
    assert "Creative Commons" in data.attribution
    assert data.aihw_url.startswith("https://data.gov.au/")


@pytest.mark.asyncio
async def test_flow_regional_mortality(mocked_client):
    """Customer: 'Mortality rates by Australian state in 2023.'"""
    data = await server.get_data(
        "MORT_GEOGRAPHY",
        filters={"category": "state", "sex": "Persons"},
        measures="age_standardised_rate_per_100000",
    )
    assert data.row_count > 0
    for r in data.records:
        assert r.dimensions["category"] == "State and territory"
        assert r.dimensions["sex"] == "Persons"


@pytest.mark.asyncio
async def test_flow_cancer_breast_incidence(mocked_client):
    """Customer: 'Breast cancer incidence in women aged 50-54 over time.'"""
    data = await server.get_data(
        "CANCER_INCIDENCE_MORTALITY",
        filters={"cancer_type": "Breast cancer", "sex": "female", "type": "Incidence"},
        measures="age_50_to_54",
    )
    assert data.row_count > 0


@pytest.mark.asyncio
async def test_flow_health_expenditure_state_breakdown(mocked_client):
    """Customer: 'Health spending in NSW broken down by source.'"""
    data = await server.get_data(
        "HEALTH_EXPENDITURE",
        filters={"state": "nsw"},
        measures="real_expenditure_millions",
    )
    assert data.row_count > 10


@pytest.mark.asyncio
async def test_flow_youth_justice_indigenous_disparity(mocked_client):
    """Customer: 'Compare Indigenous vs total youth detention nationally.'"""
    data = await server.get_data(
        "YOUTH_JUSTICE_DETENTION",
        filters={"indigenous_status": ["Indigenous", "Total"],
                 "legal_status": "Total", "sex": "Total"},
        measures="avg_nightly_pop",
    )
    assert data.row_count > 0
    statuses = {r.dimensions.get("indigenous_status") for r in data.records}
    assert statuses == {"Indigenous", "Total"}


@pytest.mark.asyncio
async def test_flow_hospital_list_by_state(mocked_client):
    """Customer: 'List public hospitals in NSW.'"""
    data = await server.get_data(
        "PUBLIC_HOSPITALS",
        filters={"state": "NSW"},
        measures="number_of_available_beds",
    )
    assert data.row_count > 0


@pytest.mark.asyncio
async def test_flow_csv_for_spreadsheet_export(mocked_client):
    """Customer: 'Give me the data as CSV.'"""
    data = await server.get_data(
        "GRIM_DEATHS",
        filters={"cause_of_death": "Diabetes", "sex": "persons"},
        measures="deaths",
        format="csv",
    )
    assert data.csv is not None
    lines = data.csv.strip().split("\n")
    assert len(lines) > 5
    assert lines[0].startswith("period,measure,value,unit")


@pytest.mark.asyncio
async def test_flow_series_format_for_charting(mocked_client):
    data = await server.get_data(
        "GRIM_DEATHS",
        filters={"cause_of_death": "Diabetes", "sex": "persons"},
        measures=["deaths", "crude_rate_per_100000"],
        format="series",
    )
    assert len(data.records) == 2
    keys = {g["measure"] for g in data.records}
    assert keys == {"deaths", "crude_rate_per_100000"}


@pytest.mark.asyncio
async def test_flow_unhappy_path_helpful_error(mocked_client):
    """Customer typos a sex value. Error must guide them to valid options."""
    with pytest.raises(ValueError, match="Valid values") as exc_info:
        await server.get_data(
            "GRIM_DEATHS",
            filters={"sex": "narnia"},
            measures="deaths",
        )
    msg = str(exc_info.value)
    assert "female" in msg or "Females" in msg


@pytest.mark.asyncio
async def test_flow_response_envelope_invariants(mocked_client):
    """Every response carries the metadata an agent needs to cite the source."""
    data = await server.get_data(
        "GRIM_DEATHS",
        filters={"cause_of_death": "Diabetes", "sex": "persons"},
        measures="deaths",
    )
    assert data.dataset_id
    assert data.dataset_name
    assert data.source == "Australian Institute of Health and Welfare"
    assert data.attribution
    assert data.retrieved_at
    assert data.aihw_url.startswith("https://data.gov.au/")
    assert data.server_version


@pytest.mark.asyncio
async def test_flow_all_curated_datasets_return_data(mocked_client):
    """Sanity: every curated dataset returns SOME data with a basic query."""
    for dataset_id in curated.list_ids():
        cd = curated.get(dataset_id)
        wide_measures = [c.key for c in cd.columns.values() if c.role == "measure"]
        first_measure = wide_measures[0] if wide_measures else None
        if first_measure is None:
            continue
        data = await server.get_data(dataset_id, measures=first_measure)
        assert data.row_count > 0, (
            f"{dataset_id} returned no rows for measure {first_measure!r}"
        )
        assert data.source == "Australian Institute of Health and Welfare"
