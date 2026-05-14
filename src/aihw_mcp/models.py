"""Pydantic v2 response models for aihw-mcp.

Mirrors the response shape used by abs-mcp, rba-mcp, and ato-mcp so a
downstream agent that calls multiple Australian government MCPs gets a
uniform envelope. AIHW-specific differences:
- attribution names AIHW and the data.gov.au Creative Commons licence
- DataResponse.source defaults to "Australian Institute of Health and Welfare"
- DataResponse.aihw_url points back at the data.gov.au dataset page
- Observation.dimensions is open-ended (cause_of_death, year, sex, age_group, etc.)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


_AIHW_ATTRIBUTION = (
    "Data sourced from the Australian Institute of Health and Welfare (AIHW) "
    "via data.gov.au. Licensed under Creative Commons Attribution 3.0 Australia "
    "(CC BY 3.0 AU). https://creativecommons.org/licenses/by/3.0/au/"
)


class DatasetSummary(BaseModel):
    """Search-result shape: one row per known AIHW dataset."""
    id: str                                  # aihw-mcp curated ID, e.g. "GRIM_DEATHS"
    name: str                                # human name
    description: str | None = None
    update_frequency: str | None = None      # "annual" / "weekly" / "irregular"
    is_curated: bool = False


class ColumnDetail(BaseModel):
    """One queryable column in a curated table."""
    key: str                                 # plain-English alias (e.g. "deaths")
    source_column: str                       # the actual CSV/XLSX header text
    description: str | None = None
    unit: str | None = None                  # "Deaths", "Persons", "AUD millions", "Rate per 100,000"
    role: str = "measure"                    # "dimension" | "measure" | "id"


class DatasetDetail(BaseModel):
    """describe_dataset shape."""
    id: str
    name: str
    description: str
    is_curated: bool
    update_frequency: str | None = None
    period_coverage: str | None = None       # e.g. "1907 to 2023"
    dimensions: list[ColumnDetail] = Field(default_factory=list)
    measures: list[ColumnDetail] = Field(default_factory=list)
    source_url: str                          # data.gov.au dataset page
    download_url: str | None = None          # the actual CSV/XLSX resource URL


class Observation(BaseModel):
    """One row of returned data."""
    period: str | None = None                # ISO date or year ("2023")
    value: float | None = None               # the measure value
    measure: str | None = None               # which measure this value is for
    dimensions: dict[str, Any] = Field(default_factory=dict)  # cause, sex, age_group, etc.
    unit: str | None = None


class DataResponse(BaseModel):
    """get_data / latest shape — uniform across all curated datasets.

    `records` carries either:
      - list of `Observation` (default "records" format), or
      - list of dicts shaped {measure, unit, observations: [{period, value, dimensions}, ...]}
        (the "series" format — one group per measure).
    We use `Any` here instead of a union so Pydantic does not silently coerce
    the series dicts into Observations (every Observation field is optional,
    so the dicts would otherwise match and `observations` would be dropped).
    """
    dataset_id: str
    dataset_name: str
    query: dict[str, Any] = Field(default_factory=dict)
    period: dict[str, str | None] = Field(default_factory=lambda: {"start": None, "end": None})
    unit: str | None = None
    row_count: int = 0
    records: list[Any] = Field(default_factory=list)
    csv: str | None = None
    source: str = "Australian Institute of Health and Welfare"
    attribution: str = _AIHW_ATTRIBUTION
    retrieved_at: datetime
    aihw_url: str
    # Echoed in every response so testers can verify which wheel served the call;
    # uvx caches per-version and stale caches cause real "is this fixed?" confusion.
    server_version: str = Field(default_factory=lambda: _get_server_version())
    # Set when data.gov.au was unreachable and we served a cached payload
    # past its normal TTL. Agents should surface `stale=True` to end users
    # (e.g. "AIHW reported 503; showing data from 12 minutes ago").
    stale: bool = False
    stale_reason: str | None = None
    # Set when `latest()` truncated a large response to a limit. Original
    # row count goes here so agents can detect + surface the cap.
    truncated_at: int | None = None


def _get_server_version() -> str:
    try:
        from importlib.metadata import version
        return version("aihw-mcp")
    except Exception:
        return "0.0.0+unknown"
