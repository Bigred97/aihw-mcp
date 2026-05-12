"""Data-layer edge cases against real and synthetic input.

Covers the failure modes AIHW data has historically produced:
- "na" / "*" / "-" privacy-suppressed cells in numeric columns
- All-blank rows trailing the data block
- Mixed-dtype columns (string + float)
- Unicode bytes in source columns
- Trailing/leading whitespace on canonical state codes
- Numeric IDs that pandas coerces to floats (trailing '.0')
"""
from __future__ import annotations

from io import BytesIO

import openpyxl
import pandas as pd
import pytest

from aihw_mcp import curated, parsing, shaping


def _build_synthetic_xlsx(sheet_name: str, rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_xlsx_with_nan_cells():
    body = _build_synthetic_xlsx("data", [
        ["state", "cause", "deaths"],
        ["NSW", "Diabetes", 100],
        ["NSW", "Stroke", None],     # privacy-suppressed
        ["NSW", "Heart",  "*"],      # AIHW sentinel
        ["NSW", "Liver",  "na"],     # historical sentinel
        ["VIC", "Diabetes", 250],
    ])
    df = parsing.read_xlsx(body, sheet="data", header_row=1)
    assert "deaths" in df.columns
    assert len(df) == 5
    # When coerced to numeric, '*' and 'na' should become NaN
    df["deaths"] = pd.to_numeric(df["deaths"], errors="coerce")
    assert df["deaths"].isna().sum() == 3
    assert int(df["deaths"].sum()) == 350


def test_parse_handles_trailing_blank_rows():
    body = _build_synthetic_xlsx("data", [
        ["state", "cause", "deaths"],
        ["NSW", "Diabetes", 100],
        ["NSW", "Stroke", 150],
        [None, None, None],
        [None, None, None],
    ])
    df = parsing.read_xlsx(body, sheet="data", header_row=1)
    cleaned = parsing.drop_blank_rows(df, ["state", "cause"])
    assert len(cleaned) == 2


def test_parse_csv_with_bom():
    body = "﻿state,deaths\nNSW,100\n".encode("utf-8")
    df = parsing.read_csv(body)
    assert list(df.columns) == ["state", "deaths"]
    assert df.iloc[0]["deaths"] == 100


def test_parse_csv_with_unicode_data():
    body = "name,country\n国立病院,JP\n🏥 BigHospital,AU\n".encode("utf-8")
    df = parsing.read_csv(body)
    assert df.iloc[0]["name"] == "国立病院"
    assert df.iloc[1]["name"] == "🏥 BigHospital"


def test_parse_csv_with_mixed_dtypes_no_warning():
    body = "id,value\n1,100\n2,abc\n3,200\n".encode("utf-8")
    df = parsing.read_csv(body)
    assert len(df) == 3


def test_shape_wide_skips_observations_with_nan_value(grim_csv):
    """When age_standardised_rate is blank in some rows, those observations
    should be omitted, not returned with value=None."""
    cd = curated.get("GRIM_DEATHS")
    df = parsing.read_csv(grim_csv)
    df = parsing.drop_blank_rows(
        df, [c.source_column for c in cd.columns.values() if c.role == "dimension"],
    )
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"cause_of_death": "Diabetes"},
        measures="age_standardised_rate_per_100000",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    # Every returned observation must have a non-null value
    for r in resp.records:
        assert r.value is not None


def test_response_csv_handles_empty_result(grim_csv):
    cd = curated.get("GRIM_DEATHS")
    df = parsing.read_csv(grim_csv)
    df = parsing.drop_blank_rows(
        df, [c.source_column for c in cd.columns.values() if c.role == "dimension"],
    )
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"cause_of_death": "DEFINITELY NOT REAL"},
        measures="deaths",
        start_period=None, end_period=None, fmt="csv", user_query={},
    )
    assert resp.row_count == 0
    assert resp.csv == ""


def test_response_csv_format_is_valid_csv(grim_csv):
    """CSV output must be parseable back by pandas."""
    cd = curated.get("GRIM_DEATHS")
    df = parsing.read_csv(grim_csv)
    df = parsing.drop_blank_rows(
        df, [c.source_column for c in cd.columns.values() if c.role == "dimension"],
    )
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"cause_of_death": "Diabetes", "sex": "persons"},
        measures="deaths",
        start_period=None, end_period=None, fmt="csv", user_query={},
    )
    roundtrip = pd.read_csv(BytesIO(resp.csv.encode("utf-8")))
    assert "value" in roundtrip.columns
    assert "measure" in roundtrip.columns
    assert roundtrip["measure"].iloc[0] == "deaths"
    assert (roundtrip["value"] > 0).all()


def test_dtype_coercion_handles_nan_id_column(pubhosp_csv):
    """ID columns with mixed NaN/numeric values should coerce cleanly without trailing '.0'."""
    cd = curated.get("PUBLIC_HOSPITALS")
    df = parsing.read_csv(pubhosp_csv)
    df = parsing.drop_blank_rows(
        df, [c.source_column for c in cd.columns.values() if c.role == "dimension"],
    )
    resp = shaping.build_response(
        cd=cd, df=df, filters={"state": "NSW"},
        measures="number_of_available_beds",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    for r in resp.records:
        for k, v in r.dimensions.items():
            if v is None:
                continue
            # No trailing '.0' on any ID-typed column
            if k in ("lhn_id", "establishment_id", "medicare_provider_no"):
                assert "." not in str(v), f"{k} should be clean, got {v!r}"


def test_text_column_strips_whitespace(youthj_csv):
    """Source data may have trailing whitespace; the response must show clean values."""
    cd = curated.get("YOUTH_JUSTICE_DETENTION")
    df = parsing.read_csv(youthj_csv)
    df = parsing.drop_blank_rows(
        df, [c.source_column for c in cd.columns.values() if c.role == "dimension"],
    )
    resp = shaping.build_response(
        cd=cd, df=df, filters={"state": "nsw", "legal_status": "Total", "sex": "Total"},
        measures="avg_nightly_pop",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    for r in resp.records:
        state = r.dimensions.get("state")
        if state is not None:
            assert state == state.strip(), f"state has whitespace: {state!r}"
