"""Curated YAML loader contract tests.

These hit the actual YAMLs shipped with the package — if anyone breaks one,
this suite catches it before the wheel ships. Every curated dataset must
declare a non-empty list of dimensions AND a non-empty list of measures
OR (for transposed tables) at least a `metric_label_column`.
"""
from __future__ import annotations

import pytest

from aihw_mcp import curated


def test_at_least_one_curated_dataset_loads():
    ids = curated.list_ids()
    assert len(ids) >= 5, f"expected at least 5 curated datasets, got {ids}"


def test_every_curated_dataset_has_required_fields():
    for cd in curated.list_all():
        assert cd.id, f"missing id in {cd}"
        assert cd.name, f"missing name on {cd.id}"
        assert cd.description, f"missing description on {cd.id}"
        assert cd.source_url.startswith("https://"), f"bad source_url on {cd.id}: {cd.source_url}"
        assert cd.download_url.startswith("https://"), f"bad download_url on {cd.id}: {cd.download_url}"
        assert cd.format in ("xlsx", "csv"), f"bad format on {cd.id}: {cd.format}"
        if cd.format == "xlsx":
            assert cd.sheet, f"xlsx dataset {cd.id} missing sheet name"
        assert cd.header_row >= 1, f"bad header_row on {cd.id}"
        assert cd.layout in ("wide", "transposed"), f"bad layout on {cd.id}"
        # Every dataset must expose some measures — either as role=measure
        # columns (wide layout) or as dimension_values on the metric_label
        # column (transposed layout). We check both paths.
        roles = {c.role for c in cd.columns.values()}
        if cd.layout == "transposed":
            assert cd.metric_label_column, f"transposed {cd.id} needs metric_label_column"
            aliases = curated.transposed_measure_aliases(cd)
            assert aliases, (
                f"transposed {cd.id} declares no measures — needs dimension_values "
                f"on the metric_label column"
            )
        else:
            assert "measure" in roles, f"wide {cd.id} declares no measure columns"


def test_no_duplicate_curated_ids():
    ids = curated.list_ids()
    assert len(ids) == len(set(ids)), f"duplicate IDs in curated registry: {ids}"


def test_column_keys_are_unique_within_dataset():
    for cd in curated.list_all():
        keys = [c.key for c in cd.columns.values()]
        assert len(keys) == len(set(keys)), f"duplicate column keys in {cd.id}: {keys}"


def test_dimension_values_reference_real_columns():
    """Every dimension_values entry must reference a dimension column key."""
    for cd in curated.list_all():
        col_keys = {c.key for c in cd.columns.values()}
        for dim_key in cd.dimension_values:
            assert dim_key in col_keys, (
                f"{cd.id}: dimension_values entry {dim_key!r} doesn't match any column"
            )


def test_translate_filter_value_for_known_alias():
    cd = curated.get("GRIM_DEATHS")
    assert cd is not None
    out = curated.translate_filter_value(cd, "sex", "female")
    assert out == "Females"


def test_translate_filter_value_passthrough_canonical():
    cd = curated.get("GRIM_DEATHS")
    assert cd is not None
    out = curated.translate_filter_value(cd, "sex", "Persons")
    assert out == "Persons"


def test_translate_filter_value_unknown_raises():
    cd = curated.get("GRIM_DEATHS")
    assert cd is not None
    with pytest.raises(ValueError, match="Unknown value"):
        curated.translate_filter_value(cd, "sex", "wakanda")


# ---- aus-identity cross-source normalisation on state filter ----


def test_state_filter_accepts_full_name():
    """`state='New South Wales'` resolves to canonical 'NSW'."""
    cd = curated.get("HEALTH_EXPENDITURE")
    assert cd is not None
    assert curated.translate_filter_value(cd, "state", "New South Wales") == "NSW"


def test_state_filter_accepts_lowercase_full_name():
    """`state='queensland'` (lowercase) resolves to 'QLD'."""
    cd = curated.get("HEALTH_EXPENDITURE")
    assert cd is not None
    assert curated.translate_filter_value(cd, "state", "queensland") == "QLD"


def test_state_filter_accepts_iso_3166_form():
    """`state='AU-VIC'` resolves to 'VIC'."""
    cd = curated.get("HEALTH_EXPENDITURE")
    assert cd is not None
    assert curated.translate_filter_value(cd, "state", "AU-VIC") == "VIC"


def test_state_filter_accepts_common_alias():
    """`state='Tassie'` resolves to 'TAS'."""
    cd = curated.get("HEALTH_EXPENDITURE")
    assert cd is not None
    assert curated.translate_filter_value(cd, "state", "Tassie") == "TAS"


def test_state_filter_accepts_postcode_routing():
    """`state='2000'` (Sydney CBD) routes to 'NSW'."""
    cd = curated.get("HEALTH_EXPENDITURE")
    assert cd is not None
    assert curated.translate_filter_value(cd, "state", "2000") == "NSW"


def test_state_filter_postcode_in_act_routes_correctly():
    """`state='2600'` (Parliament House) resolves to 'ACT', not 'NSW'."""
    cd = curated.get("HEALTH_EXPENDITURE")
    assert cd is not None
    assert curated.translate_filter_value(cd, "state", "2600") == "ACT"


def test_state_filter_public_hospitals_accepts_full_name():
    """Verify aus_identity works on PUBLIC_HOSPITALS too — different YAML same dim."""
    cd = curated.get("PUBLIC_HOSPITALS")
    assert cd is not None
    assert curated.translate_filter_value(cd, "state", "Victoria") == "VIC"


def test_resolve_measure_keys_none_returns_all():
    cd = curated.get("GRIM_DEATHS")
    assert cd is not None
    keys = curated.resolve_measure_keys(cd, None)
    assert "deaths" in keys
    assert "crude_rate_per_100000" in keys
    assert "age_standardised_rate_per_100000" in keys


def test_resolve_measure_keys_single():
    cd = curated.get("GRIM_DEATHS")
    assert cd is not None
    assert curated.resolve_measure_keys(cd, "deaths") == ["deaths"]


def test_resolve_measure_keys_list_dedupes():
    cd = curated.get("MORT_GEOGRAPHY")
    assert cd is not None
    out = curated.resolve_measure_keys(cd, ["deaths", "population", "deaths"])
    assert out == ["deaths", "population"]


def test_resolve_measure_keys_empty_list_raises():
    cd = curated.get("GRIM_DEATHS")
    assert cd is not None
    with pytest.raises(ValueError, match="empty list"):
        curated.resolve_measure_keys(cd, [])


def test_resolve_measure_keys_unknown_raises():
    cd = curated.get("GRIM_DEATHS")
    assert cd is not None
    with pytest.raises(ValueError, match="Unknown measure"):
        curated.resolve_measure_keys(cd, "alien_metric")


def test_expected_curated_ids_present():
    """The six v0.1 datasets must all load."""
    expected = {
        "GRIM_DEATHS",
        "MORT_GEOGRAPHY",
        "CANCER_INCIDENCE_MORTALITY",
        "HEALTH_EXPENDITURE",
        "YOUTH_JUSTICE_DETENTION",
        "PUBLIC_HOSPITALS",
    }
    ids = set(curated.list_ids())
    missing = expected - ids
    assert not missing, f"expected curated datasets missing from registry: {missing}"


def test_discovery_block_shape():
    """If a YAML declares discovery, package_id is required and host pin will accept the URL."""
    for cd in curated.list_all():
        if not cd.discovery:
            continue
        # Must declare either package_id or package_id_pattern
        has_pkg = bool(cd.discovery.get("package_id") or cd.discovery.get("package_id_pattern"))
        assert has_pkg, f"{cd.id}: discovery needs package_id or package_id_pattern"
        # Must declare either resource_name or resource_name_pattern
        has_res = bool(cd.discovery.get("resource_name") or cd.discovery.get("resource_name_pattern"))
        assert has_res, f"{cd.id}: discovery needs resource_name or resource_name_pattern"


# ---- v0.4.6: portfolio dim-key convention + headline_slice ----


def test_all_dim_keys_are_lowercase_snake_case():
    """Portfolio convention — every curated column key must be lowercase
    snake_case so response.dimensions[...] reads the same across all sister
    MCPs. Pre-0.4.6 MORT_GEOGRAPHY shipped uppercase 'YEAR' / 'SEX' which
    surfaced as uppercase keys in the response dict and broke uniformity.
    """
    for cd in curated.list_all():
        for col in cd.columns.values():
            assert col.key == col.key.lower(), (
                f"{cd.id}: column key {col.key!r} must be lowercase "
                "(portfolio convention; source CSV header stays in source_column)"
            )


def test_headline_slice_loads_when_declared():
    """Each declared headline_slice round-trips into the curated dataclass."""
    expected_keys = {
        "HEALTH_EXPENDITURE": {"state", "area_of_expenditure",
                               "broad_source_of_funding",
                               "detailed_source_of_funding"},
        "MORT_GEOGRAPHY": {"category", "geography", "sex"},
        "GRIM_DEATHS": {"cause_of_death", "sex", "age_group"},
        "CANCER_INCIDENCE_MORTALITY": {"cancer_type", "sex", "type"},
        "YOUTH_JUSTICE_DETENTION": {"state", "sex", "legal_status",
                                    "indigenous_status", "age_group"},
    }
    for ds_id, expected in expected_keys.items():
        cd = curated.get(ds_id)
        assert cd is not None
        assert cd.headline_slice is not None, f"{ds_id} missing headline_slice"
        assert set(cd.headline_slice) == expected, (
            f"{ds_id} headline_slice keys: {set(cd.headline_slice)} != {expected}"
        )


def test_headline_slice_unset_on_register_dataset():
    """PUBLIC_HOSPITALS is a register without a meaningful single-row headline."""
    cd = curated.get("PUBLIC_HOSPITALS")
    assert cd is not None
    assert cd.headline_slice is None


def test_headline_slice_keys_reference_real_columns():
    """Every headline_slice key must be a curated column on the same dataset."""
    for cd in curated.list_all():
        if cd.headline_slice is None:
            continue
        col_keys = {c.key for c in cd.columns.values()}
        for slice_key in cd.headline_slice:
            assert slice_key in col_keys, (
                f"{cd.id}: headline_slice key {slice_key!r} not in columns "
                f"({sorted(col_keys)})"
            )


def test_headline_slice_invalid_key_raises_at_load(tmp_path, monkeypatch):
    """A YAML whose headline_slice references an undefined column must fail
    at load — silent failures here would manifest as 'unknown filter' errors
    deep in a user's get_data call, far from the broken config.
    """
    import yaml as _yaml
    from aihw_mcp.curated import _load_one
    bogus = {
        "id": "BOGUS",
        "name": "Bogus",
        "description": "test",
        "source_url": "https://example.com/",
        "download_url": "https://example.com/x.csv",
        "format": "csv",
        "layout": "wide",
        "header_row": 1,
        "columns": {
            "year": {
                "source_column": "year",
                "role": "dimension",
                "dtype": "string",
            },
            "value": {
                "source_column": "value",
                "role": "measure",
                "dtype": "float",
            },
        },
        "headline_slice": {"not_a_real_column": "x"},
    }
    p = tmp_path / "BOGUS.yaml"
    p.write_text(_yaml.safe_dump(bogus), encoding="utf-8")
    with pytest.raises(ValueError, match="headline_slice references unknown column"):
        _load_one(p)
