"""Thin pipeline runner: execute a StrategySpec through a named adapter.

Bridges the framework-neutral `StrategySpec` to each engine adapter. Returns
the BacktestResult. Used by both the CLI (M8) and by validation layer (M6).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from backtest_engine.data.universe import Universe
from backtest_engine.reproducibility import build_manifest
from backtest_engine.strategy.adapters.bt_adapter import BTAdapter
from backtest_engine.strategy.adapters.vbt_adapter import VBTAdapter
from backtest_engine.strategy.base import EngineAdapter
from backtest_engine.strategy.result import BacktestResult
from backtest_engine.strategy.spec import StrategySpec

_ADAPTERS = {
    "vectorbt": VBTAdapter,
    "backtrader": BTAdapter,
}


def get_adapter(name: str) -> EngineAdapter:
    if name == "nautilus":
        from backtest_engine.strategy.adapters.nautilus_adapter import NautilusAdapter

        return NautilusAdapter()
    if name not in _ADAPTERS:
        raise ValueError(f"unknown adapter: {name!r}; supported: {[*_ADAPTERS, 'nautilus']}")
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
    universe: Universe | str | Path | None = None,
    random_seed: int | None = None,
    relevant_args: dict[str, Any] | None = None,
    dataset_identity: dict[str, Any] | None = None,
) -> BacktestResult:
    """Execute `spec` through `engine`, optionally enforcing point-in-time membership."""
    if universe is not None:
        active_universe = (
            universe if isinstance(universe, Universe) else Universe.from_csv(universe)
        )
        ohlc = active_universe.filter_panel(ohlc)
        if ohlc.empty:
            raise ValueError("universe excludes every input bar")
    adapter = get_adapter(engine)
    use_cost = cost_model or spec.cost_model
    use_cap = capital if capital is not None else spec.capital
    use_params = params if params is not None else spec.params
    signals = spec.make_signals(ohlc, use_params)
    result = adapter.run(
        signals,
        ohlc,
        capital=use_cap,
        cost_model=use_cost,
        strategy_name=spec.name,
        universe_ref=spec.universe_ref,
        params=use_params,
        run_id=run_id,
    )
    if not isinstance(result, BacktestResult):
        return result
    result.manifest = build_manifest(
        run_id=result.run_id,
        strategy_name=spec.name,
        signal_factory=spec.signal_factory,
        engine=result.engine,
        params=use_params,
        capital=use_cap,
        cost_model=use_cost,
        universe_ref=spec.universe_ref,
        ohlc=ohlc,
        universe=universe if isinstance(universe, (str, Path)) else None,
        random_seed=random_seed,
        relevant_args=relevant_args,
        dataset_identity=dataset_identity,
    )
    return result
