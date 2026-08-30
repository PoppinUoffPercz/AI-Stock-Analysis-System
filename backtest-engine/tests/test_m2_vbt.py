"""M2 tests: metrics.core + VBTAdapter end-to-end on synthetic data.

No network or library-version pinning beyond vectorbt itself.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest_engine.metrics.core import (
    annualized_return,
    bias_audit,
    calmar,
    compute_metric_panel,
    hit_rate,
    max_drawdown,
    profit_factor,
    sharpe,
    sortino,
    total_return,
)
from backtest_engine.strategy.adapters.vbt_adapter import VBTAdapter
from backtest_engine.strategy.builtin import sma_cross

# --- Synth data helper ---------------------------------------------------


def _synth_ohlc(n: int = 300, start: str = "2018-01-02", drift: float = 0.0005) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    idx = pd.bdate_range(start, periods=n)
    rets = drift + rng.normal(0, 0.01, n)
    px = 100 * np.exp(np.cumsum(rets))
    out = pd.DataFrame(
        {
            "open": px,
            "high": px * (1 + rng.uniform(0, 0.005, n)),
            "low": px * (1 - rng.uniform(0, 0.005, n)),
            "close": px,
            "volume": rng.integers(100_000, 500_000, n).astype(float),
        },
        index=idx.tz_localize("UTC"),
    )
    out.index.name = "timestamp"
    out.attrs["symbol"] = "SYNTH"
    return out


# --- Metric core ---------------------------------------------------------


def _equity(n=300, annual=0.05):
    idx = pd.bdate_range("2018-01-02", periods=n).tz_localize("UTC")
    daily = (1 + annual) ** (1 / 252) - 1
    e = pd.Series(np.cumprod([1 + daily] * n) * 100_000, index=idx)
    return e


def _returns(n=300, mean=0.0005, vol=0.01):
    idx = pd.bdate_range("2018-01-02", periods=n).tz_localize("UTC")
    rng = np.random.default_rng(1)
    return pd.Series(rng.normal(mean, vol, n), index=idx)


def test_total_return_zero_len():
    assert total_return(pd.Series([], dtype=float)) == 0.0


def test_total_return_basic():
    eq = pd.Series(
        [100, 110, 121], index=pd.bdate_range("2020-01-01", periods=3).tz_localize("UTC")
    )
    assert abs(total_return(eq) - 0.21) < 1e-9


def test_annualized_return_one_year():
    eq = _equity(n=252, annual=0.10)
    ar = annualized_return(eq)
    assert abs(ar - 0.10) < 0.005


def test_max_drawdown_returns_negative():
    eq = pd.Series(
        [100, 90, 80, 95, 100], index=pd.bdate_range("2020-01-01", periods=5).tz_localize("UTC")
    )
    mdd, dur = max_drawdown(eq)
    assert mdd == pytest.approx(-0.20, rel=1e-6)
    # lack of monotonicity in peak detection; just confirm dur is Timedelta
    assert dur.days >= 0


def test_sharpe_zero_when_no_volatility():
    r = pd.Series([0.001] * 30, index=pd.bdate_range("2020-01-01", periods=30).tz_localize("UTC"))
    assert sharpe(r) == 0.0


def test_sortino_handles_no_loss_returns():
    r = pd.Series([0.001] * 30, index=pd.bdate_range("2020-01-01", periods=30).tz_localize("UTC"))
    assert sortino(r) == 0.0


def test_calmar_when_no_drawdown_returns_zero():
    eq = pd.Series(
        [100, 101, 102, 103], index=pd.bdate_range("2020-01-01", periods=4).tz_localize("UTC")
    )
    eq = eq.astype(float)  # strictly monotone increasing -> MDD = 0
    eq_rev = pd.Series(np.cumsum([1, 1, 1, 1], dtype=float) + 100, index=eq.index)
    assert calmar(eq_rev) == 0.0


def test_profit_factor_all_wins_infinite():
    r = pd.Series(
        [0.01, 0.02, 0.005], index=pd.bdate_range("2020-01-01", periods=3).tz_localize("UTC")
    )
    assert profit_factor(r) == float("inf")


def test_profit_factor_all_losses_zero():
    r = pd.Series(
        [-0.01, -0.02, -0.005], index=pd.bdate_range("2020-01-01", periods=3).tz_localize("UTC")
    )
    assert profit_factor(r) == 0.0


def test_hit_rate_empty():
    assert hit_rate(pd.Series([], dtype=float)) == 0.0


def test_metric_panel_outputs_canonical_keys():
    eq = pd.Series(
        np.cumprod(1 + np.array([0.0005] * 252 + [-0.001] * 30)) * 100_000,
        index=pd.bdate_range("2020-01-01", periods=282).tz_localize("UTC"),
    )
    r = pd.Series(np.array([0.0005] * 252 + [-0.001] * 30), index=eq.index)
    panel = compute_metric_panel(eq, r, positions=None)
    for key in (
        "total_return",
        "cagr",
        "vol",
        "sharpe",
        "sortino",
        "calmar",
        "max_drawdown",
        "max_drawdown_days",
        "hit_rate",
        "profit_factor",
        "avg_win_loss_ratio",
        "exposure",
        "turnover",
        "n_trades",
    ):
        assert key in panel


def test_bias_audit_flags_high_sharpe():
    metrics = {"sharpe": 2.5, "vol": 0.10, "n_trades": 200, "oos_cagr": 0.05, "is_cagr": 0.1}
    flags = bias_audit(metrics)
    assert flags["high_sharpe"] is True
    assert flags["any_flag"] is True


def test_bias_audit_low_trades():
    metrics = {"sharpe": 0.8, "vol": 0.15, "n_trades": 5}
    flags = bias_audit(metrics)
    assert flags["thin_trades"] is True


# --- VBTAdapter end-to-end smoke ----------------------------------------


@pytest.mark.smoke
def test_vbt_adapter_runs_single_backtest():
    pytest.importorskip("vectorbt")
    ohlc = _synth_ohlc()
    signals = sma_cross(ohlc, {"fast": 5, "slow": 30})
    adapter = VBTAdapter()
    result = adapter.run(
        signals,
        ohlc,
        capital=100_000,
        cost_model="zero",
        strategy_name="sma_cross",
        universe_ref="SYNTH",
        params={"fast": 5, "slow": 30},
        run_id="test-run",
    )
    assert result.engine == "vectorbt"
    assert result.strategy_name == "sma_cross"
    assert result.capital == 100_000
    # Equity starts at the initial capital; has positive length
    assert len(result.equity) > 0
    assert result.equity.iloc[0] == pytest.approx(100_000, rel=1e-3)
    # Returns Series aligned to equity index
    assert len(result.returns) == len(result.equity)


@pytest.mark.smoke
def test_vbt_adapter_fills_signals_at_next_open_and_skips_final_bar():
    pytest.importorskip("vectorbt")
    idx = pd.date_range("2024-01-02", periods=4, freq="D", tz="UTC")
    ohlc = pd.DataFrame(
        {
            "open": [101.0, 250.0, 303.0, 499.0],
            "high": [110.0, 260.0, 310.0, 510.0],
            "low": [99.0, 240.0, 295.0, 490.0],
            "close": [10.0, 20.0, 30.0, 40.0],
            "volume": [1000.0] * 4,
        },
        index=idx,
    )
    signals = pd.DataFrame(
        {
            "entry": [True, False, False, True],
            "exit": [False, False, True, False],
        },
        index=idx,
    )
    ohlc.attrs["symbol"] = "TIMING"

    result = VBTAdapter().run(
        signals,
        ohlc,
        capital=1_000.0,
        cost_model="zero",
        strategy_name="timing",
        universe_ref="TIMING",
        params={},
        run_id="timing",
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.timestamp == idx[1]
    assert trade.fill_price == pytest.approx(250.0)
    assert trade.exit_timestamp == idx[3]
    assert trade.exit_price == pytest.approx(499.0)
    assert result.equity.tolist() == pytest.approx([1_000.0, 80.0, 120.0, 1_996.0])


@pytest.mark.smoke
def test_vbt_adapter_sweep_returns_one_result_per_combo():
    pytest.importorskip("vectorbt")
    ohlc = _synth_ohlc()
    adapter = VBTAdapter()
    results = adapter.sweep(
        sma_cross,
        ohlc,
        param_grid={"fast": [5, 10, 20], "slow": [30, 50]},
        capital=100_000,
        cost_model="zero",
        strategy_name="sma_cross_sweep",
        universe_ref="SYNTH",
    )
    assert len(results) == 6
    # Params dict on each result
    assert all("fast" in r.params and "slow" in r.params for r in results)
    # No duplicate param combinations (fast=fast in (10,10) etc not allowed since fast<slow)
    combos = {(r.params["fast"], r.params["slow"]) for r in results}
    assert len(combos) == 6
