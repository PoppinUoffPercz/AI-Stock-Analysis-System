"""Canonical BacktestResult persistence tests."""

from __future__ import annotations

import pandas as pd

from backtest_engine.strategy.persistence import load_result, persist_result
from backtest_engine.strategy.result import BacktestResult, TradeRecord


def _result() -> BacktestResult:
    index = pd.date_range("2024-01-01", periods=3, tz="UTC")
    return BacktestResult(
        run_id="round-trip",
        strategy_name="sma_cross",
        engine="vectorbt",
        params={"fast": 5, "slow": 20},
        capital=10_000.0,
        cost_model="us_equity_flat",
        universe_ref="data/universe/spx.csv",
        equity=pd.Series([10_000.0, 10_100.0, 10_050.0], index=index),
        returns=pd.Series([0.0, 0.01, -0.004950495], index=index),
        trades=[
            TradeRecord(
                timestamp=index[0],
                symbol="SPY",
                side="LONG",
                quantity=10.0,
                fill_price=100.0,
                commission=1.0,
                slippage_cost=0.5,
                exit_timestamp=index[2],
                exit_price=100.5,
            )
        ],
        raw_metrics={"engine_metric": 1.25},
        metrics={"total_return": 0.005},
        metadata={
            "symbols": ["SPY"],
            "date_range": {"start": index[0].isoformat(), "end": index[-1].isoformat()},
            "data_source": "fixture",
        },
    )


def test_backtest_result_round_trip_preserves_research_fields(tmp_path):
    original = _result()

    path = persist_result(original, tmp_path)
    loaded = load_result(path)

    assert path == tmp_path / "result.json"
    assert loaded.run_id == original.run_id
    assert loaded.strategy_name == original.strategy_name
    assert loaded.engine == original.engine
    assert loaded.params == original.params
    assert loaded.capital == original.capital
    assert loaded.cost_model == original.cost_model
    assert loaded.universe_ref == original.universe_ref
    pd.testing.assert_series_equal(loaded.equity, original.equity)
    pd.testing.assert_series_equal(loaded.returns, original.returns)
    assert loaded.trades == original.trades
    assert loaded.raw_metrics == original.raw_metrics
    assert loaded.metrics == original.metrics
    assert loaded.metadata == original.metadata


def test_persist_result_uses_atomic_json_payload(tmp_path):
    path = persist_result(_result(), tmp_path)
    payload = path.read_text(encoding="utf-8")

    assert '"schema_version": 1' in payload
    assert not list(tmp_path.glob("*.tmp"))
