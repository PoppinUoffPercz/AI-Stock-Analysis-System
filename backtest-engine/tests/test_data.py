"""M1 tests: data layer (store, cleaner, ingest orchestration, universe as-of).

All tests run offline. Network sources are mocked via fixture monkeypatching.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backtest_engine.data.clean import CleanError, validate_clean
from backtest_engine.data.sources.base import YFinanceSource
from backtest_engine.data.store import CLEAN_COLUMNS, clean_path, read_clean, write_clean
from backtest_engine.data.universe import Universe, write_spx_sample

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raw_frame(n: int = 5, start: str = "2024-01-01") -> pd.DataFrame:
    """Build a tiny in-memory raw OHLCV frame (no adj columns)."""
    dates = pd.bdate_range(start, periods=n)
    df = (
        pd.DataFrame(
            {
                "timestamp": dates.tz_localize("UTC"),
                "open": 100.0 + pd.RangeIndex(n).astype(float),
                "high": 102.0 + pd.RangeIndex(n).astype(float),
                "low": 99.0 + pd.RangeIndex(n).astype(float),
                "close": 101.0 + pd.RangeIndex(n).astype(float),
                "volume": 1_000_000.0 + pd.RangeIndex(n).astype(float) * 100,
                "dividend": 0.0,
                "split_ratio": 1.0,
            }
        )
        .reset_index(drop=True)
        .copy()
    )
    df["adj_open"] = df["open"]
    df["adj_high"] = df["high"]
    df["adj_low"] = df["low"]
    df["adj_close"] = df["close"]
    return df


# ---------------------------------------------------------------------------
# Cleaner
# ---------------------------------------------------------------------------


def test_validate_clean_fills_missing_optional_cols():
    raw = _raw_frame()[["timestamp", "open", "high", "low", "close", "volume"]]
    out = validate_clean(raw, source="test")
    assert list(out.columns) == list(CLEAN_COLUMNS)
    assert (out["dividend"] == 0).all()
    assert (out["split_ratio"] == 1).all()
    assert (out["adj_open"] == out["open"]).all()


def test_validate_clean_coerces_timestamp_to_utc():
    raw = _raw_frame()
    raw["timestamp"] = raw["timestamp"].dt.tz_localize(None)
    out = validate_clean(raw, source="test")
    assert out["timestamp"].dt.tz is not None
    assert str(out["timestamp"].dt.tz) == "UTC"


def test_validate_clean_dedupes_duplicate_timestamps():
    raw = _raw_frame()
    dup = pd.concat([raw, raw.iloc[:1]], ignore_index=True)  # duplicate of row 0
    out = validate_clean(dup, source="test")
    assert out["timestamp"].is_unique


def test_validate_clean_rejects_negative_volume():
    raw = _raw_frame()
    raw.loc[0, "volume"] = -1
    with pytest.raises(CleanError):
        validate_clean(raw, source="test")


def test_validate_clean_rejects_high_below_low():
    bad = _raw_frame()
    bad.loc[0, "high"] = 1.0  # high < open/close/low
    bad.loc[0, "low"] = 99.0
    with pytest.raises(CleanError):
        validate_clean(bad, source="test")


def test_validate_clean_rejects_negative_dividend():
    raw = _raw_frame()
    raw.loc[0, "dividend"] = -0.5
    with pytest.raises(CleanError):
        validate_clean(raw, source="test")


def test_validate_clean_rejects_zero_split_ratio():
    raw = _raw_frame()
    raw.loc[0, "split_ratio"] = 0.0
    with pytest.raises(CleanError):
        validate_clean(raw, source="test")


def test_validate_clean_rejects_missing_required_column():
    raw = _raw_frame().drop(columns=["close"])
    with pytest.raises(CleanError):
        validate_clean(raw, source="test")


# ---------------------------------------------------------------------------
# Store round-trip
# ---------------------------------------------------------------------------


def test_write_clean_partitions_by_year(tmp_path):
    df = pd.concat(
        [_raw_frame(n=10, start="2023-12-25"), _raw_frame(n=10, start="2024-01-01")],
        ignore_index=True,
    )
    paths = write_clean(df, tmp_path / "clean", symbol="TEST", source="test")
    assert len(paths) == 2  # 2023 + 2024
    years = sorted(int(p.stem) for p in paths)
    assert years == [2023, 2024]
    # Files under symbol dir
    assert all("TEST" in str(p) for p in paths)


def test_read_clean_round_trip(tmp_path):
    df = _raw_frame(n=5, start="2024-01-01")
    write_clean(df, tmp_path / "clean", symbol="TEST", source="test")
    got = read_clean(tmp_path / "clean", "TEST", start="2024-01-01", end="2024-01-31")
    assert len(got) == len(df)
    assert list(got.columns) == list(CLEAN_COLUMNS)
    # Source tag persisted
    assert (got["source"] == "test").all()


def test_read_clean_missing_symbol_returns_empty(tmp_path):
    got = read_clean(tmp_path / "clean", "NOPE")
    assert len(got) == 0
    assert list(got.columns) == list(CLEAN_COLUMNS)


def test_clean_path_canonical():
    p = clean_path(Path("clean"), "aapl", 2024)
    assert p.as_posix().replace("\\", "/") == "clean/AAPL/2024.parquet"


# ---------------------------------------------------------------------------
# YFinance source (mocked: we DON'T hit network)
# ---------------------------------------------------------------------------


def test_yfinance_source_normalize_yields_canonical_columns(monkeypatch):
    # Simulate yfinance output with 'auto_adjust=False, actions=True'.
    raw = _raw_frame(n=3)
    fake_index = raw["timestamp"]
    fake_yf_df = pd.DataFrame(
        {
            "Open": raw["open"],
            "High": raw["high"],
            "Low": raw["low"],
            "Close": raw["close"],
            "Volume": raw["volume"],
            "Dividends": raw["dividend"],
            "Stock Splits": raw["split_ratio"],
        }
    )
    fake_yf_df.index = fake_index
    fake_yf_df.index.name = "Date"

    class FakeTicker:
        def __init__(self, symbol: str) -> None:
            self._sym = symbol

        def history(self, **kw):
            return fake_yf_df

    fake_yf_module = type("_YF", (), {"Ticker": FakeTicker})
    src = YFinanceSource.__new__(YFinanceSource)  # bypass real yfinance import
    from backtest_engine.config import Settings

    src.s = Settings()
    src._yf = fake_yf_module

    out = src.fetch("TEST")
    assert list(out.columns) == [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adj_open",
        "adj_high",
        "adj_low",
        "adj_close",
        "dividend",
        "split_ratio",
    ]
    # adj prices equal raw when no corp actions take place
    assert ((out["adj_close"] - out["close"]).abs() < 1e-9).all()


# ---------------------------------------------------------------------------
# Universe as-of + survivorship
# ---------------------------------------------------------------------------


def test_write_spx_sample_creates_csv(tmp_path):
    p = write_spx_sample(tmp_path / "u", ["AAPL", "MSFT"])
    df = pd.read_csv(p)
    assert set(df["symbol"]) == {"AAPL", "MSFT"}
    assert (df["list_date"] == "2008-01-01").all()


def test_universe_as_of_filters_by_dates():
    u = Universe(
        pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "list_date": "2010-01-01",
                    "delist_date": "",
                    "delist_reason": "",
                },
                {
                    "symbol": "BBB",
                    "list_date": "2015-01-01",
                    "delist_date": "2020-06-30",
                    "delist_reason": "acquired",
                },
                {
                    "symbol": "CCC",
                    "list_date": "",
                    "delist_date": "2018-01-01",
                    "delist_reason": "bankrupt",
                },
            ]
        )
    )

    # CCC has unknown list_date => tradable from beginning; dies 2018-01-01.
    assert u.as_of("2012-01-01") == ["AAA", "CCC"]
    # BBB listed in 2015, CCC not yet delisted.
    assert u.as_of("2016-06-01") == ["AAA", "BBB", "CCC"]
    # After CCC's delist date, just AAA + BBB.
    assert u.as_of("2018-07-01") == ["AAA", "BBB"]
    # After BBB's delist date, only AAA remains.
    assert u.as_of("2020-07-01") == ["AAA"]

    assert u.is_delisted("BBB", "2020-06-30") is True
    assert u.is_delisted("BBB", "2020-06-29") is False
    assert u.is_delisted("AAA", "2025-01-01") is False
    assert u.is_delisted("ZZZ", "2025-01-01") is False  # unknown -> not delisted


def test_universe_filter_panel_drops_post_delist_rows():
    u = Universe(
        pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "list_date": "2010-01-01",
                    "delist_date": "",
                    "delist_reason": "",
                },
                {
                    "symbol": "BBB",
                    "list_date": "2010-01-01",
                    "delist_date": "2020-06-30",
                    "delist_reason": "acquired",
                },
            ]
        )
    )
    panel = pd.DataFrame(
        [
            {"symbol": "AAA", "timestamp": "2025-01-01", "close": 100},
            {"symbol": "BBB", "timestamp": "2020-01-01", "close": 50},  # OK, before delist
            {"symbol": "BBB", "timestamp": "2021-01-01", "close": 51},  # drop: post-delist
        ]
    )
    out = u.filter_panel(panel)
    assert len(out) == 2
    assert "BBB" in set(out["symbol"])
    assert set(out[out["symbol"] == "BBB"]["timestamp"].astype(str)) == {
        "2020-01-01 00:00:00+00:00"
    }
