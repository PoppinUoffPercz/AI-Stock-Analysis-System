"""SignalFactory protocol: turn (ohlc bars, params) -> entry/exit signals.

Strategies are expressed as pure functions over a single symbol's OHLC frame,
returning a frame with at minimum `entry` and `exit` boolean columns (True on the
bar where a new signal appears). VBTAdapter uses them directly.

Implementation example lives in `backtest_engine.strategy.builtin.sma_cross`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import pandas as pd

# A signal factory is a callable: (ohlc, params) -> DataFrame with entry/exit
SignalFactory = Callable[[pd.DataFrame, dict[str, Any]], pd.DataFrame]


class _SignalFactoryProto(Protocol):
    def __call__(self, ohlc: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame: ...
