"""Tests for the bollinger_breakout signal factory.

Mirrors the structure of `test_m2_vbt.py` but at the unit level — we don't run
the adapter, just verify signal logic + column contract.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest_engine.strategy.bollinger import bollinger_breakout


def _ohlc(n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2020-01-02", periods=n).tz_localize("UTC")
    close = 100 + np.cumsum(rng.normal(0, 0.5, n)) + rng.normal(0, 3, n)
    return pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1e5}, index=idx
    )


def test_bollinger_returns_entry_exit_columns():
    df = bollinger_breakout(_ohlc(80), {"period": 20, "std_dev": 2.0, "stop_outside": False})
    assert "entry" in df.columns and "exit" in df.columns
    assert df["entry"].dtype == bool
    assert df["exit"].dtype == bool
    assert len(df) == 80


def test_bollinger_no_lookahead_in_first_window():
    """While the SMA window is building, signals should be False (NaN -> False)."""
    df = bollinger_breakout(_ohlc(40), {"period": 20, "std_dev": 2.0, "stop_outside": False})
    assert not df["entry"].iloc[:19].any()
    assert not df["exit"].iloc[:19].any()


def test_bollinger_stop_outside_alters_exit_logic():
    """stop_outside=True uses lower band for exit; default uses middle band.

    Verifying via a synthetic case where mid band stays calm but lower band
    is hit: both should produce at least one exit in their respective
    constructions when seeded correctly. Here we just confirm the column is
    produced either way (functional divergence covered in integration tests).
    """
    df_default = bollinger_breakout(
        _ohlc(100), {"period": 20, "std_dev": 2.0, "stop_outside": False}
    )
    df_stop = bollinger_breakout(_ohlc(100), {"period": 20, "std_dev": 2.0, "stop_outside": True})
    assert not df_default.equals(df_stop)  # paths diverge on at least one bar
