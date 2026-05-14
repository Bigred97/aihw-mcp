"""Hand-curated metadata for the top-N AIHW datasets.

Each YAML under `data/curated/` describes one queryable table:
- where to fetch it (data.gov.au resource URL)
- how to parse it (sheet name, header row, layout)
- which columns are dimensions (filterable) vs measures (returned values)
- plain-English aliases for AIHW's source column names
- which filter values are accepted, what they mean
- search keywords folded into the fuzzy search haystack

The translator turns a user's plain-English `filters={...}` and
`measures=[...]` request into instructions the shaping layer can apply
to the parsed DataFrame.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Literal

import yaml
from aus_identity import (
    is_valid_postcode,
    normalize_state,
    postcode_to_state,
)


# Dim names whose values are state/region references. When `translate_filter_value`
# encounters one of these, the user input is run through aus_identity first so
# "NSW", "nsw", "New South Wales", "AU-NSW", "Tassie", and 4-digit postcodes
# all resolve to the curated key.
_STATE_LIKE_DIM_NAMES = frozenset({"state", "region", "state_territory"})


Layout = Literal["wide", "transposed"]


@dataclass(frozen=True)
class CuratedColumn:
    """One column in the source table that's exposed to users."""
    key: str                                 # plain-English alias (e.g. "deaths")
    source_column: str                       # exact CSV/XLSX column header
    description: str | None = None
    unit: str | None = None                  # "Deaths", "Persons", "Rate per 100,000", "AUD millions"
    role: str = "measure"                    # "dimension" | "measure" | "id"
    dtype: str | None = None                 # optional pandas coercion: "int", "float", "string"


@dataclass(frozen=True)
class CuratedDimensionValues:
    """Allowed values for a dimension, plus their canonical labels.

    Used for state/territory codes, sex enums, cause-of-death codes, etc.
    `None` means free-form (e.g. age_group, year) — anything goes.
    """
    values: dict[str, str] | None = None     # alias -> source value


@dataclass(frozen=True)
class CuratedDataset:
    """One curated dataset (a single queryable view)."""
    id: str
    name: str
    description: str
    source_url: str                          # the data.gov.au dataset page
    download_url: str                        # direct CSV/XLSX resource URL (fallback if discovery fails)
    format: Literal["xlsx", "csv"]
    sheet: str | None                        # XLSX sheet name; None for CSV
    header_row: int                          # 1-indexed
    data_start_row: int | None               # optional override (defaults to header_row + 1)
    layout: Layout                           # "wide" = entities-as-rows; "transposed" = years-as-cols
    period_coverage: str | None              # e.g. "1907 to 2023"
    update_frequency: str | None             # "annual", "weekly", "irregular"
    cache_kind: str                          # "data" | "register"
    columns: dict[str, CuratedColumn]        # keyed by alias
    dimension_values: dict[str, CuratedDimensionValues]  # keyed by alias (column key)
    search_keywords: tuple[str, ...] = ()
    # For transposed tables: which column header carries the metric label,
    # and what unit column to read alongside (typically column B).
    metric_label_column: str | None = None
    unit_column: str | None = None
    # Optional auto-discovery spec: when present, the server resolves the
    # current download URL via CKAN at fetch time so new yearly releases
    # land without a YAML edit. See discovery.py.
    discovery: dict | None = None
    # Optional period dimension key — names a column the shaping layer should
    # treat as the dataset's time axis. When set:
    #   - start_period / end_period on get_data filters rows by this column
    #     (using the lenient _normalize_period parser shared with transposed
    #     tables).
    #   - latest() sorts by this column ascending before trimming, so
    #     `last_n=1` returns the most-recent period rather than whatever
    #     happens to be last in source order.
    # Leave unset for register-style datasets without a meaningful time axis
    # (e.g. PUBLIC_HOSPITALS, where every row is one current establishment).
    period_dimension: str | None = None


_REGISTRY: dict[str, CuratedDataset] | None = None


def _yaml_dir() -> Path:
    try:
        ref = resources.files("aihw_mcp").joinpath("data/curated")
        if ref.is_dir():
            return Path(str(ref))
    except (ModuleNotFoundError, AttributeError):
        pass
    here = Path(__file__).resolve().parent / "data" / "curated"
    if here.is_dir():
        return here
    raise FileNotFoundError("Could not locate aihw_mcp/data/curated/")


def _parse_column(key: str, raw: dict) -> CuratedColumn:
    if not isinstance(raw, dict):
        raise ValueError(f"Column {key!r} must be a mapping, got {type(raw).__name__}")
    if "source_column" not in raw:
        raise ValueError(f"Column {key!r} missing required field 'source_column'")
    return CuratedColumn(
        key=key,
        source_column=str(raw["source_column"]),
        description=raw.get("description"),
        unit=raw.get("unit"),
        role=str(raw.get("role", "measure")),
        dtype=raw.get("dtype"),
    )


def _parse_dimension_values(raw: dict | None) -> CuratedDimensionValues:
    if raw is None:
        return CuratedDimensionValues(values=None)
    if not isinstance(raw, dict):
        raise ValueError(f"dimension_values entry must be a mapping, got {type(raw).__name__}")
    return CuratedDimensionValues(values={str(k): str(v) for k, v in raw.items()})


def _load_one(path: Path) -> CuratedDataset:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name}: top-level must be a mapping")

    columns: dict[str, CuratedColumn] = {}
    for key, col_raw in (raw.get("columns") or {}).items():
        columns[key] = _parse_column(key, col_raw)

    dim_values: dict[str, CuratedDimensionValues] = {}
    for key, val_raw in (raw.get("dimension_values") or {}).items():
        dim_values[key] = _parse_dimension_values(val_raw)

    fmt = str(raw.get("format", "xlsx")).lower()
    if fmt not in ("xlsx", "csv"):
        raise ValueError(f"{path.name}: format must be 'xlsx' or 'csv', got {fmt!r}")

    layout = str(raw.get("layout", "wide")).lower()
    if layout not in ("wide", "transposed"):
        raise ValueError(f"{path.name}: layout must be 'wide' or 'transposed', got {layout!r}")

    discovery_raw = raw.get("discovery")
    if discovery_raw is not None and not isinstance(discovery_raw, dict):
        raise ValueError(f"{path.name}: discovery must be a mapping if provided")

    period_dim_raw = raw.get("period_dimension")
    if period_dim_raw is not None and not isinstance(period_dim_raw, str):
        raise ValueError(f"{path.name}: period_dimension must be a string if provided")

    return CuratedDataset(
        id=str(raw["id"]),
        name=str(raw["name"]),
        description=str(raw.get("description", "")),
        source_url=str(raw["source_url"]),
        download_url=str(raw["download_url"]),
        format=fmt,  # type: ignore[arg-type]
        sheet=raw.get("sheet"),
        header_row=int(raw.get("header_row", 1)),
        data_start_row=raw.get("data_start_row"),
        layout=layout,  # type: ignore[arg-type]
        period_coverage=raw.get("period_coverage"),
        update_frequency=raw.get("update_frequency"),
        cache_kind=str(raw.get("cache_kind", "data")),
        columns=columns,
        dimension_values=dim_values,
        search_keywords=tuple(raw.get("search_keywords") or ()),
        metric_label_column=raw.get("metric_label_column"),
        unit_column=raw.get("unit_column"),
        discovery=discovery_raw,
        period_dimension=period_dim_raw,
    )


def _load_all() -> dict[str, CuratedDataset]:
    out: dict[str, CuratedDataset] = {}
    for path in sorted(_yaml_dir().glob("*.yaml")):
        cd = _load_one(path)
        if cd.id in out:
            raise ValueError(f"Duplicate curated id {cd.id!r} (from {path.name})")
        out[cd.id] = cd
    return out


def get(dataset_id: str) -> CuratedDataset | None:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _load_all()
    return _REGISTRY.get(dataset_id.upper())


def list_ids() -> list[str]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _load_all()
    return sorted(_REGISTRY.keys())


def list_all() -> list[CuratedDataset]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _load_all()
    return [_REGISTRY[k] for k in sorted(_REGISTRY.keys())]


def reset_registry() -> None:
    """For tests."""
    global _REGISTRY
    _REGISTRY = None


def dimension_columns(cd: CuratedDataset) -> list[CuratedColumn]:
    """All columns flagged role == 'dimension'."""
    return [c for c in cd.columns.values() if c.role == "dimension"]


def measure_columns(cd: CuratedDataset) -> list[CuratedColumn]:
    """All columns flagged role == 'measure'."""
    return [c for c in cd.columns.values() if c.role == "measure"]


def id_columns(cd: CuratedDataset) -> list[CuratedColumn]:
    """All columns flagged role == 'id'."""
    return [c for c in cd.columns.values() if c.role == "id"]


def _aus_identity_pass_through(user_value: str) -> str | None:
    """Normalise a state-shaped value when there's no curated enum.

    Returns the canonical short code ("NSW") or `None` if the input isn't
    a state reference. Used for free-form state-shaped dims so postcode
    routing + alias normalisation still kicks in.
    """
    s = user_value.strip()
    if not s:
        return None
    if s.isdigit() and is_valid_postcode(s):
        try:
            return postcode_to_state(s)
        except ValueError:
            return None
    try:
        return normalize_state(s)
    except ValueError:
        return None


def _normalise_state_like(
    user_value: str, alias_to_canonical: dict[str, str]
) -> str | None:
    """Resolve a state-shaped user value to the source-column value.

    Returns the source-column value from `alias_to_canonical.values()` if
    the input maps to a known state via `aus_identity`, else `None`.
    """
    s = user_value.strip()
    if not s:
        return None
    if s.isdigit() and is_valid_postcode(s):
        try:
            code = postcode_to_state(s)
        except ValueError:
            return None
    else:
        try:
            code = normalize_state(s)
        except ValueError:
            return None
    # Direct key match (uppercase / canonical).
    if code in alias_to_canonical:
        return alias_to_canonical[code]
    # Lowercase key match (some YAMLs only enumerate lowercase aliases).
    lower = code.lower()
    if lower in alias_to_canonical:
        return alias_to_canonical[lower]
    # Match by canonical value (in case source-column form is the short code).
    for v in alias_to_canonical.values():
        if v.upper() == code:
            return v
    return None


def translate_filter_value(
    cd: CuratedDataset, dim_key: str, user_value: str
) -> str:
    """Translate a user-supplied dimension value to the value stored in the source column.

    If the dim has an enumerated `dimension_values` map, the user can pass either
    a plain-English alias (e.g. 'nsw') or the raw source value (e.g. 'NSW') —
    both resolve. If the dim is free-form (no enum), the raw value passes through.
    On miss, the error message includes a fuzzy "did you mean" hint when a
    close match exists (typo tolerance for high-traffic filters like state/sex).

    State-shaped filters (`state`, `region`, `state_territory`) accept the
    full cross-source menu via `aus_identity` — short codes, full names,
    ISO 3166-2, aliases, and 4-digit postcodes all route through to the
    curated alias / canonical value pair.
    """
    dv = cd.dimension_values.get(dim_key)
    if dv is None or dv.values is None:
        # Free-form state-shaped dims (rare) still benefit from postcode
        # routing: a user passing "2000" gets back "NSW" automatically.
        if dim_key in _STATE_LIKE_DIM_NAMES:
            normalised = _aus_identity_pass_through(user_value)
            if normalised is not None:
                return normalised
        return user_value
    if user_value in dv.values:
        return dv.values[user_value]
    # Maybe the user already passed the canonical value.
    if user_value in dv.values.values():
        return user_value
    # Cross-source normalisation via aus_identity (state names, postcodes).
    if dim_key in _STATE_LIKE_DIM_NAMES:
        normalised = _normalise_state_like(user_value, dv.values)
        if normalised is not None:
            return normalised
    valid = sorted(dv.values.keys())
    suggestion = _suggest(user_value, valid)
    suggest_msg = f"Did you mean {suggestion!r}? " if suggestion else ""
    shown = valid[:10]
    rest = f" ({len(valid)} total)" if len(valid) > len(shown) else ""
    raise ValueError(
        f"Unknown value {user_value!r} for filter {dim_key!r} on dataset {cd.id!r}. "
        f"{suggest_msg}Try one of: {', '.join(shown)}{rest}. "
        f"Try describe_dataset({cd.id!r}) for the full list."
    )


def _suggest(query: str, candidates: list[str], cutoff: int = 70) -> str | None:
    """Return the best fuzzy match for `query` in `candidates`, or None.

    Uses RapidFuzz WRatio (already a project dep). The 70 cutoff is tight enough
    to avoid spurious suggestions ('nsw' vs 'act') but loose enough to catch
    real typos ('femal' → 'female').
    """
    if not query or not candidates:
        return None
    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        return None
    match = process.extractOne(
        query, candidates, scorer=fuzz.WRatio, score_cutoff=cutoff,
    )
    return match[0] if match else None


def transposed_measure_aliases(cd: CuratedDataset) -> list[str]:
    """For a transposed-layout dataset, return the list of alias keys that
    label rows of the metric_label_column. These act as the dataset's
    'available measures' since transposed tables don't have measure columns.
    """
    if cd.layout != "transposed" or cd.metric_label_column is None:
        return []
    label_col = cd.metric_label_column
    for c in cd.columns.values():
        if c.source_column == label_col:
            dv = cd.dimension_values.get(c.key)
            if dv and dv.values is not None:
                return list(dv.values.keys())
            break
    return []


def resolve_measure_keys(
    cd: CuratedDataset, requested: str | list[str] | None
) -> list[str]:
    """Translate a user's measures= request into a list of measure keys.

    - None  → all measure columns (subject to a soft default cap at the
      caller's discretion).
    - "foo" → ["foo"] (validated)
    - ["foo", "bar"] → ["foo", "bar"] (validated)
    Raw source column names also pass through if they match a measure column.

    For transposed-layout datasets without explicit role=measure columns,
    the metric_label_column's dimension_values aliases double as the
    available measure keys.
    """
    measure_keys = [c.key for c in measure_columns(cd)]
    if not measure_keys:
        measure_keys = transposed_measure_aliases(cd)
    if requested is None:
        return measure_keys
    items: list[str]
    if isinstance(requested, str):
        items = [requested]
    elif isinstance(requested, list):
        if not requested:
            raise ValueError(
                f"measures filter is an empty list. "
                "Pass at least one measure, or omit `measures` to return all."
            )
        items = [str(x) for x in requested]
    else:
        raise ValueError(
            f"measures must be a string or list of strings, got {type(requested).__name__}."
        )

    source_to_key = {c.source_column: c.key for c in cd.columns.values() if c.role == "measure"}
    valid_keys = set(measure_keys)
    out: list[str] = []
    for v in items:
        v_str = v.strip()
        if not v_str:
            valid_sorted = sorted(valid_keys)
            shown = valid_sorted[:10]
            rest = f" ({len(valid_sorted)} total)" if len(valid_sorted) > len(shown) else ""
            raise ValueError(
                f"Empty measure key for dataset {cd.id!r}. "
                f"Try one of: {', '.join(shown)}{rest}. "
                f"Try describe_dataset({cd.id!r}) for the full list."
            )
        if v_str in valid_keys:
            out.append(v_str)
        elif v_str in source_to_key:
            out.append(source_to_key[v_str])
        else:
            valid_sorted = sorted(valid_keys)
            shown = valid_sorted[:10]
            rest = f" ({len(valid_sorted)} total)" if len(valid_sorted) > len(shown) else ""
            valid_hint = (
                f"{', '.join(shown)}{rest}"
                if valid_keys
                else "(none — dataset has no curated measures)"
            )
            suggestion = _suggest(v_str, valid_sorted) if valid_keys else None
            suggest_msg = f"Did you mean {suggestion!r}? " if suggestion else ""
            raise ValueError(
                f"Unknown measure {v!r} for dataset {cd.id!r}. "
                f"{suggest_msg}Try one of: {valid_hint}. "
                f"Try describe_dataset({cd.id!r}) for the full list."
            )
    # Dedupe while preserving order.
    seen: set[str] = set()
    return [k for k in out if not (k in seen or seen.add(k))]
