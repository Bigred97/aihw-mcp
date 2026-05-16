"""Shaping contract tests against real AIHW sample files."""
from __future__ import annotations

from io import BytesIO

import pandas as pd
import pytest

from aihw_mcp import curated, parsing, shaping


def _parse_csv(cd, body):
    df = parsing.read_csv(body)
    dim_cols = [c.source_column for c in cd.columns.values() if c.role == "dimension"]
    return parsing.drop_blank_rows(df, dim_cols)


def test_grim_unfiltered_returns_observations(grim_csv):
    cd = curated.get("GRIM_DEATHS")
    df = _parse_csv(cd, grim_csv)
    resp = shaping.build_response(
        cd=cd, df=df, filters={}, measures="deaths",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    assert resp.row_count > 100
    assert resp.unit == "Deaths"
    assert resp.dataset_id == "GRIM_DEATHS"
    assert all(r.measure == "deaths" for r in resp.records)


def test_grim_filter_by_cause_and_sex(grim_csv):
    cd = curated.get("GRIM_DEATHS")
    df = _parse_csv(cd, grim_csv)
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"cause_of_death": "Diabetes", "sex": "persons"},
        measures="deaths",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    assert resp.row_count > 10
    for r in resp.records:
        assert r.dimensions["cause_of_death"] == "Diabetes"
        assert r.dimensions["sex"] == "Persons"


def test_grim_canonical_sex_alias(grim_csv):
    """Lowercase aliases should resolve to canonical AIHW labels."""
    cd = curated.get("GRIM_DEATHS")
    df = _parse_csv(cd, grim_csv)
    for user_sex, canonical in (("female", "Females"), ("male", "Males"), ("persons", "Persons")):
        resp = shaping.build_response(
            cd=cd, df=df,
            filters={"sex": user_sex, "cause_of_death": "All causes combined"},
            measures="deaths",
            start_period=None, end_period=None, fmt="records", user_query={},
        )
        assert resp.row_count > 0
        assert all(r.dimensions["sex"] == canonical for r in resp.records)


def test_mort_state_filter(mort_csv):
    cd = curated.get("MORT_GEOGRAPHY")
    df = _parse_csv(cd, mort_csv)
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"category": "state", "SEX": "Persons"},
        measures="deaths",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    assert resp.row_count > 0
    for r in resp.records:
        assert r.dimensions["category"] == "State and territory"
        assert r.dimensions["SEX"] == "Persons"


def test_mort_multiple_measures(mort_csv):
    cd = curated.get("MORT_GEOGRAPHY")
    df = _parse_csv(cd, mort_csv)
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"category": "state", "SEX": "Persons"},
        measures=["deaths", "median_age", "potentially_avoidable_deaths"],
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    measures = {r.measure for r in resp.records}
    assert measures == {"deaths", "median_age", "potentially_avoidable_deaths"}


def test_cancer_filter_by_type_and_sex(acim_csv):
    cd = curated.get("CANCER_INCIDENCE_MORTALITY")
    df = _parse_csv(cd, acim_csv)
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"cancer_type": "Breast cancer", "sex": "female", "type": "Incidence"},
        measures="age_50_to_54",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    assert resp.row_count > 0
    for r in resp.records:
        assert r.dimensions["cancer_type"] == "Breast cancer"
        assert r.dimensions["sex"] == "Female"
        assert r.dimensions["type"] == "Incidence"


def test_cancer_age_85_plus_column_works(acim_csv):
    """Column name with '+' must round-trip through alias renaming."""
    cd = curated.get("CANCER_INCIDENCE_MORTALITY")
    df = _parse_csv(cd, acim_csv)
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"cancer_type": "Breast cancer", "sex": "female"},
        measures="age_85_plus",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    assert resp.row_count > 0
    assert all(r.measure == "age_85_plus" for r in resp.records)


def test_hexp_state_alias_filter(hexp_csv):
    cd = curated.get("HEALTH_EXPENDITURE")
    df = _parse_csv(cd, hexp_csv)
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"state": "nsw"},
        measures="real_expenditure_millions",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    assert resp.row_count > 0
    for r in resp.records:
        assert r.dimensions["state"] == "NSW"


def test_youthj_state_mixed_case(youthj_csv):
    """Youth justice uses mixed-case state codes (Vic, Qld). Alias should resolve."""
    cd = curated.get("YOUTH_JUSTICE_DETENTION")
    df = _parse_csv(cd, youthj_csv)
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"state": "vic", "legal_status": "Total", "sex": "Total"},
        measures="avg_nightly_pop",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    assert resp.row_count > 0
    for r in resp.records:
        assert r.dimensions["state"] == "Vic"


def test_pubhosp_state_filter(pubhosp_csv):
    cd = curated.get("PUBLIC_HOSPITALS")
    df = _parse_csv(cd, pubhosp_csv)
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"state": "NSW"},
        measures="number_of_available_beds",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    assert resp.row_count > 0
    for r in resp.records:
        assert r.dimensions["state"] == "NSW"


def test_pubhosp_id_columns_are_clean_strings(pubhosp_csv):
    """Numeric ID columns should not have trailing '.0' from float coercion."""
    cd = curated.get("PUBLIC_HOSPITALS")
    df = _parse_csv(cd, pubhosp_csv)
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"state": "NSW"},
        measures="number_of_available_beds",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    # lhn_id should be clean integer-string (e.g. "103", not "103.0")
    for r in resp.records:
        lhn = r.dimensions.get("lhn_id")
        if lhn is not None:
            assert "." not in lhn, f"lhn_id should be clean, got {lhn!r}"


def test_grim_csv_format(grim_csv):
    cd = curated.get("GRIM_DEATHS")
    df = _parse_csv(cd, grim_csv)
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"cause_of_death": "Diabetes", "sex": "persons"},
        measures="deaths",
        start_period=None, end_period=None, fmt="csv", user_query={},
    )
    assert resp.csv is not None
    lines = resp.csv.strip().split("\n")
    assert len(lines) >= 2
    assert "deaths" in resp.csv


def test_grim_series_format(grim_csv):
    cd = curated.get("GRIM_DEATHS")
    df = _parse_csv(cd, grim_csv)
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"cause_of_death": "Diabetes", "sex": "persons"},
        measures=["deaths", "crude_rate_per_100000"],
        start_period=None, end_period=None, fmt="series", user_query={},
    )
    assert len(resp.records) == 2
    measure_names = {g["measure"] for g in resp.records}
    assert measure_names == {"deaths", "crude_rate_per_100000"}


def test_unknown_filter_raises(grim_csv):
    cd = curated.get("GRIM_DEATHS")
    df = _parse_csv(cd, grim_csv)
    with pytest.raises(ValueError, match="Unknown filter"):
        shaping.build_response(
            cd=cd, df=df, filters={"not_a_dim": "x"}, measures="deaths",
            start_period=None, end_period=None, fmt="records", user_query={},
        )


def test_empty_list_filter_raises(grim_csv):
    cd = curated.get("GRIM_DEATHS")
    df = _parse_csv(cd, grim_csv)
    with pytest.raises(ValueError, match="empty list"):
        shaping.build_response(
            cd=cd, df=df, filters={"cause_of_death": []}, measures="deaths",
            start_period=None, end_period=None, fmt="records", user_query={},
        )


def test_response_carries_metadata(grim_csv):
    cd = curated.get("GRIM_DEATHS")
    df = _parse_csv(cd, grim_csv)
    resp = shaping.build_response(
        cd=cd, df=df, filters={}, measures="deaths",
        start_period=None, end_period=None, fmt="records", user_query={"x": 1},
    )
    assert resp.dataset_id == "GRIM_DEATHS"
    assert resp.dataset_name
    assert resp.source == "Australian Institute of Health and Welfare"
    assert "Creative Commons" in resp.attribution
    assert resp.aihw_url == cd.source_url
    assert resp.query == {"x": 1}
    assert resp.server_version


def test_data_response_has_source_url_canonical_field(grim_csv):
    """Wave-2 interop: both source_url and aihw_url are populated and equal."""
    cd = curated.get("GRIM_DEATHS")
    df = _parse_csv(cd, grim_csv)
    resp = shaping.build_response(
        cd=cd, df=df, filters={}, measures="deaths",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    assert resp.source_url is not None
    assert resp.source_url == resp.aihw_url
    assert resp.source_url == cd.source_url


def test_data_response_source_url_present_on_csv_format(grim_csv):
    """source_url is populated regardless of output format."""
    cd = curated.get("GRIM_DEATHS")
    df = _parse_csv(cd, grim_csv)
    resp = shaping.build_response(
        cd=cd, df=df, filters={}, measures="deaths",
        start_period=None, end_period=None, fmt="csv", user_query={},
    )
    assert resp.source_url == resp.aihw_url
    assert resp.source_url.startswith("https://")


def test_shape_wide_skips_nan_value_observations(grim_csv):
    """When age_standardised_rate is blank (e.g. Total age band), that
    measure observation should be omitted, not returned with value=None."""
    cd = curated.get("GRIM_DEATHS")
    df = _parse_csv(cd, grim_csv)
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"cause_of_death": "Diabetes", "sex": "persons"},
        measures="age_standardised_rate_per_100000",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    # All returned observations must have non-null values
    for r in resp.records:
        assert r.value is not None


def test_csv_handles_empty_result(grim_csv):
    cd = curated.get("GRIM_DEATHS")
    df = _parse_csv(cd, grim_csv)
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"cause_of_death": "Definitely Not A Real Cause"},
        measures="deaths",
        start_period=None, end_period=None, fmt="csv", user_query={},
    )
    assert resp.row_count == 0
    assert resp.csv == ""


def test_csv_format_is_valid_csv(grim_csv):
    """CSV output must be parseable back by pandas."""
    cd = curated.get("GRIM_DEATHS")
    df = _parse_csv(cd, grim_csv)
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


def test_curated_yaml_canonical_columns_match_real_files(
    grim_csv, mort_csv, acim_csv, hexp_csv, youthj_csv, pubhosp_csv,
):
    """Every curated source_column must be in the parsed file headers.
    This is the canary that catches schema drift in AIHW releases.
    """
    fixtures = {
        "GRIM_DEATHS":                grim_csv,
        "MORT_GEOGRAPHY":             mort_csv,
        "CANCER_INCIDENCE_MORTALITY": acim_csv,
        "HEALTH_EXPENDITURE":         hexp_csv,
        "YOUTH_JUSTICE_DETENTION":    youthj_csv,
        "PUBLIC_HOSPITALS":           pubhosp_csv,
    }
    for dataset_id, body in fixtures.items():
        cd = curated.get(dataset_id)
        df = parsing.read_csv(body)
        missing = [
            c.source_column for c in cd.columns.values()
            if c.source_column not in df.columns
        ]
        assert not missing, (
            f"{dataset_id}: source columns missing in real data: {missing}\n"
            f"actual first 10: {list(df.columns[:10])}"
        )


def test_grim_multi_value_filter(grim_csv):
    """List filter values mean OR across values."""
    cd = curated.get("GRIM_DEATHS")
    df = _parse_csv(cd, grim_csv)
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"cause_of_death": ["Diabetes", "All neoplasms"], "sex": "persons"},
        measures="deaths",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    causes = {r.dimensions["cause_of_death"] for r in resp.records}
    assert causes == {"Diabetes", "All neoplasms"}


def test_unknown_dimension_value_lists_alternatives(grim_csv):
    """Bad value for an enumerated dimension should list valid options."""
    cd = curated.get("GRIM_DEATHS")
    df = _parse_csv(cd, grim_csv)
    with pytest.raises(ValueError, match="Unknown value") as exc_info:
        shaping.build_response(
            cd=cd, df=df, filters={"sex": "narnia"}, measures="deaths",
            start_period=None, end_period=None, fmt="records", user_query={},
        )
    msg = str(exc_info.value)
    assert "female" in msg or "Females" in msg


# ─── Item 5: long-text-field truncation ────────────────────────────────
# Defensive cap. Real AIHW data fields are <100 chars in every observed
# dataset (longest measured: ~70 chars on PUBLIC_HOSPITALS peer-group
# names), but if AIHW ever introduces a long descriptor (e.g. extended
# cancer-type definitions, hospital service descriptions) the cap keeps
# the response payload tight by default — and we expose the original
# value via shaping.truncate_text() / shaping._TEXT_FIELD_CAP for tests.


def test_long_text_field_is_truncated_by_default(grim_csv):
    """A synthetic >500-char cause_of_death gets truncated in the response."""
    cd = curated.get("GRIM_DEATHS")
    df = _parse_csv(cd, grim_csv)
    # Inject a long descriptor into a copy of the df
    long_desc = "X" * 800
    df = df.copy()
    # Replace the first row's cause_of_death
    df.loc[df.index[0], "cause_of_death"] = long_desc
    resp = shaping.build_response(
        cd=cd, df=df, filters={}, measures="deaths",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    # Find a record whose cause_of_death was that long value
    long_records = [
        r for r in resp.records
        if r.dimensions.get("cause_of_death", "").startswith("X")
    ]
    assert long_records, "expected at least one record carrying the long value"
    for r in long_records:
        val = r.dimensions["cause_of_death"]
        # Cap is configurable but must be well under the 800-char source
        assert len(val) <= shaping._TEXT_FIELD_CAP + 80, (
            f"value not truncated: len={len(val)}"
        )
        # Marker tells the agent more text exists and how to retrieve it
        assert "more chars" in val
        assert "include_full_text" in val


def test_short_text_field_is_not_truncated(grim_csv):
    """Real AIHW values (all <100 chars) must pass through unchanged."""
    cd = curated.get("GRIM_DEATHS")
    df = _parse_csv(cd, grim_csv)
    resp = shaping.build_response(
        cd=cd, df=df, filters={"cause_of_death": "Diabetes"}, measures="deaths",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    assert resp.row_count > 0
    for r in resp.records:
        cause = r.dimensions.get("cause_of_death", "")
        # No truncation marker on values that fit
        assert "more chars" not in cause
        assert "include_full_text" not in cause


def test_truncate_text_helper_threshold():
    """The helper is configurable but uses _TEXT_FIELD_CAP by default."""
    short = "x" * 100
    long = "x" * 800
    assert shaping.truncate_text(short) == short
    out = shaping.truncate_text(long)
    assert out != long
    assert "more chars" in out
    assert "include_full_text" in out
    # Default cap exists and is sensible (between 100 and a few thousand)
    assert 100 < shaping._TEXT_FIELD_CAP < 5000


def test_truncate_text_handles_non_string():
    """None / int / NaN pass through unchanged — only str values are capped."""
    assert shaping.truncate_text(None) is None
    assert shaping.truncate_text(42) == 42
    assert shaping.truncate_text("") == ""
