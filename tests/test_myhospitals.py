"""Tests for the MyHospitals API curated datasets (v0.4.18).

Covers:
- The two new YAMLs load and register cleanly (`ED_WAITING_TIMES`,
  `ELECTIVE_SURGERY_WAITING_TIMES`).
- Schema invariants — required columns present, dimension values map
  hospital-level / state-level granularity selectors.
- The new `read_myhospitals_json` parser flattens the concatenated JSON
  payload our client emits.
- The new `AIHWClient.fetch_myhospitals_extract` walks paginated API
  responses and concatenates them. respx is used to mock the AIHW
  MyHospitals API so the unit suite stays offline.
- Filter translation works through the curated dimension_values map for
  the new granularity selectors (hospital / state) and triage / measure
  aliases.
"""
from __future__ import annotations

import json as _json
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from aihw_mcp import curated, parsing, shaping
from aihw_mcp.cache import Cache
from aihw_mcp.client import AIHWClient


# ─── canonical sample payloads (verbatim shape AIHW returns) ─────────────


def _make_ed_record(
    *,
    hospital_code: str = "H0021",
    hospital_name: str = "Royal Prince Alfred Hospital",
    unit_type: str = "H",
    state: str = "NSW",
    triage: str = "Resuscitation",
    measure_code: str = "MYH0010",
    measure_name: str = "Number of patients presenting to the emergency department",
    units: str = "patients",
    value: float = 1234.0,
    start: str = "2023-07-01",
    end: str = "2024-06-30",
    peer_group: str | None = "Principal referral hospitals",
) -> dict[str, Any]:
    return {
        "reporting_start_date": start,
        "reporting_end_date": end,
        "reporting_unit_code": hospital_code,
        "reporting_unit_name": hospital_name,
        "reporting_unit_type_code": unit_type,
        "mapped_state": state,
        "reported_measure_category_name": triage,
        "measure_code": measure_code,
        "measure_name": measure_name,
        "peer_group_name": peer_group,
        "value": value,
        "units_name": units,
    }


def _make_es_record(
    *,
    hospital_code: str = "H0014",
    hospital_name: str = "The Children's Hospital at Westmead",
    unit_type: str = "H",
    state: str = "NSW",
    specialty: str = "Cardio-thoracic surgery",
    measure_code: str = "MYH0009",
    measure_name: str = "Median waiting time for elective surgery",
    units: str = "days",
    value: float = 36.0,
    peer_value: float | None = 35.0,
    start: str = "2023-07-01",
    end: str = "2024-06-30",
    peer_group: str | None = "Children's hospitals",
) -> dict[str, Any]:
    return {
        "reporting_start_date": start,
        "reporting_end_date": end,
        "reporting_unit_code": hospital_code,
        "reporting_unit_name": hospital_name,
        "reporting_unit_type_code": unit_type,
        "mapped_state": state,
        "reported_measure_category_name": specialty,
        "measure_code": measure_code,
        "measure_name": measure_name,
        "peer_group_name": peer_group,
        "value": value,
        "peer_value": peer_value,
        "units_display": units,
    }


# ─── curated YAML schema contract ────────────────────────────────────────


def test_ed_waiting_times_loads():
    cd = curated.get("ED_WAITING_TIMES")
    assert cd is not None
    assert cd.format == "myhospitals_json"
    assert cd.download_url.startswith("https://myhospitalsapi.aihw.gov.au/")
    assert cd.source_url.startswith("https://www.aihw.gov.au/")


def test_elective_surgery_waiting_times_loads():
    cd = curated.get("ELECTIVE_SURGERY_WAITING_TIMES")
    assert cd is not None
    assert cd.format == "myhospitals_json"
    assert cd.download_url.startswith("https://myhospitalsapi.aihw.gov.au/")
    assert cd.source_url.startswith("https://www.aihw.gov.au/")


def test_ed_dataset_exposes_hospital_granularity_filter():
    """`reporting_unit_type` must accept 'hospital' / 'state' aliases — the
    selector that lets researchers narrow to per-hospital rows vs state rollups.
    """
    cd = curated.get("ED_WAITING_TIMES")
    assert cd is not None
    assert curated.translate_filter_value(cd, "reporting_unit_type", "hospital") == "H"
    assert curated.translate_filter_value(cd, "reporting_unit_type", "state") == "S"
    assert curated.translate_filter_value(cd, "reporting_unit_type", "H") == "H"


def test_ed_dataset_triage_aliases():
    cd = curated.get("ED_WAITING_TIMES")
    assert cd is not None
    for alias, canonical in (
        ("resuscitation", "Resuscitation"),
        ("emergency", "Emergency"),
        ("urgent", "Urgent"),
        ("semi_urgent", "Semi-Urgent"),
        ("non_urgent", "Non-Urgent"),
    ):
        assert (
            curated.translate_filter_value(cd, "triage_category", alias) == canonical
        )


def test_ed_dataset_measure_aliases():
    cd = curated.get("ED_WAITING_TIMES")
    assert cd is not None
    assert (
        curated.translate_filter_value(cd, "measure_code", "presentations")
        == "MYH0010"
    )
    assert (
        curated.translate_filter_value(cd, "measure_code", "percent_within_target")
        == "MYH0011"
    )


def test_es_dataset_measure_aliases():
    cd = curated.get("ELECTIVE_SURGERY_WAITING_TIMES")
    assert cd is not None
    assert (
        curated.translate_filter_value(cd, "measure_code", "median_wait_days")
        == "MYH0009"
    )
    assert (
        curated.translate_filter_value(cd, "measure_code", "percent_waited_over_365_days")
        == "MYH0007"
    )


def test_es_dataset_peer_value_is_measure():
    """`peer_value` must be a role=measure column so it's returned in records,
    not silently dropped as a dimension.
    """
    cd = curated.get("ELECTIVE_SURGERY_WAITING_TIMES")
    assert cd is not None
    assert cd.columns["peer_value"].role == "measure"
    assert cd.columns["value"].role == "measure"


def test_both_datasets_have_hospital_code_id():
    """`hospital_code` must be role=id so MyHospitals codes ('H0021') don't
    get treated as dimensions for cross-join purposes."""
    for ds_id in ("ED_WAITING_TIMES", "ELECTIVE_SURGERY_WAITING_TIMES"):
        cd = curated.get(ds_id)
        assert cd is not None
        assert cd.columns["hospital_code"].role == "id"


def test_state_filter_routes_through_aus_identity():
    """The state filter accepts full names + postcodes via aus_identity."""
    cd = curated.get("ED_WAITING_TIMES")
    assert cd is not None
    assert curated.translate_filter_value(cd, "state", "New South Wales") == "NSW"
    assert curated.translate_filter_value(cd, "state", "2000") == "NSW"  # postcode


# ─── parser contract ──────────────────────────────────────────────────────


def test_read_myhospitals_json_flattens_records():
    payload = {
        "records": [
            _make_ed_record(value=10.0),
            _make_ed_record(
                hospital_code="H0014",
                hospital_name="The Children's Hospital at Westmead",
                value=20.0,
            ),
        ]
    }
    df = parsing.read_myhospitals_json(_json.dumps(payload).encode("utf-8"))
    assert len(df) == 2
    assert "reporting_unit_code" in df.columns
    assert "value" in df.columns


def test_read_myhospitals_json_empty_records():
    df = parsing.read_myhospitals_json(_json.dumps({"records": []}).encode("utf-8"))
    assert df.empty


def test_read_myhospitals_json_rejects_missing_records_key():
    with pytest.raises(parsing.ParseError, match="missing top-level 'records'"):
        parsing.read_myhospitals_json(_json.dumps({"foo": []}).encode("utf-8"))


def test_read_myhospitals_json_rejects_empty_body():
    with pytest.raises(parsing.ParseError, match="empty"):
        parsing.read_myhospitals_json(b"")


# ─── shaping end-to-end (parser → DataResponse) ───────────────────────────


def _records_to_concat_bytes(records: list[dict[str, Any]]) -> bytes:
    return _json.dumps({"records": records}).encode("utf-8")


def test_ed_shaping_emits_observations_with_hospital_metadata():
    cd = curated.get("ED_WAITING_TIMES")
    assert cd is not None
    df = parsing.read_myhospitals_json(
        _records_to_concat_bytes(
            [
                _make_ed_record(
                    hospital_code="H0021",
                    hospital_name="Royal Prince Alfred Hospital",
                    triage="Resuscitation",
                    measure_code="MYH0010",
                    units="patients",
                    value=1234.0,
                ),
                _make_ed_record(
                    hospital_code="H0021",
                    hospital_name="Royal Prince Alfred Hospital",
                    triage="Emergency",
                    measure_code="MYH0010",
                    units="patients",
                    value=4567.0,
                ),
            ]
        )
    )
    resp = shaping.build_response(
        cd=cd, df=df, filters={}, measures="value",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    assert resp.row_count == 2
    codes = {r.dimensions.get("hospital_code") for r in resp.records}
    assert codes == {"H0021"}
    triages = {r.dimensions.get("triage_category") for r in resp.records}
    assert triages == {"Resuscitation", "Emergency"}


def test_ed_shaping_filters_to_hospital_granularity():
    cd = curated.get("ED_WAITING_TIMES")
    assert cd is not None
    df = parsing.read_myhospitals_json(
        _records_to_concat_bytes(
            [
                _make_ed_record(unit_type="H", hospital_code="H0021", value=10),
                _make_ed_record(
                    unit_type="S", hospital_code="NSW",
                    hospital_name="New South Wales", value=99999,
                ),
            ]
        )
    )
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"reporting_unit_type": "hospital"},
        measures="value",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    assert resp.row_count == 1
    assert resp.records[0].dimensions["hospital_code"] == "H0021"


def test_es_shaping_returns_value_and_peer_value():
    """ES is the only dataset with paired primary / benchmark measures."""
    cd = curated.get("ELECTIVE_SURGERY_WAITING_TIMES")
    assert cd is not None
    df = parsing.read_myhospitals_json(
        _records_to_concat_bytes(
            [
                _make_es_record(
                    hospital_code="H0014",
                    specialty="Cardio-thoracic surgery",
                    value=36.0,
                    peer_value=35.0,
                ),
            ]
        )
    )
    resp = shaping.build_response(
        cd=cd, df=df, filters={}, measures=None,
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    # Two measures per row: value + peer_value.
    measures = {r.measure for r in resp.records}
    assert measures == {"value", "peer_value"}
    by_measure = {r.measure: r.value for r in resp.records}
    assert by_measure["value"] == 36.0
    assert by_measure["peer_value"] == 35.0


def test_es_shaping_filter_by_specialty():
    cd = curated.get("ELECTIVE_SURGERY_WAITING_TIMES")
    assert cd is not None
    df = parsing.read_myhospitals_json(
        _records_to_concat_bytes(
            [
                _make_es_record(specialty="Cardio-thoracic surgery", value=36.0),
                _make_es_record(specialty="Orthopaedic surgery", value=180.0),
                _make_es_record(specialty="Cataract extraction", value=90.0),
            ]
        )
    )
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"surgical_specialty": "Cataract extraction"},
        measures="value",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    assert resp.row_count == 1
    assert resp.records[0].value == 90.0


# ─── client.fetch_myhospitals_extract pagination ─────────────────────────


def _api_response_bytes(records: list[dict[str, Any]]) -> bytes:
    payload = {
        "result": {
            "data": records,
            "pagination": {"skip": 0, "top": len(records), "total": len(records)},
        },
        "version_information": {},
    }
    return _json.dumps(payload).encode("utf-8")


@pytest.mark.asyncio
@respx.mock
async def test_fetch_myhospitals_extract_single_page(tmp_path: Path):
    """A single short page returns immediately — no second-page fetch."""
    base = "https://myhospitalsapi.aihw.gov.au/api/v1/flat-data-extract/MYH-ED-WAITS"
    records = [_make_ed_record(value=1.0), _make_ed_record(value=2.0)]
    route = respx.get(f"{base}?skip=0&top=1000").mock(
        return_value=httpx.Response(200, content=_api_response_bytes(records)),
    )
    cache = Cache(tmp_path / "cache.db")
    async with AIHWClient(cache=cache) as client:
        body = await client.fetch_myhospitals_extract(base)
    assert route.called
    payload = _json.loads(body)
    assert len(payload["records"]) == 2


@pytest.mark.asyncio
@respx.mock
async def test_fetch_myhospitals_extract_paginates_until_short_page(tmp_path: Path):
    """Two full pages of 1000 + one short page should fan-out to three calls."""
    base = "https://myhospitalsapi.aihw.gov.au/api/v1/flat-data-extract/MYH-ES"
    page0 = [_make_es_record(value=float(i)) for i in range(1000)]
    page1 = [_make_es_record(value=float(i)) for i in range(1000, 2000)]
    page2 = [_make_es_record(value=2001.0)]
    respx.get(f"{base}?skip=0&top=1000").mock(
        return_value=httpx.Response(200, content=_api_response_bytes(page0)),
    )
    respx.get(f"{base}?skip=1000&top=1000").mock(
        return_value=httpx.Response(200, content=_api_response_bytes(page1)),
    )
    respx.get(f"{base}?skip=2000&top=1000").mock(
        return_value=httpx.Response(200, content=_api_response_bytes(page2)),
    )
    cache = Cache(tmp_path / "cache.db")
    async with AIHWClient(cache=cache) as client:
        body = await client.fetch_myhospitals_extract(base, page_size=1000)
    payload = _json.loads(body)
    assert len(payload["records"]) == 2001


@pytest.mark.asyncio
@respx.mock
async def test_fetch_myhospitals_extract_uses_cache_on_warm_call(tmp_path: Path):
    """Second call should hit cache — no HTTP request fired."""
    base = "https://myhospitalsapi.aihw.gov.au/api/v1/flat-data-extract/MYH-ED-WAITS"
    records = [_make_ed_record(value=1.0)]
    route = respx.get(f"{base}?skip=0&top=1000").mock(
        return_value=httpx.Response(200, content=_api_response_bytes(records)),
    )
    cache = Cache(tmp_path / "cache.db")
    async with AIHWClient(cache=cache) as client:
        await client.fetch_myhospitals_extract(base)
        await client.fetch_myhospitals_extract(base)
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_fetch_myhospitals_extract_raises_on_first_page_error(tmp_path: Path):
    from aihw_mcp.client import AIHWAPIError

    base = "https://myhospitalsapi.aihw.gov.au/api/v1/flat-data-extract/MYH-ED-WAITS"
    respx.get(f"{base}?skip=0&top=1000").mock(
        return_value=httpx.Response(503, text="bad gateway"),
    )
    cache = Cache(tmp_path / "cache.db")
    async with AIHWClient(cache=cache) as client:
        with pytest.raises(AIHWAPIError, match="503"):
            await client.fetch_myhospitals_extract(base)


# ─── live smoke test (skipped by default) ─────────────────────────────────


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_ed_waiting_times_fetches_real_records():
    """Hit the real MyHospitals API end-to-end. Expensive — gated by `live`."""
    from aihw_mcp import server

    curated.reset_registry()
    await server.reset_client_for_tests()
    try:
        r = await server.get_data(
            "ED_WAITING_TIMES",
            filters={"reporting_unit_type": "state", "state": "NSW"},
            measures="value",
        )
        assert r.row_count > 0
        for rec in r.records:
            assert rec.dimensions.get("state") == "NSW"
    finally:
        await server.reset_client_for_tests()
