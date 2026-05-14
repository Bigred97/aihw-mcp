"""Server-level validation guards on each MCP tool.

Mirrors abs-mcp / rba-mcp / ato-mcp `test_server_validation` — confirms each
tool rejects nonsense input cleanly (with a ValueError carrying a 'Try X'
hint) rather than crashing partway through with an obscure error.
"""
from __future__ import annotations

import pytest

from aihw_mcp import server


@pytest.mark.asyncio
async def test_search_datasets_empty_query():
    with pytest.raises(ValueError, match="query is required"):
        await server.search_datasets("")


@pytest.mark.asyncio
async def test_search_datasets_whitespace_query():
    with pytest.raises(ValueError, match="query is required"):
        await server.search_datasets("   ")


@pytest.mark.asyncio
async def test_search_datasets_non_string_query():
    with pytest.raises(ValueError, match="must be a string"):
        await server.search_datasets(123)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_search_datasets_limit_too_small():
    with pytest.raises(ValueError, match=">= 1"):
        await server.search_datasets("mortality", limit=0)


@pytest.mark.asyncio
async def test_search_datasets_limit_is_bool():
    with pytest.raises(ValueError, match="positive integer"):
        await server.search_datasets("mortality", limit=True)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_describe_dataset_unknown_id():
    with pytest.raises(ValueError, match="not a curated"):
        await server.describe_dataset("DOES_NOT_EXIST")


@pytest.mark.asyncio
async def test_describe_dataset_bad_chars():
    with pytest.raises(ValueError, match="invalid characters"):
        await server.describe_dataset("../etc/passwd")


@pytest.mark.asyncio
async def test_describe_dataset_empty_id():
    with pytest.raises(ValueError, match="empty"):
        await server.describe_dataset("")


@pytest.mark.asyncio
async def test_get_data_unknown_id():
    with pytest.raises(ValueError, match="not a curated"):
        await server.get_data("DOES_NOT_EXIST")


@pytest.mark.asyncio
async def test_get_data_filters_must_be_dict():
    with pytest.raises(ValueError, match="filters must be a dict"):
        await server.get_data("GRIM_DEATHS", filters=["sex", "Persons"])  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_data_bad_period_format():
    with pytest.raises(ValueError, match="invalid format"):
        await server.get_data("GRIM_DEATHS", start_period="?garbage?")


@pytest.mark.asyncio
async def test_get_data_period_swap():
    with pytest.raises(ValueError, match="before start_period"):
        await server.get_data("GRIM_DEATHS", start_period="2024", end_period="2020")


@pytest.mark.asyncio
async def test_get_data_empty_measures_list():
    with pytest.raises(ValueError, match="empty list"):
        await server.get_data("GRIM_DEATHS", measures=[])


@pytest.mark.asyncio
async def test_get_data_bad_format():
    with pytest.raises(ValueError, match="Unknown format"):
        await server.get_data("GRIM_DEATHS", format="parquet")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_list_curated_returns_sorted_ids():
    ids = server.list_curated()
    assert ids == sorted(ids)
    assert "GRIM_DEATHS" in ids
    assert "MORT_GEOGRAPHY" in ids
    assert len(ids) == 6


# ---------------------------------------------------------------------------
# v0.1.3 error-message sweep: rejection messages must suggest the correction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_dataset_id_suggests_close_match():
    """A typo in dataset_id surfaces a 'Did you mean' hint pointing at the
    closest curated ID (e.g. GRIM_DEATH → GRIM_DEATHS)."""
    with pytest.raises(ValueError) as exc_info:
        await server.describe_dataset("GRIM_DEATH")
    msg = str(exc_info.value)
    assert "Did you mean 'GRIM_DEATHS'" in msg
    # Also includes the corrective pointer + a worked list
    assert "list_curated()" in msg
    assert "GRIM_DEATHS" in msg


@pytest.mark.asyncio
async def test_unknown_dataset_id_lists_valid_options():
    """Even when no close fuzzy match exists, the message enumerates valid IDs
    and points at list_curated()."""
    with pytest.raises(ValueError) as exc_info:
        await server.describe_dataset("WHO_KNOWS_WHAT_THIS_IS")
    msg = str(exc_info.value)
    # At least the canonical dataset IDs we ship in v0.1
    assert "GRIM_DEATHS" in msg
    assert "list_curated()" in msg or "search_datasets" in msg


@pytest.mark.asyncio
async def test_bad_period_format_includes_worked_example():
    """An invalid period must show a worked example, not just describe the format."""
    with pytest.raises(ValueError) as exc_info:
        await server.get_data("GRIM_DEATHS", start_period="?garbage?")
    msg = str(exc_info.value)
    assert "YYYY" in msg
    # Worked example with a real value (concrete, not just a format string)
    assert "'2020'" in msg or "2020" in msg


@pytest.mark.asyncio
async def test_bad_format_did_you_mean():
    """Typoed format name surfaces a 'Did you mean' suggestion."""
    with pytest.raises(ValueError) as exc_info:
        await server.get_data("GRIM_DEATHS", format="recordz")  # typo of 'records'
    msg = str(exc_info.value)
    assert "Did you mean 'records'" in msg
    assert "records" in msg and "series" in msg and "csv" in msg
