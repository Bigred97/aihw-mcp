"""Parquet on-disk parsed-DataFrame cache (cold-restart speedup)."""
from __future__ import annotations

import os
import time

import pandas as pd
import pytest

from aihw_mcp import parquet_cache


@pytest.fixture(autouse=True)
def _isolate_parquet_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AIHW_MCP_PARQUET_CACHE_DIR", str(tmp_path / "parquet"))
    yield


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "year": [2022, 2023, 2024],
            "cause": ["cardiovascular", "cancer", "respiratory"],
            "deaths": [50000, 45000, 12000],
        }
    )


def test_parquet_cache_writes_after_first_parse():
    key = ("https://example.com/cancer.xlsx", "xlsx", "Table 1", 0, 1, 1024, b"\x00" * 32, None)
    parquet_cache.write(key, _sample_df())
    result = parquet_cache.read_if_fresh(key)
    assert result is not None
    pd.testing.assert_frame_equal(_sample_df(), result)


def test_parquet_cache_skips_xlsx_parse_on_warm_hit():
    k1 = ("a", "xlsx", "T1", 0, 1, 0, b"", None)
    k2 = ("b", "csv", None, 0, 1, 0, b"", None)
    parquet_cache.write(k1, _sample_df())
    parquet_cache.write(k2, _sample_df().assign(cause=["x", "y", "z"]))

    out1 = parquet_cache.read_if_fresh(k1)
    out2 = parquet_cache.read_if_fresh(k2)
    assert out1 is not None and out2 is not None
    assert list(out1["cause"]) == ["cardiovascular", "cancer", "respiratory"]
    assert list(out2["cause"]) == ["x", "y", "z"]


def test_parquet_cache_self_heals_on_corruption():
    key = ("corrupt-key", "xlsx", "T", 0, 1, 0, b"", None)
    parquet_cache.write(key, _sample_df())
    path = parquet_cache.cache_dir() / parquet_cache._key_to_filename(key)
    assert path.is_file()

    path.write_bytes(b"not actually parquet")
    result = parquet_cache.read_if_fresh(key)
    assert result is None
    assert not path.is_file()


def test_parquet_cache_respects_ttl():
    key = ("ttl",)
    parquet_cache.write(key, _sample_df())
    path = parquet_cache.cache_dir() / parquet_cache._key_to_filename(key)

    # AIHW TTL is 24h; backdate to 25h ago.
    old = time.time() - 25 * 60 * 60
    os.utime(path, (old, old))

    assert parquet_cache.read_if_fresh(key) is None  # expired
    assert path.is_file()  # not deleted on TTL miss

    # Permissive TTL recovers the file.
    assert parquet_cache.read_if_fresh(key, ttl_seconds=48 * 60 * 60) is not None


def test_parquet_cache_missing_file_returns_none():
    assert parquet_cache.read_if_fresh(("never-written",)) is None


def test_env_var_override_routes_writes(tmp_path, monkeypatch):
    target = tmp_path / "custom-cache"
    monkeypatch.setenv("AIHW_MCP_PARQUET_CACHE_DIR", str(target))
    parquet_cache.write(("env-test",), _sample_df())
    assert len(list(target.glob("*.parquet"))) == 1


def test_reset_for_tests_clears_dir():
    parquet_cache.write(("k1",), _sample_df())
    parquet_cache.write(("k2",), _sample_df())
    parquet_cache.reset_for_tests()
    assert list(parquet_cache.cache_dir().glob("*.parquet")) == []
