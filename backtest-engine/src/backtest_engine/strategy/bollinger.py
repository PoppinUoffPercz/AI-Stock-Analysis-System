"""Bollinger Bands breakout signal factory.

Long when close crosses above upper band (breakout); exit when close touches
the middle band (mean reversion take-profit) OR drops below lower band
(stop-loss).

params:
  period    int  default 20    SMA window
  std_dev   float default 2.0  band width
  stop_outside bool default False  use lower band as exit (else middle)
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def bollinger_breakout(ohlc: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Bollinger Bands breakout. params: {period, std_dev, stop_outside}."""
    period = int(params.get("period", 20))
    std_dev = float(params.get("std_dev", 2.0))
    stop_outside = bool(params.get("stop_outside", False))

    close = ohlc["close"]
    mid = close.rolling(period).mean()
    sd = close.rolling(period).std(ddof=0)
    upper = mid + std_dev * sd
    lower = mid - std_dev * sd

    cross_above = (close > upper) & (close.shift(1) <= upper.shift(1))
    exit_band = lower if stop_outside else mid
    touch_exit = (close <= exit_band) & (close.shift(1) > exit_band.shift(1))

    out = pd.DataFrame(index=ohlc.index)
    out["entry"] = cross_above.fillna(False).astype(bool)
    out["exit"] = touch_exit.fillna(False).astype(bool)
    return out
