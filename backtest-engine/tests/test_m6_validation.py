"""M6 tests: validation layer (walk-forward, Monte Carlo, permutation, stability)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest_engine.metrics.core import total_return
from backtest_engine.validation.monte_carlo import (
    block_bootstrap_returns,
    shuffle_trade_order,
)
from backtest_engine.validation.permutation import random_entry_permutation
from backtest_engine.validation.stability import build_metric_surface, param_drift
from backtest_engine.validation.walk_forward import rolling_windows

# --- helpers --------------------------------------------------------------


def _equity(seed: int = 0, n: int = 252, drift: float = 0.0005, vol: float = 0.01) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n).tz_localize("UTC")
    rets = drift + rng.normal(0, vol, n)
    return pd.Series(np.cumprod(1 + rets) * 100, index=idx)


def _backtest_result_mock(equity: pd.Series, capital: float = 100.0):
    """Minimal stand-in for BacktestResult covering only fields M6 needs."""

    class _M:
        def __init__(self_):
            self_.equity = equity
            self_.returns = equity.pct_change().fillna(0.0)
            self_.capital = capital
            self_.params: dict = {}
            self_.raw_metrics: dict = {}
            self_.n_trades = 0

        @property
        def final_equity(self_):
            return float(equity.iloc[-1])

    return _M()


# --- Monte Carlo ----------------------------------------------------------


def test_montecarlo_returns_distribution_metrics():
    eq = _equity(seed=1, n=300, drift=0.001, vol=0.008)
    mc = shuffle_trade_order(eq, n_trials=200, rng_seed=42)
    assert mc.n_trials == 200
    assert len(mc.max_dd_pcts) == 200
    assert mc.max_dd_pctile_5 <= mc.max_dd_pctile_95
    assert -1.0 <= mc.max_dd_p_realized <= 1.0


def test_montecarlo_handles_short_equity():
    eq = pd.Series([100], index=pd.bdate_range("2020-01-01", periods=1).tz_localize("UTC"))
    mc = shuffle_trade_order(eq)
    assert mc.n_trials == 0  # too short to shuffle


def test_block_bootstrap_returns_runnable():
    eq = _equity(seed=2, n=400, drift=0.0015, vol=0.012)
    r = eq.pct_change().dropna()
    bb = block_bootstrap_returns(r, block_size=10, n_trials=100, rng_seed=5)
    assert bb.n_trials == 100
    assert len(bb.terminal_wealth) == 100


# --- Permutation ----------------------------------------------------------


def test_permutation_p_value_in_unit_interval():
    market_returns = pd.Series(
        np.random.default_rng(0).normal(0.001, 0.01, 252),
        index=pd.bdate_range("2020-01-01", periods=252).tz_localize("UTC"),
    )
    real_entries = pd.Series(False, index=market_returns.index)
    real_entries.iloc[::25] = True
    res = random_entry_permutation(
        market_returns,
        real_entries,
        metric_fn=lambda eq, r: total_return(eq),
        n_entries=10,
        holding_period=1,
        n_trials=100,
        rng_seed=11,
    )
    assert 0.0 <= res.p_value <= 1.0
    assert res.n_trials == 100


def test_permutation_zero_entries_returns_unit_p():
    market_returns = pd.Series(
        [0.0, 0.01, 0.02], index=pd.bdate_range("2020-01-01", periods=3).tz_localize("UTC")
    )
    real_entries = pd.Series(False, index=market_returns.index)
    res = random_entry_permutation(
        market_returns,
        real_entries,
        metric_fn=lambda eq, r: 0.0,
        n_entries=0,
    )
    assert res.p_value == 1.0
    assert res.n_trials == 0


def test_permutation_n_entries_changes_random_trials():
    market_returns = pd.Series(
        np.linspace(-0.01, 0.02, 40),
        index=pd.bdate_range("2020-01-01", periods=40).tz_localize("UTC"),
    )
    real_entries = pd.Series(False, index=market_returns.index)
    real_entries.iloc[[5, 15, 25]] = True
    one = random_entry_permutation(
        market_returns,
        real_entries,
        metric_fn=lambda eq, r: total_return(eq),
        n_entries=1,
        holding_period=2,
        n_trials=50,
        rng_seed=3,
    )
    three = random_entry_permutation(
        market_returns,
        real_entries,
        metric_fn=lambda eq, r: total_return(eq),
        n_entries=3,
        holding_period=2,
        n_trials=50,
        rng_seed=3,
    )

    assert not np.allclose(one.random_metrics, three.random_metrics)


def test_permutation_detects_known_entry_edge_with_finite_sample_p_value():
    idx = pd.bdate_range("2020-01-01", periods=100).tz_localize("UTC")
    market_returns = pd.Series(0.0, index=idx)
    real_entries = pd.Series(False, index=idx)
    real_entries.iloc[[10, 30, 50]] = True
    market_returns.iloc[[11, 31, 51]] = 0.20

    res = random_entry_permutation(
        market_returns,
        real_entries,
        metric_fn=lambda eq, r: total_return(eq),
        n_entries=3,
        holding_period=1,
        n_trials=500,
        rng_seed=9,
    )

    assert res.real_metric > 0.5
    assert res.p_value == pytest.approx(1 / 501)


def test_permutation_noise_is_not_systematically_significant():
    idx = pd.bdate_range("2020-01-01", periods=252).tz_localize("UTC")
    market_returns = pd.Series(np.random.default_rng(0).normal(0.0, 0.01, 252), index=idx)
    real_entries = pd.Series(False, index=idx)
    real_entries.iloc[::25] = True

    p_values = [
        random_entry_permutation(
            market_returns,
            real_entries,
            metric_fn=lambda eq, r: total_return(eq),
            n_entries=int(real_entries.sum()),
            holding_period=1,
            n_trials=300,
            rng_seed=seed,
        ).p_value
        for seed in range(10)
    ]

    assert all(p > 0.05 for p in p_values)


# --- Stability ------------------------------------------------------------


def test_stability_detects_broad_plateau():
    # Build a sweep where metric is high across most of the grid.
    results = []
    for fast in (5, 10, 15):
        for slow in (30, 50, 70):
            from backtest_engine.strategy.result import BacktestResult

            idx = pd.bdate_range("2020-01-01", periods=10).tz_localize("UTC")
            r = BacktestResult(
                run_id="r",
                strategy_name="s",
                engine="vectorbt",
                params={"fast": fast, "slow": slow},
                capital=100,
                cost_model="zero",
                universe_ref="u",
                equity=pd.Series([100, 120], index=idx[:2]),
                returns=pd.Series([0, 0.2], index=idx[:2]),
                trades=[],
                raw_metrics={},
            )
            results.append(r)
    # Construct equity with consistent 20% gain (final_equity / capital - 1 = 0.2)
    for r in results:
        idx = pd.bdate_range("2020-01-01", periods=2).tz_localize("UTC")
        r.equity = pd.Series([100, 120], index=idx)
    res = build_metric_surface(results, param_x="fast", param_y="slow", metric="total_return")
    assert res.surface.shape == (3, 3)
    assert res.is_plateau is True
    assert res.plateau_score == pytest.approx(1.0, rel=0.05)


def test_stability_spike_not_plateau():
    from backtest_engine.strategy.result import BacktestResult

    results = []
    pairs = [(5, 30), (5, 50), (5, 70), (10, 30), (10, 50), (10, 70), (15, 30), (15, 50), (15, 70)]
    # Only one cell has high return, rest low -> spike
    for i, (fast, slow) in enumerate(pairs):
        v = 0.50 if (fast, slow) == (10, 50) else 0.001
        idx = pd.bdate_range("2020-01-01", periods=2).tz_localize("UTC")
        r = BacktestResult(
            run_id=f"r{i}",
            strategy_name="s",
            engine="vectorbt",
            params={"fast": fast, "slow": slow},
            # capital=100, equity ending at 120 -> 20% return for non-spike.
            capital=100,
            cost_model="zero",
            universe_ref="u",
            equity=pd.Series([100, 100 * (1 + v)], index=idx),
            returns=pd.Series([0, v], index=idx),
            trades=[],
            raw_metrics={},
        )
        results.append(r)
    res = build_metric_surface(results, param_x="fast", param_y="slow", metric="total_return")
    assert res.is_plateau is False
    assert res.plateau_score < 0.20


def test_param_drift_returns_dataframe():
    folds = [{"fast": 5, "slow": 30}, {"fast": 7, "slow": 35}, {"fast": 6, "slow": 32}]
    df = param_drift(folds, ["fast", "slow"])
    assert list(df.columns) == ["fast", "slow"]
    assert len(df) == 3
    assert df["fast"].iloc[1] == 7


# --- Walk-forward windows helper ------------------------------------------


def test_rolling_windows_emits_aligned_pairs():
    idx = pd.bdate_range("2010-01-01", periods=252 * 10).tz_localize("UTC")
    ohlc = pd.DataFrame({"close": 100 + np.arange(len(idx))}, index=idx)
    is_w, oos_w = rolling_windows(ohlc, is_years=5, oos_years=1, step_years=1)
    assert len(is_w) == len(oos_w)
    assert len(is_w) >= 3
    # IS end == OOS start
    for (_s, e), (os_, oe) in zip(is_w, oos_w, strict=True):
        assert e == os_
        assert oe > e


def test_rolling_windows_short_history_returns_empty():
    idx = pd.bdate_range("2024-01-01", periods=10).tz_localize("UTC")
    ohlc = pd.DataFrame({"close": 100 + np.arange(10)}, index=idx)
    is_w, oos_w = rolling_windows(ohlc, is_years=5, oos_years=1)
    assert is_w == [] and oos_w == []
