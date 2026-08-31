"""M6 tests: validation layer (walk-forward, Monte Carlo, permutation, stability)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest_engine.metrics.core import total_return
from backtest_engine.pipeline.discovery import run_spec
from backtest_engine.strategy.spec import StrategySpec
from backtest_engine.validation.monte_carlo import (
    block_bootstrap_returns,
    bootstrap_trade_returns,
    shuffle_trade_order,
)
from backtest_engine.validation.permutation import EntryEvaluation, random_entry_permutation
from backtest_engine.validation.stability import build_metric_surface, param_drift
from backtest_engine.validation.walk_forward import rolling_windows, walk_forward

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
    trade_returns = pd.Series([0.10, -0.05, 0.20, -0.10, 0.03])
    mc = shuffle_trade_order(trade_returns, n_trials=200, rng_seed=42)
    assert mc.n_trials == 200
    assert len(mc.max_dd_pcts) == 200
    assert np.unique(mc.max_dd_pcts).size > 1
    assert mc.max_dd_pctile_5 <= mc.max_dd_pctile_95
    assert -1.0 <= mc.max_dd_p_realized <= 1.0


def test_montecarlo_handles_short_trade_returns():
    mc = shuffle_trade_order(pd.Series([], dtype=float))
    assert mc.n_trials == 0


def test_montecarlo_drawdown_includes_initial_wealth():
    mc = shuffle_trade_order(pd.Series([-0.5, 0.1]), n_trials=20, rng_seed=42)

    np.testing.assert_allclose(mc.max_dd_pcts, -0.5)


def test_block_bootstrap_returns_runnable():
    eq = _equity(seed=2, n=400, drift=0.0015, vol=0.012)
    r = eq.pct_change().dropna()
    bb = block_bootstrap_returns(r, block_size=10, n_trials=100, rng_seed=5)
    assert bb.n_trials == 100
    assert len(bb.terminal_wealth) == 100


def test_bootstrap_trade_returns_changes_terminal_wealth_and_sharpe():
    trade_returns = pd.Series([0.10, -0.05, 0.20, -0.10, 0.03, 0.01])

    bootstrap = bootstrap_trade_returns(trade_returns, n_trials=200, rng_seed=42)

    assert np.unique(bootstrap.terminal_wealth).size > 1
    assert np.unique(bootstrap.sharpe_samples).size > 1


def test_montecarlo_sharpe_is_unannualized_by_default():
    trade_returns = pd.Series([0.10, -0.05, 0.20, -0.10, 0.03, 0.01])

    unannualized = bootstrap_trade_returns(trade_returns, n_trials=50, rng_seed=42)
    annualized = bootstrap_trade_returns(
        trade_returns, n_trials=50, rng_seed=42, periods_per_year=252
    )

    np.testing.assert_allclose(
        annualized.sharpe_samples, unannualized.sharpe_samples * np.sqrt(252)
    )


def test_block_bootstrap_accepts_explicit_sharpe_periods():
    returns = pd.Series([0.01, -0.02, 0.03, 0.01, -0.01, 0.02])

    unannualized = block_bootstrap_returns(returns, block_size=2, n_trials=50, rng_seed=42)
    annualized = block_bootstrap_returns(
        returns, block_size=2, n_trials=50, rng_seed=42, periods_per_year=4
    )

    np.testing.assert_allclose(annualized.sharpe_samples, unannualized.sharpe_samples * 2)


# --- Permutation ----------------------------------------------------------


def _single_position_evaluator(bar_returns: pd.Series, holding_period: int = 2):
    """Evaluate next-bar entries with one long position and a fixed exit policy."""

    def evaluate(entries: pd.Series):
        exposure = np.zeros(len(entries), dtype="float64")
        completed_trades = 0
        occupied_until = -1
        for signal_pos in np.flatnonzero(entries.to_numpy()):
            fill_pos = int(signal_pos) + 1
            if fill_pos >= len(entries) or fill_pos < occupied_until:
                continue
            exit_pos = fill_pos + holding_period
            exposure[fill_pos : min(exit_pos, len(entries))] = 1.0
            occupied_until = exit_pos
            if exit_pos < len(entries):
                completed_trades += 1
        strategy_returns = bar_returns.to_numpy() * exposure
        metric = float(np.prod(1.0 + strategy_returns) - 1.0)
        return EntryEvaluation(
            metric=metric,
            completed_trades=completed_trades,
            exposure=pd.Series(exposure, index=entries.index),
        )

    return evaluate


def test_permutation_real_metric_matches_actual_benchmark_policy():
    idx = pd.bdate_range("2020-01-01", periods=40).tz_localize("UTC")
    close = pd.Series(np.linspace(100.0, 140.0, len(idx)), index=idx)
    ohlc = pd.DataFrame(
        {
            "open": close.shift(1, fill_value=99.0) + 2.0,
            "high": close + 3.0,
            "low": close - 3.0,
            "close": close,
            "volume": 1_000_000.0,
        },
        index=idx,
    )

    def scheduled_signals(bars: pd.DataFrame, _params: dict) -> pd.DataFrame:
        signals = pd.DataFrame(False, index=bars.index, columns=["entry", "exit"])
        signals.iloc[[1, 12, 24], signals.columns.get_loc("entry")] = True
        signals.iloc[[7, 18, 30], signals.columns.get_loc("exit")] = True
        return signals

    spec = StrategySpec(name="scheduled", signal_factory=scheduled_signals, capital=10_000.0)
    actual = run_spec(spec, ohlc, engine="vectorbt", run_id="actual")

    from notebooks.strategy_bench import run_permutation

    permutation = run_permutation(spec, ohlc, n_trials=20)

    assert permutation.real_metric == pytest.approx(total_return(actual.equity))


def test_permutation_samples_match_trade_count_without_leverage_and_are_seeded():
    idx = pd.bdate_range("2020-01-01", periods=40).tz_localize("UTC")
    bar_returns = pd.Series(np.linspace(-0.02, 0.03, len(idx)), index=idx)
    real_entries = pd.Series(False, index=idx)
    real_entries.iloc[[1, 10, 20]] = True
    evaluator = _single_position_evaluator(bar_returns, holding_period=3)

    first = random_entry_permutation(
        real_entries,
        evaluator=evaluator,
        n_trials=50,
        rng_seed=7,
        max_resamples=200,
    )
    second = random_entry_permutation(
        real_entries,
        evaluator=evaluator,
        n_trials=50,
        rng_seed=7,
        max_resamples=200,
    )

    assert np.all(first.random_completed_trades == first.real_completed_trades)
    assert np.all(first.random_max_exposures <= 1.0)
    np.testing.assert_array_equal(first.random_metrics, second.random_metrics)


def test_permutation_final_bar_entry_remains_unfilled():
    idx = pd.bdate_range("2020-01-01", periods=8).tz_localize("UTC")
    real_entries = pd.Series(False, index=idx)
    real_entries.iloc[-1] = True
    evaluator = _single_position_evaluator(pd.Series(0.10, index=idx), holding_period=1)

    result = random_entry_permutation(real_entries, evaluator=evaluator, n_trials=20)

    assert result.real_completed_trades == 0
    assert result.real_metric == 0.0
    assert result.n_trials == 0


def test_permutation_fails_when_comparable_sample_cannot_be_generated():
    idx = pd.bdate_range("2020-01-01", periods=8).tz_localize("UTC")
    real_entries = pd.Series(False, index=idx)
    real_entries.iloc[1] = True
    calls = 0

    def evaluator(entries: pd.Series):
        nonlocal calls
        calls += 1
        return EntryEvaluation(
            metric=1.0 if calls == 1 else 0.0,
            completed_trades=1 if calls == 1 else 0,
            exposure=pd.Series(0.0, index=entries.index),
        )

    with pytest.raises(ValueError, match="comparable random-entry sample"):
        random_entry_permutation(
            real_entries,
            evaluator=evaluator,
            n_trials=1,
            max_resamples=3,
        )


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


def test_walk_forward_uses_history_for_signals_but_executes_only_oos():
    index = pd.date_range("2024-01-01", periods=8, tz="UTC")
    ohlc = pd.DataFrame({"close": np.arange(8, dtype=float)}, index=index)
    optimized_indexes: list[pd.Index] = []
    oos_calls: list[tuple[pd.Index, pd.Index]] = []

    def optimize(_spec, bars):
        optimized_indexes.append(bars.index)
        return {"period": 3}

    def run_engine(_spec, bars, *, run_id, signal_ohlc=None, **_kwargs):
        if run_id.startswith("wf-oos"):
            oos_calls.append((bars.index, signal_ohlc.index))
        return _backtest_result_mock(pd.Series(np.arange(1, len(bars) + 1), index=bars.index))

    result = walk_forward(
        StrategySpec(
            name="warmup", signal_factory=lambda bars, params: pd.DataFrame(index=bars.index)
        ),
        ohlc,
        run_engine=run_engine,
        optimize=optimize,
        is_windows=[(index[0], index[3])],
        oos_windows=[(index[3], index[6])],
    )

    assert optimized_indexes[0].equals(index[:3])
    assert oos_calls[0][0].equals(index[3:6])
    assert oos_calls[0][1].equals(index[:6])
    assert result.oos_equity.index.equals(index[3:6])


def test_walk_forward_accepts_adjacent_oos_windows_and_sorts_output():
    index = pd.date_range("2024-01-01", periods=8, tz="UTC")
    ohlc = pd.DataFrame({"close": np.arange(8, dtype=float)}, index=index)

    def run_engine(_spec, bars, **_kwargs):
        equity = pd.Series(np.arange(1, len(bars) + 1), index=bars.index[::-1])
        return _backtest_result_mock(equity)

    result = walk_forward(
        StrategySpec(
            name="adjacent", signal_factory=lambda bars, params: pd.DataFrame(index=bars.index)
        ),
        ohlc,
        run_engine=run_engine,
        optimize=lambda _spec, _bars: {},
        is_windows=[(index[1], index[4]), (index[0], index[2])],
        oos_windows=[(index[4], index[6]), (index[2], index[4])],
    )

    assert result.oos_equity.index.equals(index[2:6])
    assert result.oos_equity.index.is_unique
    assert result.oos_intervals == [(index[2], index[4]), (index[4], index[6])]


def test_walk_forward_rejects_overlapping_oos_windows():
    index = pd.date_range("2024-01-01", periods=8, tz="UTC")
    ohlc = pd.DataFrame({"close": np.arange(8, dtype=float)}, index=index)

    with pytest.raises(ValueError, match="OOS windows must not overlap"):
        walk_forward(
            StrategySpec(
                name="overlap", signal_factory=lambda bars, params: pd.DataFrame(index=bars.index)
            ),
            ohlc,
            run_engine=lambda *_args, **_kwargs: None,
            optimize=lambda _spec, _bars: {},
            is_windows=[(index[0], index[2]), (index[1], index[3])],
            oos_windows=[(index[2], index[5]), (index[4], index[6])],
        )


def test_walk_forward_rejects_duplicate_stitched_dates():
    index = pd.date_range("2024-01-01", periods=6, tz="UTC")
    ohlc = pd.DataFrame({"close": np.arange(6, dtype=float)}, index=index)

    def run_engine(_spec, bars, *, run_id, **_kwargs):
        equity_index = (
            bars.index if run_id.startswith("wf-is") else bars.index.insert(1, bars.index[0])
        )
        return _backtest_result_mock(
            pd.Series(np.arange(1, len(equity_index) + 1), index=equity_index)
        )

    with pytest.raises(ValueError, match="duplicate OOS equity dates"):
        walk_forward(
            StrategySpec(
                name="duplicate", signal_factory=lambda bars, params: pd.DataFrame(index=bars.index)
            ),
            ohlc,
            run_engine=run_engine,
            optimize=lambda _spec, _bars: {},
            is_windows=[(index[0], index[3])],
            oos_windows=[(index[3], index[-1] + pd.Timedelta(days=1))],
        )
