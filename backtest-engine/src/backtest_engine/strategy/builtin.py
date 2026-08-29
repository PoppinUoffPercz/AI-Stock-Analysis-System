"""Builtin signal factories. Each returns a frame with `entry`/`exit` boolean
columns aligned to `ohlc.index`. They output the *signal at the close it is
first observed*. The adapter translates to execution-at-next-open.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def sma_cross(ohlc: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """SMA crossover. params: {fast: int, slow: int}.

    Entry at first bar where fast SMA crosses above slow; exit at the opposite.
    Signals emit on the bar the cross closes (so fills at next bar open).
    """
    fast = int(params.get("fast", 10))
    slow = int(params.get("slow", 30))
    if fast >= slow:
        raise ValueError(f"fast ({fast}) must be < slow ({slow})")
    close = ohlc["close"]
    ma_f = close.rolling(fast).mean()
    ma_s = close.rolling(slow).mean()
    cross_up = (ma_f > ma_s) & (ma_f.shift(1) <= ma_s.shift(1))
    cross_dn = (ma_f < ma_s) & (ma_f.shift(1) >= ma_s.shift(1))
    out = pd.DataFrame(index=ohlc.index)
    out["entry"] = cross_up.fillna(False).astype(bool)
    out["exit"] = cross_dn.fillna(False).astype(bool)
    return out
