"""Fuzzy search and listing across the curated dataset registry.

Unlike abs-mcp (which calls SDMX dataflow listings) or rba-mcp (which has a
static F-table registry), aihw-mcp ships with N curated datasets hand-picked
for sellable value. The catalog surface is intentionally small in v0.1 — we
expose only the curated set. Future versions can grow this to discover
arbitrary AIHW datasets via CKAN.
"""
from __future__ import annotations

from rapidfuzz import fuzz, process

from . import curated as curated_mod
from .models import DatasetSummary


def list_summaries() -> list[DatasetSummary]:
    """All curated datasets as DatasetSummary objects."""
    out: list[DatasetSummary] = []
    for cd in curated_mod.list_all():
        out.append(
            DatasetSummary(
                id=cd.id,
                name=cd.name,
                description=cd.description,
                update_frequency=cd.update_frequency,
                is_curated=True,
            )
        )
    return out


def search(query: str, limit: int = 10) -> list[DatasetSummary]:
    """Fuzzy-search curated datasets — two-pool ranker.

    High-signal pool (id + name + curated.search_keywords) scored with
    token_set_ratio. Description pool capped via WRatio + DESCRIPTION_CAP.
    Prevents the WRatio-collapse-to-57 problem where unrelated datasets
    score identically because every description shares boilerplate
    ('Australia', 'annual', etc.).
    """
    if not query.strip():
        raise ValueError(
            "query is required. Try 'mortality', 'cancer', 'hospital', "
            "'expenditure', 'youth justice', or any other AIHW topic."
        )
    summaries = list_summaries()
    if not summaries:
        return []
    DESCRIPTION_CAP = 30
    keyword_lookup = {cd.id: " ".join(cd.search_keywords) for cd in curated_mod.list_all()}
    query_lc = query.lower()
    scored: list[tuple[float, float, int]] = []
    for i, s in enumerate(summaries):
        high_str = f"{s.id} {s.name} {keyword_lookup.get(s.id, '')}".lower()
        desc_str = (s.description or "").lower()
        high = fuzz.token_set_ratio(query_lc, high_str)
        desc_raw = fuzz.WRatio(query_lc, desc_str) if desc_str else 0
        desc = min(desc_raw, DESCRIPTION_CAP)
        final = min(high + desc * 0.5, 100.0)
        scored.append((final, high, i))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    return [
        summaries[idx].model_copy(update={"relevance": round(float(final), 1)})
        for final, _high, idx in scored[:limit]
    ]
