"""Shaping contract tests against real AIHW sample files."""
from __future__ import annotations

import json as _json
from io import BytesIO

import pandas as pd
import pytest

from aihw_mcp import curated, parsing, shaping


def _parse_csv(cd, body):
    df = parsing.read_csv(body)
    dim_cols = [c.source_column for c in cd.columns.values() if c.role == "dimension"]
    return parsing.drop_blank_rows(df, dim_cols)


def _myhospitals_df(records: list[dict]):
    """Build a parsed MyHospitals DataFrame from raw API record dicts."""
    return parsing.read_myhospitals_json(
        _json.dumps({"records": records}).encode("utf-8")
    )


# Minimal MyHospitals records exercising both unit variants per dataset.
_ED_RECORDS = [
    {  # count row — unit 'patients'
        "reporting_start_date": "2023-07-01",
        "reporting_end_date": "2024-06-30",
        "reporting_unit_code": "H0021",
        "reporting_unit_name": "Royal Prince Alfred Hospital",
        "reporting_unit_type_code": "H",
        "mapped_state": "NSW",
        "reported_measure_category_name": "Resuscitation",
        "measure_code": "MYH0010",
        "measure_name": "Number of patients presenting",
        "peer_group_name": "Principal referral hospitals",
        "value": 1234.0,
        "units_name": "patients",
    },
    {  # percentage row — unit 'percent'
        "reporting_start_date": "2023-07-01",
        "reporting_end_date": "2024-06-30",
        "reporting_unit_code": "H0021",
        "reporting_unit_name": "Royal Prince Alfred Hospital",
        "reporting_unit_type_code": "H",
        "mapped_state": "NSW",
        "reported_measure_category_name": "Resuscitation",
        "measure_code": "MYH0011",
        "measure_name": "Percentage treated within recommended time",
        "peer_group_name": "Principal referral hospitals",
        "value": 87.5,
        "units_name": "percent",
    },
]

_ES_RECORDS = [
    {  # median-days row — unit 'days', with a peer_value
        "reporting_start_date": "2023-07-01",
        "reporting_end_date": "2024-06-30",
        "reporting_unit_code": "H0014",
        "reporting_unit_name": "The Children's Hospital at Westmead",
        "reporting_unit_type_code": "H",
        "mapped_state": "NSW",
        "reported_measure_category_name": "Cardio-thoracic surgery",
        "measure_code": "MYH0009",
        "measure_name": "Median waiting time for elective surgery",
        "peer_group_name": "Children's hospitals",
        "value": 36.0,
        "peer_value": 35.0,
        "units_display": "days",
    },
    {  # percentage row — unit '%'
        "reporting_start_date": "2023-07-01",
        "reporting_end_date": "2024-06-30",
        "reporting_unit_code": "H0014",
        "reporting_unit_name": "The Children's Hospital at Westmead",
        "reporting_unit_type_code": "H",
        "mapped_state": "NSW",
        "reported_measure_category_name": "Cardio-thoracic surgery",
        "measure_code": "MYH0007",
        "measure_name": "Percentage who waited longer than 365 days",
        "peer_group_name": "Children's hospitals",
        "value": 2.1,
        "peer_value": 1.8,
        "units_display": "%",
    },
]


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
            filters={"sex": user_sex, "cause_of_death": "All causes combined (ICD-10 all)"},
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
        filters={"category": "state", "sex": "Persons"},
        measures="deaths",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    assert resp.row_count > 0
    for r in resp.records:
        assert r.dimensions["category"] == "State and territory"
        assert r.dimensions["sex"] == "Persons"


def test_mort_multiple_measures(mort_csv):
    cd = curated.get("MORT_GEOGRAPHY")
    df = _parse_csv(cd, mort_csv)
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"category": "state", "sex": "Persons"},
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


def test_pubhosp_latest_does_not_collapse_to_one_row(pubhosp_csv):
    """Regression (v0.4.21 BUG 1): latest() passes last_n=1 into build_response.
    PUBLIC_HOSPITALS has no period_dimension at all (a register, not a time
    series), so grouping the old way — by measure ONLY, with no null-period
    carve-out — collapsed the whole ~700-hospital register to essentially one
    arbitrary row. The fix must skip the trim entirely when every record has
    a null period, returning the WHOLE matching set instead."""
    cd = curated.get("PUBLIC_HOSPITALS")
    df = _parse_csv(cd, pubhosp_csv)
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={},
        measures="number_of_available_beds",
        start_period=None, end_period=None, fmt="records", user_query={},
        last_n=1,
    )
    assert resp.row_count > 1, (
        f"latest() collapsed PUBLIC_HOSPITALS to {resp.row_count} row(s); "
        "expected the full register (no period to trim on)."
    )
    hospital_names = {r.dimensions.get("hospital_name") for r in resp.records}
    assert len(hospital_names) > 1, "expected multiple distinct hospitals in the response"


def test_grim_latest_keeps_all_entities_at_latest_year(grim_csv):
    """Regression (v0.4.21 BUG 1): dimensional datasets like GRIM_DEATHS also
    collapsed under the old grouping. Filtering to one cause_of_death (but no
    sex filter) leaves 3 rows per year (Males/Females/Persons) under the same
    "deaths" measure — a per-measure-only trim would arbitrarily keep just one
    of those three. latest() (last_n=1) must keep ALL entities at the most
    recent period, not an arbitrary single row."""
    cd = curated.get("GRIM_DEATHS")
    df = _parse_csv(cd, grim_csv)
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={"cause_of_death": "All causes combined (ICD-10 all)"},
        measures="deaths",
        start_period=None, end_period=None, fmt="records", user_query={},
        last_n=1,
    )
    assert resp.row_count == 3, (
        f"expected 3 rows (one per sex) at the latest year, got {resp.row_count}"
    )
    years = {r.dimensions["year"] for r in resp.records}
    assert years == {"2023"}, f"expected only the most recent year, got {years}"
    sexes = {r.dimensions["sex"] for r in resp.records}
    assert sexes == {"Males", "Females", "Persons"}


def test_latest_limit_caps_response_and_sets_truncated_at(pubhosp_csv):
    """Regression (v0.4.21 BUG 2): latest() had no `limit`/cap for register-shaped
    datasets, and truncated_at was declared in models.py but never assigned
    anywhere. build_response must slice to `limit` and set truncated_at to the
    ORIGINAL (pre-truncation) row count."""
    cd = curated.get("PUBLIC_HOSPITALS")
    df = _parse_csv(cd, pubhosp_csv)

    full = shaping.build_response(
        cd=cd, df=df,
        filters={},
        measures="number_of_available_beds",
        start_period=None, end_period=None, fmt="records", user_query={},
        last_n=1,
    )
    original_count = full.row_count
    assert original_count > 10, "fixture too small to exercise the cap meaningfully"
    assert full.truncated_at is None

    capped = shaping.build_response(
        cd=cd, df=df,
        filters={},
        measures="number_of_available_beds",
        start_period=None, end_period=None, fmt="records", user_query={},
        last_n=1, limit=10,
    )
    assert len(capped.records) == 10
    assert capped.row_count == 10
    assert capped.truncated_at == original_count, (
        f"truncated_at should be the ORIGINAL row count ({original_count}), "
        f"got {capped.truncated_at!r}"
    )


# ---------------------------------------------------------------------------
# BUG (live audit 2026-08-16): the `limit` cap sliced records[:limit] on a
# list in ASCENDING period order (oldest -> newest, ../CLAUDE.md invariant
# #5), so whenever the pre-cap record count still exceeded `limit` without
# already being narrowed to a single period -- e.g. `last_n` unset, or a
# broad/unfiltered query -- the surviving window was the EARLIEST period
# instead of the latest. Portfolio contract: a caller asking for latest-N
# without a start period must get the MOST RECENT rows.
# ---------------------------------------------------------------------------


def test_limit_cap_keeps_latest_period_not_earliest(acim_csv):
    """CANCER_INCIDENCE_MORTALITY, unfiltered, spans every year in the
    fixture (2005-2011). Capping the (untrimmed) record set at `limit` must
    keep the LATEST year's rows, not whichever year happens to sort first --
    and ascending order must hold within the surviving window, so
    records[-1] is the newest."""
    cd = curated.get("CANCER_INCIDENCE_MORTALITY")
    df = _parse_csv(cd, acim_csv)
    resp = shaping.build_response(
        cd=cd, df=df,
        filters={},  # broad -- no headline_slice narrowing here
        measures=None,
        start_period=None, end_period=None, fmt="records", user_query={},
        last_n=None,  # isolate the cap itself from the last_n trim
        limit=20,
    )
    assert resp.truncated_at is not None, "fixture too small to exercise the cap"
    all_years = sorted(df["Year"].astype(str).unique())
    latest_year = all_years[-1]
    years_in_response = {r.dimensions.get("year") for r in resp.records}
    assert latest_year in years_in_response, (
        f"limit cap kept only {sorted(years_in_response)}; the latest "
        f"available year {latest_year!r} was truncated away instead of "
        "the earliest year"
    )
    assert resp.records[-1].dimensions.get("year") == latest_year, (
        "ascending order must hold within the capped window -- "
        f"records[-1] should be {latest_year!r}, got "
        f"{resp.records[-1].dimensions.get('year')!r}"
    )


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
    assert resp.source == "Australian Institute of Health and Welfare (AIHW), via data.gov.au"
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


# ─── unit contract: every non-null value carries a non-null unit ───────────
# Portfolio binding rule (../CLAUDE.md): every numeric Observation.value MUST
# carry a non-null `unit` string in native source scale. ED_WAITING_TIMES and
# ELECTIVE_SURGERY_WAITING_TIMES have row-varying units (patients vs percent;
# days vs %) sitting in the `units` dimension, not in a static measure unit —
# these tests lock in that shape_wide falls back to the per-row unit.


def test_ed_waiting_times_every_value_carries_unit():
    cd = curated.get("ED_WAITING_TIMES")
    df = _myhospitals_df(_ED_RECORDS)
    resp = shaping.build_response(
        cd=cd, df=df, filters={}, measures="value",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    assert resp.row_count == 2
    for r in resp.records:
        assert r.value is not None
        assert r.unit is not None, f"value {r.value} missing unit"
    # Per-row unit, native scale, no conversion.
    units_by_value = {r.value: r.unit for r in resp.records}
    assert units_by_value[1234.0] == "patients"
    assert units_by_value[87.5] == "percent"


def test_elective_surgery_every_value_carries_unit():
    cd = curated.get("ELECTIVE_SURGERY_WAITING_TIMES")
    df = _myhospitals_df(_ES_RECORDS)
    resp = shaping.build_response(
        cd=cd, df=df, filters={}, measures=None,  # value + peer_value
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    # 2 rows × {value, peer_value} = 4 observations.
    assert resp.row_count == 4
    for r in resp.records:
        assert r.value is not None
        assert r.unit is not None, f"{r.measure}={r.value} missing unit"
    # Both value and peer_value on a row inherit that row's unit.
    days_units = {r.unit for r in resp.records if r.value in (36.0, 35.0)}
    pct_units = {r.unit for r in resp.records if r.value in (2.1, 1.8)}
    assert days_units == {"days"}
    assert pct_units == {"%"}


def test_unit_dimension_blank_falls_back_to_sentinel():
    """If the unit-bearing dimension cell is blank, the value still carries a
    non-null unit (the documented sentinel), never None."""
    cd = curated.get("ED_WAITING_TIMES")
    rec = dict(_ED_RECORDS[0])
    rec["units_name"] = None  # source row with no declared unit
    df = _myhospitals_df([rec])
    resp = shaping.build_response(
        cd=cd, df=df, filters={}, measures="value",
        start_period=None, end_period=None, fmt="records", user_query={},
    )
    assert resp.row_count == 1
    assert resp.records[0].unit == shaping._UNKNOWN_UNIT
    assert resp.records[0].unit is not None


def test_unit_contract_holds_for_all_curated_datasets(
    grim_csv, mort_csv, acim_csv, hexp_csv, youthj_csv, pubhosp_csv,
):
    """General unit-contract scan: for EVERY curated dataset, every Observation
    with a non-null value must carry a non-null unit. CSV/XLSX datasets are
    driven from their fixtures; the two MyHospitals datasets from synthetic
    API records. This is the canary that would have caught the ED/ELECTIVE
    unit=None violation."""
    csv_cases = {
        "GRIM_DEATHS":                (grim_csv, "deaths"),
        "MORT_GEOGRAPHY":             (mort_csv, "deaths"),
        "CANCER_INCIDENCE_MORTALITY": (acim_csv, None),
        "HEALTH_EXPENDITURE":         (hexp_csv, None),
        "YOUTH_JUSTICE_DETENTION":    (youthj_csv, None),
        "PUBLIC_HOSPITALS":           (pubhosp_csv, None),
    }
    json_cases = {
        "ED_WAITING_TIMES":              _ED_RECORDS,
        "ELECTIVE_SURGERY_WAITING_TIMES": _ES_RECORDS,
    }

    checked_ids: set[str] = set()
    total_obs = 0

    for ds_id, (body, measures) in csv_cases.items():
        cd = curated.get(ds_id)
        df = _parse_csv(cd, body)
        resp = shaping.build_response(
            cd=cd, df=df, filters={}, measures=measures,
            start_period=None, end_period=None, fmt="records", user_query={},
        )
        for r in resp.records:
            if r.value is not None:
                assert r.unit is not None, (
                    f"{ds_id}: measure {r.measure!r} value {r.value} has unit=None — "
                    "unit-contract violation"
                )
                total_obs += 1
        checked_ids.add(ds_id)

    for ds_id, records in json_cases.items():
        cd = curated.get(ds_id)
        df = _myhospitals_df(records)
        resp = shaping.build_response(
            cd=cd, df=df, filters={}, measures=None,
            start_period=None, end_period=None, fmt="records", user_query={},
        )
        for r in resp.records:
            if r.value is not None:
                assert r.unit is not None, (
                    f"{ds_id}: measure {r.measure!r} value {r.value} has unit=None — "
                    "unit-contract violation"
                )
                total_obs += 1
        checked_ids.add(ds_id)

    # Guard: ensure the scan actually covered every curated dataset, so a new
    # dataset added without a fixture here fails loudly rather than silently
    # escaping the unit-contract check.
    assert checked_ids == set(curated.list_ids()), (
        "Unit-contract scan does not cover all curated datasets. "
        f"Uncovered: {sorted(set(curated.list_ids()) - checked_ids)}"
    )
    assert total_obs > 0
