"""M1 tests: data layer (store, cleaner, ingest orchestration, universe as-of).

All tests run offline. Network sources are mocked via fixture monkeypatching.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest_engine.data.clean import CleanError, validate_clean
from backtest_engine.data.ingest import _write_boundary
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


def test_write_clean_merges_incremental_rows_and_incoming_wins(tmp_path):
    root = tmp_path / "clean"
    first = _raw_frame(n=2, start="2024-01-01")
    second = _raw_frame(n=2, start="2024-01-03")
    correction = second.iloc[[0]].copy()
    correction["close"] = 100.0
    correction["adj_close"] = 100.0

    write_clean(first, root, symbol="TEST", source="first")
    write_clean(second, root, symbol="TEST", source="second")
    write_clean(correction, root, symbol="TEST", source="correction")

    got = read_clean(root, "TEST")
    assert len(got) == 4
    assert got.loc[got["timestamp"] == second.loc[0, "timestamp"], "close"].iloc[0] == 100.0
    assert got.loc[got["timestamp"] == first.loc[0, "timestamp"], "source"].iloc[0] == "first"


def test_write_clean_failed_replacement_keeps_previous_partition(tmp_path, monkeypatch):
    root = tmp_path / "clean"
    original = _raw_frame(n=2, start="2024-01-01")
    write_clean(original, root, symbol="TEST", source="original")
    replacement = _raw_frame(n=2, start="2024-01-03")
    original_to_parquet = pd.DataFrame.to_parquet

    def fail_to_parquet(self, *args, **kwargs):
        original_to_parquet(self, *args, **kwargs)
        raise OSError("simulated parquet failure")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fail_to_parquet)
    with pytest.raises(OSError, match="simulated parquet failure"):
        write_clean(replacement, root, symbol="TEST", source="replacement")

    got = read_clean(root, "TEST")
    assert got["timestamp"].tolist() == original["timestamp"].tolist()


def test_write_boundary_preserves_full_history_on_incremental_update(tmp_path):
    clean_root = tmp_path / "data" / "clean"
    older = _raw_frame(n=2, start="2020-01-01")
    newer = _raw_frame(n=2, start="2024-01-01")
    _write_boundary(older, clean_root, "TEST")
    boundary = _write_boundary(newer, clean_root, "TEST")

    got = pd.read_csv(boundary)
    assert got.loc[0, "first_date"].startswith("2020-01-01")
    assert got.loc[0, "last_date"].startswith("2024-01-02")


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


def _yfinance_frame(
    close: list[float],
    *,
    dividends: list[float] | None = None,
    splits: list[float] | None = None,
    adj_close: list[float] | None = None,
) -> pd.DataFrame:
    n = len(close)
    idx = pd.date_range("2024-01-01", periods=n, tz="UTC")
    return pd.DataFrame(
        {
            "Open": close,
            "High": [p + 1.0 for p in close],
            "Low": [p - 1.0 for p in close],
            "Close": close,
            "Adj Close": adj_close if adj_close is not None else close,
            "Volume": [1_000.0] * n,
            "Dividends": dividends if dividends is not None else [0.0] * n,
            "Stock Splits": splits if splits is not None else [0.0] * n,
        },
        index=idx,
    )


def test_yfinance_normalize_zero_splits_are_finite():
    out = YFinanceSource._normalize(_yfinance_frame([100.0, 101.0, 102.0]))

    assert (out["split_ratio"] == 1.0).all()
    assert np.isfinite(out[["adj_open", "adj_high", "adj_low", "adj_close"]]).all().all()
    assert (out["adj_close"] == out["close"]).all()


def test_yfinance_normalize_split_uses_adjusted_close_factor():
    out = YFinanceSource._normalize(
        _yfinance_frame([100.0, 50.0, 52.0], splits=[0.0, 2.0, 0.0], adj_close=[50.0, 50.0, 52.0])
    )

    assert out["adj_close"].tolist() == [50.0, 50.0, 52.0]
    assert out["open"].tolist() == [100.0, 50.0, 52.0]
    assert out["adj_open"].tolist() == [50.0, 50.0, 52.0]


def test_yfinance_normalize_dividend_uses_adjusted_close_factor():
    out = YFinanceSource._normalize(
        _yfinance_frame(
            [100.0, 98.0, 99.0], dividends=[0.0, 2.0, 0.0], adj_close=[98.0, 98.0, 99.0]
        )
    )

    assert out["adj_close"].tolist() == [98.0, 98.0, 99.0]
    assert out["close"].tolist() == [100.0, 98.0, 99.0]


def test_yfinance_normalize_invalid_adjusted_close_falls_back_to_raw():
    out = YFinanceSource._normalize(
        _yfinance_frame([100.0, 101.0, 102.0], adj_close=[np.nan, 0.0, 102.0])
    )

    assert np.isfinite(out[["adj_open", "adj_high", "adj_low", "adj_close"]]).all().all()
    assert out["adj_close"].tolist() == [100.0, 101.0, 102.0]


def test_validate_clean_accepts_normalized_yfinance_no_action_rows():
    normalized = YFinanceSource._normalize(_yfinance_frame([100.0, 101.0, 102.0]))

    cleaned = validate_clean(normalized, source="yfinance")

    assert (cleaned["split_ratio"] == 1.0).all()
    assert np.isfinite(cleaned["adj_close"]).all()


def test_validate_clean_rejects_nonfinite_adjusted_ohlc():
    raw = _raw_frame()
    raw.loc[0, "adj_close"] = np.inf

    with pytest.raises(CleanError, match="adjusted OHLC"):
        validate_clean(raw, source="test")


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
            {"symbol": "BBB", "timestamp": "2009-01-01", "close": 49},  # drop: before listing
            {"symbol": "BBB", "timestamp": "2020-01-01", "close": 50},  # OK, before delist
            {"symbol": "BBB", "timestamp": "2020-06-30", "close": 51},  # drop: delist date
            {"symbol": "BBB", "timestamp": "2021-01-01", "close": 51},  # drop: post-delist
        ]
    )
    out = u.filter_panel(panel)
    assert len(out) == 2
    assert "BBB" in set(out["symbol"])
    assert set(out[out["symbol"] == "BBB"]["timestamp"].astype(str)) == {
        "2020-01-01 00:00:00+00:00"
    }
