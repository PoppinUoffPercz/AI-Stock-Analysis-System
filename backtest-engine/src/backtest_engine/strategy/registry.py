"""Strategy registry: name -> (signal_factory, default_params)."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from backtest_engine.strategy.bollinger import bollinger_breakout
from backtest_engine.strategy.builtin import sma_cross
from backtest_engine.strategy.rsi_reversion import rsi_reversion

SignalFactory = Callable[[pd.DataFrame, dict], pd.DataFrame]

REGISTRY: dict[str, tuple[SignalFactory, dict]] = {
    "sma_cross": (sma_cross, {"fast": 10, "slow": 30}),
    "rsi_reversion": (rsi_reversion, {"period": 14, "entry_level": 30, "exit_level": 50}),
    "bollinger_breakout": (
        bollinger_breakout,
        {"period": 20, "std_dev": 2.0, "stop_outside": False},
    ),
}


def get_strategy(name: str) -> tuple[SignalFactory, dict]:
    if name not in REGISTRY:
        raise KeyError(f"unknown strategy '{name}'; available: {sorted(REGISTRY)}")
    return REGISTRY[name]
