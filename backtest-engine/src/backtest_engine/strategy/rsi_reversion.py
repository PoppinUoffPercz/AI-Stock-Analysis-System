"""RSI mean-reversion signal factory (plan M8 - second example strategy)."""

from __future__ import annotations

from typing import Any

import pandas as pd


def rsi_reversion(ohlc: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Entry when RSI < oversold; exit when RSI > oversold_exit.

    params: {period: int=14, entry_level: int=30, exit_level: int=50}
    """
    period = int(params.get("period", 14))
    entry_level = float(params.get("entry_level", 30))
    exit_level = float(params.get("exit_level", 50))
    close = ohlc["close"]
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    out = pd.DataFrame(index=ohlc.index)
    out["entry"] = (rsi < entry_level).astype(bool)
    out["exit"] = (rsi > exit_level).astype(bool)
    return out
