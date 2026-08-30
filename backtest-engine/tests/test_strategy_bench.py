"""Integration tests for the strategy benchmark workflow."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest_engine.strategy.spec import StrategySpec


def _regime_bars() -> pd.DataFrame:
    index = pd.bdate_range("2020-01-01", periods=900).tz_localize("UTC")
    positions = pd.Series(index.year).groupby(index.year).cumcount().to_numpy()
    year_lengths = pd.Series(index.year).groupby(index.year).transform("size").to_numpy()
    phase = positions / np.maximum(year_lengths - 1, 1)
    close = np.where(phase <= 0.5, 100.0 + 100.0 * phase, 200.0 - 100.0 * (phase - 0.5) / 0.5)
    close = pd.Series(close, index=index, dtype="float64")
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000_000.0,
        },
        index=index,
    )


def _half_window_strategy(bars: pd.DataFrame, params: dict) -> pd.DataFrame:
    signals = pd.DataFrame(False, index=bars.index, columns=["entry", "exit"])
    midpoint = len(bars) // 2
    if int(params["mode"]) == 0:
        signals.iloc[0, 0] = True
        signals.iloc[max(1, midpoint - 1), 1] = True
    else:
        signals.iloc[midpoint, 0] = True
        signals.iloc[-2, 1] = True
    return signals


def test_walk_forward_selects_parameters_from_is_only():
    from notebooks.strategy_bench import run_walk_forward

    spec = StrategySpec(name="regime", signal_factory=_half_window_strategy, params={"mode": 0})
    result = run_walk_forward(
        spec,
        _regime_bars(),
        is_years=1,
        oos_years=1,
        param_grid={"mode": [0, 1]},
        objective="total_return",
        min_valid_folds=2,
    )

    assert len(result.fold_params) >= 2
    assert all(params == {"mode": 0} for params in result.fold_params)


def test_walk_forward_rejects_too_few_valid_folds():
    from notebooks.strategy_bench import run_walk_forward

    spec = StrategySpec(name="regime", signal_factory=_half_window_strategy, params={"mode": 0})
    with pytest.raises(ValueError, match="minimum valid folds"):
        run_walk_forward(
            spec,
            _regime_bars().iloc[:300],
            is_years=2,
            oos_years=1,
            param_grid={"mode": [0, 1]},
            min_valid_folds=1,
        )
