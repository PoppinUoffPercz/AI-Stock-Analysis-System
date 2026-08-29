"""Adapter protocol shared by all three engine adapters (M2/M4/M9).

The protocol budgets the minimum surface every adapter must provide:
  - `run(...) -> BacktestResult` — single backtest run with fixed params
  - `sweep(...) -> list[BacktestResult]` — vectorized param grid in Phase 1

Backtrader / Nautilus will raise NotImplementedError on `sweep` (no vectorized
mode). VBT implements both.

The adapter is stateless; `run()` and `sweep()` parameters lock in the actual
spec/capital/costs at call time. This lets us share a single instance.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import pandas as pd

from backtest_engine.strategy.result import BacktestResult

# A signal factory is a callable: (ohlc, params) -> DataFrame with entry/exit
SignalFactory = Callable[[pd.DataFrame, dict[str, Any]], pd.DataFrame]


class EngineAdapter(Protocol):
    """Common interface for all engine adapters.

    Adapter modules in `backtest_engine.strategy.adapters` provide concrete
    classes implementing this protocol.
    """

    name: str  # "vectorbt" | "backtrader" | "nautilus"

    def run(
        self,
        signals: pd.DataFrame,  # entry/exit boolean or signed int columns
        ohlc: pd.DataFrame,  # canonical clean schema
        *,
        capital: float,
        cost_model: str,
        strategy_name: str,
        universe_ref: str,
        params: dict[str, Any],
        run_id: str | None,
    ) -> BacktestResult: ...

    def sweep(
        self,
        signal_factory: SignalFactory,
        ohlc: pd.DataFrame,
        *,
        param_grid: dict[str, list[Any]],
        capital: float,
        cost_model: str,
        strategy_name: str,
        universe_ref: str,
    ) -> list[BacktestResult]: ...
