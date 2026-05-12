"""Parsing contract tests against real AIHW sample files."""
from __future__ import annotations

from io import BytesIO

import openpyxl
import pytest

from aihw_mcp.parsing import (
    ParseError,
    _normalize_header,
    drop_blank_rows,
    read_csv,
    read_xlsx,
)


def _build_synthetic_xlsx(sheet_name: str, rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_read_csv_grim(grim_csv):
    df = read_csv(grim_csv)
    assert "grim" in df.columns
    assert "cause_of_death" in df.columns
    assert "year" in df.columns
    assert "sex" in df.columns
    assert "deaths" in df.columns
    assert len(df) > 100


def test_read_csv_mort(mort_csv):
    df = read_csv(mort_csv)
    for col in ("mort", "category", "geography", "YEAR", "SEX", "deaths", "median_age"):
        assert col in df.columns, f"missing {col}"
    assert len(df) > 100


def test_read_csv_acim(acim_csv):
    df = read_csv(acim_csv)
    assert "Year" in df.columns
    assert "Cancer_Type" in df.columns
    assert "Age_85+" in df.columns
    assert len(df) > 50


def test_read_csv_hexp(hexp_csv):
    df = read_csv(hexp_csv)
    for col in ("financial_year", "state", "area_of_expenditure", "real_expenditure_millions"):
        assert col in df.columns
    assert len(df) > 100


def test_read_csv_youthj(youthj_csv):
    df = read_csv(youthj_csv)
    for col in ("agegrp", "indig_status", "legal_status", "sex", "state", "avg_nightly_pop"):
        assert col in df.columns
    assert len(df) > 50


def test_read_csv_pubhosp(pubhosp_csv):
    df = read_csv(pubhosp_csv)
    for col in ("State", "Hospital name", "Establishment ID", "Number of available beds"):
        assert col in df.columns
    assert len(df) > 100


def test_read_csv_empty_body_raises():
    with pytest.raises(ParseError, match="empty"):
        read_csv(b"")


def test_read_csv_bom_stripped():
    body = "﻿state,postcode\nNSW,2000\n".encode("utf-8")
    df = read_csv(body)
    assert list(df.columns) == ["state", "postcode"]


def test_read_csv_unicode_data():
    body = "name,note\n株式会社東京,JP\n🏥 Hospital,AU\n".encode("utf-8")
    df = read_csv(body)
    assert df.iloc[0]["name"] == "株式会社東京"
    assert df.iloc[1]["name"] == "🏥 Hospital"


def test_read_xlsx_minimal_works():
    body = _build_synthetic_xlsx("data", [
        ["state", "cause", "deaths"],
        ["NSW", "Diabetes", 100],
        ["VIC", "Diabetes", 80],
    ])
    df = read_xlsx(body, sheet="data", header_row=1)
    assert list(df.columns) == ["state", "cause", "deaths"]
    assert len(df) == 2


def test_read_xlsx_bad_sheet_raises():
    body = _build_synthetic_xlsx("data", [["a"], [1]])
    with pytest.raises(ParseError, match="not found"):
        read_xlsx(body, sheet="NotASheet", header_row=1)


def test_read_xlsx_bad_header_row_raises():
    body = _build_synthetic_xlsx("data", [["a"], [1]])
    with pytest.raises(ParseError, match="1-indexed"):
        read_xlsx(body, sheet="data", header_row=0)


def test_read_xlsx_empty_body_raises():
    with pytest.raises(ParseError, match="empty"):
        read_xlsx(b"", sheet="x", header_row=1)


def test_read_xlsx_corrupt_zip_raises_parse_error():
    """A truncated/corrupt XLSX body must raise ParseError, not BadZipFile."""
    with pytest.raises(ParseError):
        read_xlsx(b"\x50\x4b\x03\x04garbage", sheet="x", header_row=1)


def test_read_xlsx_complete_garbage_raises_parse_error():
    with pytest.raises(ParseError):
        read_xlsx(b"this is not an xlsx file" * 100, sheet="x", header_row=1)


def test_normalize_header_strips_padding_around_newline():
    assert _normalize_header("Deaths  \n  no.") == "Deaths\nno."
    assert _normalize_header("Deaths\n  no.") == "Deaths\nno."
    assert _normalize_header("Deaths  \nno.") == "Deaths\nno."


def test_normalize_header_preserves_internal_spaces():
    assert _normalize_header("Other deaths\n$") == "Other deaths\n$"


def test_normalize_header_handles_multiple_newlines():
    assert _normalize_header("a\n\nb") == "a\n\nb"  # double newline preserved


def test_normalize_header_handles_only_whitespace():
    assert _normalize_header("   ") == ""
    assert _normalize_header("\n") == "\n"


def test_normalize_header_passthrough_non_string():
    import datetime
    dt = datetime.datetime(2024, 1, 1)
    assert _normalize_header(dt) == dt


def test_drop_blank_rows(grim_csv):
    df = read_csv(grim_csv)
    before = len(df)
    cleaned = drop_blank_rows(df, ["cause_of_death", "year"])
    assert len(cleaned) <= before


def test_drop_blank_rows_no_matching_keys_passthrough(grim_csv):
    df = read_csv(grim_csv)
    out = drop_blank_rows(df, ["nonexistent_col"])
    assert len(out) == len(df)


def test_drop_blank_rows_removes_only_all_nan_rows():
    import pandas as pd
    df = pd.DataFrame({
        "a": ["x", None, "z", None],
        "b": ["1", None, None, "2"],
    })
    out = drop_blank_rows(df, ["a", "b"])
    # Row 1 (None, None) dropped. Row 2 (z, None) kept. Row 3 (None, 2) kept.
    assert len(out) == 3
