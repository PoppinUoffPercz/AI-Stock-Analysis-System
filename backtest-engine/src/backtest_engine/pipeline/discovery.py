"""Thin pipeline runner: execute a StrategySpec through a named adapter.

Bridges the framework-neutral `StrategySpec` to each engine adapter. Returns
the BacktestResult. Used by both the CLI (M8) and by validation layer (M6).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from backtest_engine.strategy.adapters.bt_adapter import BTAdapter
from backtest_engine.strategy.adapters.vbt_adapter import VBTAdapter
from backtest_engine.strategy.base import EngineAdapter
from backtest_engine.strategy.result import BacktestResult
from backtest_engine.strategy.spec import StrategySpec

_ADAPTERS = {
    "vectorbt": VBTAdapter,
    "backtrader": BTAdapter,
    # nautilus wired in M9
}


def get_adapter(name: str) -> EngineAdapter:
    if name not in _ADAPTERS:
        raise ValueError(f"unknown adapter: {name!r}; supported: {list(_ADAPTERS)}")
    return _ADAPTERS[name]()


def run_spec(
    spec: StrategySpec,
    ohlc: pd.DataFrame,
    *,
    engine: str = "vectorbt",
    cost_model: str | None = None,
    capital: float | None = None,
    params: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> BacktestResult:
    """Execute `spec` through `engine`. Adapter maps spec -> result."""
    adapter = get_adapter(engine)
    use_cost = cost_model or spec.cost_model
    use_cap = capital if capital is not None else spec.capital
    use_params = params or spec.params
    signals = spec.make_signals(ohlc, use_params)
    return adapter.run(
        signals,
        ohlc,
        capital=use_cap,
        cost_model=use_cost,
        strategy_name=spec.name,
        universe_ref=spec.universe_ref,
        params=use_params,
        run_id=run_id,
    )
