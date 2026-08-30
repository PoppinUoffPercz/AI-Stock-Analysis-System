"""Adapter protocol shared by all three engine adapters (M2/M4/M9).

The protocol budgets the minimum surface every adapter must provide:
  - `run(...) -> BacktestResult` — single backtest run with fixed params

VectorBT owns parameter sweeps because it is the only vectorized adapter.

The adapter is stateless; `run()` parameters lock in the actual
spec/capital/costs at call time. This lets us share a single instance.
"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd

from backtest_engine.strategy.result import BacktestResult


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
