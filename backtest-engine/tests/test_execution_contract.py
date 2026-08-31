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


def _assert_cost_accounting(result, cost_addback_final_equity):
    commission = sum(trade.commission for trade in result.trades)
    slippage = sum(trade.slippage_cost for trade in result.trades)
    total = commission + slippage

    assert result.metadata["cost_fidelity"] == "exact"
    assert result.metadata["total_commission"] == pytest.approx(commission)
    assert result.metadata["total_slippage"] == pytest.approx(slippage)
    assert result.metadata["total_execution_cost"] == pytest.approx(total)
    assert result.metadata["cost_addback_final_equity"] == pytest.approx(cost_addback_final_equity)
    assert result.metadata["net_final_equity"] == pytest.approx(result.final_equity)
    assert result.metadata["cost_addback_final_equity"] - result.metadata[
        "net_final_equity"
    ] == pytest.approx(total)
    expected_returns = result.equity.pct_change().fillna(0.0)
    pd.testing.assert_series_equal(result.returns, expected_returns)


def test_cost_presets_include_proportional_commission():
    model = PRESETS["us_equity_proportional"]
    assert model.commission(10.0, 100.0) == pytest.approx(1.0)


@pytest.mark.parametrize("cost_model", ["us_equity_flat", "us_equity_pershare"])
def test_vbt_rejects_cost_presets_with_unrepresentable_volume_impact(cost_model):
    ohlc, signals = _round_trip_fixture()

    with pytest.raises(ValueError, match="cannot represent.*exactly"):
        _run(VBTAdapter(), ohlc, signals, cost_model)


@pytest.mark.parametrize("adapter_type", [VBTAdapter, BTAdapter])
@pytest.mark.parametrize("cost_model", ["zero", "us_equity_proportional"])
def test_exact_cost_metadata_and_returns_reconcile(adapter_type, cost_model):
    ohlc, signals = _round_trip_fixture()
    result = _run(adapter_type(), ohlc, signals, cost_model)

    _assert_cost_accounting(result, cost_addback_final_equity=1_000.0)


def test_backtrader_flat_commission_and_volume_slippage_are_exact():
    ohlc, signals = _round_trip_fixture()
    result = _run(BTAdapter(), ohlc, signals, "us_equity_flat")

    trade = result.trades[0]
    expected_slippage = 2 * (9 * 100.0 * (1.0 + 20.0 * 9 / 1_000_000.0) / 1e4)
    assert trade.commission == pytest.approx(2.0)
    assert trade.slippage_cost == pytest.approx(expected_slippage)
    _assert_cost_accounting(result, cost_addback_final_equity=1_000.0)


@pytest.mark.parametrize("adapter_type", [VBTAdapter, BTAdapter])
def test_costly_open_position_is_preserved_without_inventing_an_exit(adapter_type):
    ohlc, signals = _round_trip_fixture()
    signals["exit"] = False

    result = _run(adapter_type(), ohlc, signals, "us_equity_proportional")

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_timestamp is None
    assert trade.exit_price is None
    assert trade.commission == pytest.approx(0.9)
    assert trade.slippage_cost == 0.0
    _assert_cost_accounting(result, cost_addback_final_equity=1_000.0)


def test_cost_aware_sizing_preserves_cross_engine_parity():
    ohlc, signals = _round_trip_fixture(entry_open=90.0)

    vbt = _run(VBTAdapter(), ohlc, signals, "us_equity_proportional")
    bt = _run(BTAdapter(), ohlc, signals, "us_equity_proportional")

    assert vbt.trades[0].quantity == 10.0
    assert bt.trades[0].quantity == 10.0
    assert vbt.metadata["cost_addback_final_equity"] == pytest.approx(
        vbt.final_equity + vbt.metadata["total_execution_cost"]
    )
    assert bt.metadata["cost_addback_final_equity"] == pytest.approx(
        bt.final_equity + bt.metadata["total_execution_cost"]
    )


@pytest.mark.parametrize("cost_model", ["zero", "us_equity_proportional"])
def test_cross_engine_cost_parity_when_semantics_are_equivalent(cost_model):
    ohlc, signals = _round_trip_fixture()
    vbt = _run(VBTAdapter(), ohlc, signals, cost_model)
    bt = _run(BTAdapter(), ohlc, signals, cost_model)

    assert vbt.trades[0].quantity == bt.trades[0].quantity
    assert vbt.metadata["total_commission"] == pytest.approx(bt.metadata["total_commission"])
    assert vbt.metadata["total_slippage"] == pytest.approx(bt.metadata["total_slippage"])
    assert vbt.final_equity == pytest.approx(bt.final_equity)


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
