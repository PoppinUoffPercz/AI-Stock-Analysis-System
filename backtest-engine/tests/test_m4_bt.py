"""M4 tests: Backtrader adapter end-to-end + signal-driven portability smoke.

Run on synthetic OHLC. No network. The key assertion: BTAdapter produces a
BacktestResult whose equity/returns align to UTC and whose trades carry our
CostModel commission + slippage cost fields.
"""

from __future__ import annotations

from types import SimpleNamespace

import backtrader as bt
import numpy as np
import pandas as pd
import pytest

from backtest_engine.strategy.adapters.bt_adapter import BTAdapter, _SignalDrivenStrategy
from backtest_engine.strategy.builtin import sma_cross


def _synth_ohlc(n: int = 300, start: str = "2018-01-02", seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    rets = 0.0005 + rng.normal(0, 0.01, n)
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


@pytest.mark.smoke
def test_bt_adapter_runs_and_emits_canonical_result():
    pytest.importorskip("backtrader")
    ohlc = _synth_ohlc()
    signals = sma_cross(ohlc, {"fast": 5, "slow": 30})
    adapter = BTAdapter()
    result = adapter.run(
        signals,
        ohlc,
        capital=100_000.0,
        cost_model="zero",
        strategy_name="sma_cross",
        universe_ref="SYNTH",
        params={"fast": 5, "slow": 30},
        run_id="m4-test",
    )
    assert result.engine == "backtrader"
    assert result.capital == 100_000.0
    # Equity series non-empty and tz-aware UTC
    assert not result.equity.empty
    assert result.equity.index.tz is not None
    assert str(result.equity.index.tz) == "UTC"
    # Returns aligned to equity
    assert len(result.returns) == len(result.equity)
    # Trades list may be empty on certain seeds; assert each carries correct fields
    for tr in result.trades:
        assert tr.side in {"LONG", "EXIT"}
        assert tr.quantity >= 0
        assert tr.fill_price > 0
        assert tr.commission >= 0
        assert tr.slippage_cost >= 0


@pytest.mark.smoke
def test_bt_adapter_zero_cost_keeps_equity_near_buy_and_hold_when_always_long():
    pytest.importorskip("backtrader")
    # Force a permanent-long signal: entry=True at bar 0, no exits.
    ohlc = _synth_ohlc(n=60, seed=99)
    signals = pd.DataFrame(
        {"entry": [True] + [False] * 59, "exit": [False] * 60},
        index=ohlc.index,
    )
    adapter = BTAdapter()
    result = adapter.run(
        signals,
        ohlc,
        capital=100_000.0,
        cost_model="zero",
        strategy_name="hold",
        universe_ref="SYNTH",
        params={},
        run_id="hold",
    )
    # The equity should track close * n_shares, roughly the buy-hold curve.
    close_norm = ohlc["close"] / ohlc["close"].iloc[0]
    bh_final = 100_000 * close_norm.iloc[-1]
    # Tolerance: backtrader fills at next bar open (1-bar lag), so the equity at
    # the final close reflects the *prior* bar's close × n_shares roughly.
    assert result.final_equity > 0
    rel_diff = abs(result.final_equity - bh_final) / bh_final
    assert rel_diff < 0.15, f"final_equity={result.final_equity:.2f} vs bh_final={bh_final:.2f}"


@pytest.mark.smoke
def test_bt_adapter_does_not_record_final_bar_order():
    pytest.importorskip("backtrader")
    idx = pd.date_range("2024-01-02", periods=3, freq="D", tz="UTC")
    ohlc = pd.DataFrame(
        {
            "open": [100.0, 200.0, 300.0],
            "high": [101.0, 201.0, 301.0],
            "low": [99.0, 199.0, 299.0],
            "close": [100.0, 200.0, 300.0],
            "volume": [1000.0] * 3,
        },
        index=idx,
    )
    signals = pd.DataFrame(
        {"entry": [False, False, True], "exit": [False, False, False]},
        index=idx,
    )
    ohlc.attrs["symbol"] = "FINAL"

    result = BTAdapter().run(
        signals,
        ohlc,
        capital=1_000.0,
        cost_model="zero",
        strategy_name="final-bar",
        universe_ref="FINAL",
        params={},
        run_id="final-bar",
    )

    assert result.trades == []


@pytest.mark.smoke
def test_bt_adapter_records_each_completed_order_with_execution_data():
    pytest.importorskip("backtrader")
    idx = pd.date_range("2024-01-02", periods=4, freq="D", tz="UTC")
    ohlc = pd.DataFrame(
        {
            "open": [100.0, 10.0, 20.0, 30.0],
            "high": [101.0, 11.0, 21.0, 31.0],
            "low": [99.0, 9.0, 19.0, 29.0],
            "close": [100.0, 10.0, 20.0, 30.0],
            "volume": [1000.0] * 4,
        },
        index=idx,
    )
    signals = pd.DataFrame(
        {"entry": [True, False, False, False], "exit": [False, False, True, False]},
        index=idx,
    )
    ohlc.attrs["symbol"] = "EXECUTED"

    result = BTAdapter().run(
        signals,
        ohlc,
        capital=1_000.0,
        cost_model="zero",
        strategy_name="executed",
        universe_ref="EXECUTED",
        params={},
        run_id="executed",
    )

    assert len(result.trades) == 2
    entry, exit_ = result.trades
    assert (entry.timestamp, entry.quantity, entry.fill_price, entry.side) == (
        idx[1],
        9.0,
        10.0,
        "LONG",
    )
    assert (exit_.timestamp, exit_.quantity, exit_.fill_price, exit_.side) == (
        idx[3],
        9.0,
        30.0,
        "EXIT",
    )


@pytest.mark.parametrize("status", [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected])
def test_bt_adapter_clears_failed_pending_order_without_record(status):
    strategy = object.__new__(_SignalDrivenStrategy)
    strategy._pending_order_ref = 7
    strategy._trade_log = []
    order = SimpleNamespace(
        ref=7,
        status=status,
        Completed=bt.Order.Completed,
        Canceled=bt.Order.Canceled,
        Margin=bt.Order.Margin,
        Rejected=bt.Order.Rejected,
        Expired=bt.Order.Expired,
    )

    strategy.notify_order(order)

    assert strategy._pending_order_ref is None
    assert strategy._trade_log == []


@pytest.mark.smoke
def test_bt_adapter_charges_execution_costs_to_broker_equity():
    pytest.importorskip("backtrader")
    idx = pd.date_range("2024-01-02", periods=4, freq="D", tz="UTC")
    ohlc = pd.DataFrame(
        {
            "open": [100.0] * 4,
            "high": [101.0] * 4,
            "low": [99.0] * 4,
            "close": [100.0] * 4,
            "volume": [1000.0] * 4,
        },
        index=idx,
    )
    signals = pd.DataFrame(
        {"entry": [True, False, False, False], "exit": [False, False, True, False]},
        index=idx,
    )
    ohlc.attrs["symbol"] = "COSTS"
    adapter = BTAdapter()
    zero = adapter.run(
        signals,
        ohlc,
        capital=1_000.0,
        cost_model="zero",
        strategy_name="costs",
        universe_ref="COSTS",
        params={},
        run_id="zero-cost",
    )
    costly = adapter.run(
        signals,
        ohlc,
        capital=1_000.0,
        cost_model="us_equity_flat",
        strategy_name="costs",
        universe_ref="COSTS",
        params={},
        run_id="costly",
    )

    recorded_costs = sum(tr.commission + tr.slippage_cost for tr in costly.trades)
    assert costly.final_equity < zero.final_equity
    assert zero.final_equity == pytest.approx(1_000.0)
    assert recorded_costs > 0.0
    assert zero.final_equity - costly.final_equity == pytest.approx(recorded_costs)
