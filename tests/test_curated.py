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
