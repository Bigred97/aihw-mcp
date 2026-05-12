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
