"""On-disk Parquet cache for parsed DataFrames.

Mirrors `wgea-mcp/src/wgea_mcp/parquet_cache.py`. The in-process LRU
(`_df_cache` in `server.py`) handles warm queries in ~50ms but it's
empty on cold restart — first call after a worker bounce pays the full
pandas/openpyxl parse cost (~6s for the larger AIHW XLSX files like
`CANCER_INCIDENCE_MORTALITY`). The Parquet cache below persists the
post-parse DataFrame to disk so cold-restart loads complete in ~0.5-1s
instead.

Location: defaults to `~/.aihw-mcp/parquet-cache/`, overridable via
`AIHW_MCP_PARQUET_CACHE_DIR` (used by tests + the Fly deploy that
mounts `/data/parquet-cache`).

TTL: 24h, matching the SQLite byte-cache TTL for `kind="data"` on AIHW
(faster refresh than WGEA since AIHW publishes updates more often).

Self-heal: a corrupted Parquet file is unlinked and the call falls
through to a fresh parse, matching the SQLite cache's corruption
recovery pattern.
"""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any

import pandas as pd

# 24h, matching cache.py's TTL for data-kind payloads.
DEFAULT_TTL_SECONDS = 24 * 60 * 60

_ENV_VAR = "AIHW_MCP_PARQUET_CACHE_DIR"
_DEFAULT_DIR = Path.home() / ".aihw-mcp" / "parquet-cache"


def cache_dir() -> Path:
    """Resolve the cache directory, creating it if needed."""
    override = os.environ.get(_ENV_VAR)
    path = Path(override) if override else _DEFAULT_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _key_to_filename(key: tuple[Any, ...]) -> str:
    """Hash a cache key tuple to a stable Parquet filename."""
    payload = repr(key).encode("utf-8")
    return hashlib.sha256(payload).hexdigest() + ".parquet"


def read_if_fresh(
    key: tuple[Any, ...], *, ttl_seconds: int = DEFAULT_TTL_SECONDS
) -> pd.DataFrame | None:
    """Return the cached DataFrame if the Parquet file exists + is fresh."""
    path = cache_dir() / _key_to_filename(key)
    if not path.is_file():
        return None
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return None
    if age > ttl_seconds:
        return None
    try:
        return pd.read_parquet(path)
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        return None


def write(key: tuple[Any, ...], df: pd.DataFrame) -> None:
    """Persist a parsed DataFrame to the cache (best-effort, atomic)."""
    target = cache_dir() / _key_to_filename(key)
    tmp = target.with_suffix(".parquet.tmp")
    try:
        df.to_parquet(tmp, engine="pyarrow", compression="snappy", index=False)
        tmp.replace(target)
    except Exception:
        try:
            if tmp.is_file():
                tmp.unlink()
        except OSError:
            pass


def reset_for_tests() -> None:
    """Drop every cached file. For tests + manual recovery."""
    d = cache_dir()
    for f in d.glob("*.parquet"):
        try:
            f.unlink()
        except OSError:
            pass
    for f in d.glob("*.parquet.tmp"):
        try:
            f.unlink()
        except OSError:
            pass
