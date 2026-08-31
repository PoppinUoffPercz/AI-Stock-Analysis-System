from __future__ import annotations

import pandas as pd
import pytest

from backtest_engine.execution.costs import PRESETS
from backtest_engine.strategy.adapters.bt_adapter import BTAdapter
from backtest_engine.strategy.adapters.vbt_adapter import VBTAdapter


def _round_trip_fixture(*, entry_open: float = 100.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    index = pd.date_range("2024-01-02", periods=4, freq="D", tz="UTC")
    opens = [10.0, entry_open, 100.0, 100.0]
    ohlc = pd.DataFrame(
        {
            "open": opens,
            "high": [value + 1.0 for value in opens],
            "low": [value - 1.0 for value in opens],
            "close": opens,
            "volume": [1_000_000.0] * 4,
        },
        index=index,
    )
    ohlc.attrs["symbol"] = "CONTRACT"
    signals = pd.DataFrame(
        {"entry": [True, False, False, False], "exit": [False, False, True, False]},
        index=index,
    )
    return ohlc, signals


def _run(adapter, ohlc, signals, cost_model="zero"):
    return adapter.run(
        signals,
        ohlc,
        capital=1_000.0,
        cost_model=cost_model,
        strategy_name="contract",
        universe_ref="CONTRACT",
        params={},
        run_id=f"{adapter.name}-{cost_model}",
    )


def test_cost_presets_include_proportional_commission():
    model = PRESETS["us_equity_proportional"]
    assert model.commission(10.0, 100.0) == pytest.approx(1.0)


@pytest.mark.parametrize("cost_model", ["us_equity_flat", "us_equity_proportional"])
def test_vbt_reported_commission_reconciles_with_equity(cost_model):
    ohlc, signals = _round_trip_fixture()
    zero = _run(VBTAdapter(), ohlc, signals)
    costly = _run(VBTAdapter(), ohlc, signals, cost_model)

    assert len(costly.trades) == 1
    reported = sum(trade.commission + trade.slippage_cost for trade in costly.trades)
    assert reported > 0.0
    assert zero.final_equity - costly.final_equity == pytest.approx(reported, abs=0.02)


def test_vbt_reported_slippage_reconciles_with_equity():
    ohlc, signals = _round_trip_fixture()
    zero = _run(VBTAdapter(), ohlc, signals)
    costly = _run(VBTAdapter(), ohlc, signals, "us_equity_flat")

    trade = costly.trades[0]
    assert trade.slippage_cost > 0.0
    assert zero.final_equity - costly.final_equity == pytest.approx(
        trade.commission + trade.slippage_cost,
        abs=0.02,
    )


def test_backtrader_emits_one_completed_round_trip():
    ohlc, signals = _round_trip_fixture()
    result = _run(BTAdapter(), ohlc, signals)

    assert result.n_trades == 1
    trade = result.trades[0]
    assert trade.timestamp == ohlc.index[1]
    assert trade.exit_timestamp == ohlc.index[3]


def test_backtrader_sizes_at_execution_open_after_overnight_gap():
    ohlc, signals = _round_trip_fixture(entry_open=200.0)
    result = _run(BTAdapter(), ohlc, signals)

    assert result.n_trades == 1
    assert result.trades[0].quantity == 4.0
    assert result.trades[0].fill_price == 200.0


def test_cross_engine_trade_count_and_gap_quantity_agree():
    ohlc, signals = _round_trip_fixture(entry_open=200.0)
    vbt = _run(VBTAdapter(), ohlc, signals)
    bt = _run(BTAdapter(), ohlc, signals)

    assert vbt.n_trades == bt.n_trades == 1
    assert vbt.trades[0].quantity == bt.trades[0].quantity == 4.0
