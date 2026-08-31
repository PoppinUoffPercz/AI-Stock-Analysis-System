"""Canonical BacktestResult persistence tests."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from backtest_engine.strategy.persistence import load_result, persist_result
from backtest_engine.strategy.result import BacktestResult, TradeRecord, validate_backtest_result


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


def _set_series_value(result: BacktestResult, field_name: str, value: float) -> None:
    series = getattr(result, field_name).copy()
    series.iloc[1] = value
    setattr(result, field_name, series)


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


def test_irregular_result_round_trip(tmp_path):
    result = _result()
    irregular = pd.DatetimeIndex(
        ["2024-01-01T14:30:00Z", "2024-01-03T15:15:00Z", "2024-01-09T20:00:00Z"]
    )
    result.equity.index = irregular
    result.returns.index = irregular
    result.trades[0].timestamp = irregular[0]
    result.trades[0].exit_timestamp = irregular[-1]

    loaded = load_result(persist_result(result, tmp_path))

    pd.testing.assert_index_equal(loaded.equity.index, irregular)
    pd.testing.assert_index_equal(loaded.returns.index, irregular)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda result: setattr(result, "run_id", ""), "run_id"),
        (lambda result: setattr(result, "capital", np.inf), "capital"),
        (lambda result: _set_series_value(result, "equity", np.nan), "equity"),
        (lambda result: _set_series_value(result, "returns", np.inf), "returns"),
        (lambda result: result.metrics.__setitem__("sharpe", np.nan), "metrics.sharpe"),
        (lambda result: result.metadata.__setitem__("score", np.inf), "metadata.score"),
        (lambda result: setattr(result.trades[0], "quantity", 0.0), "quantity"),
        (lambda result: setattr(result.trades[0], "fill_price", np.inf), "fill_price"),
        (lambda result: setattr(result.trades[0], "commission", -1.0), "commission"),
        (lambda result: setattr(result.trades[0], "side", "BUY"), "side"),
        (lambda result: setattr(result.trades[0], "symbol", ""), "symbol"),
    ],
)
def test_validator_rejects_invalid_result_values(mutation, message):
    result = _result()
    mutation(result)

    with pytest.raises(ValueError, match=message):
        validate_backtest_result(result)


@pytest.mark.parametrize(
    "index",
    [
        pd.DatetimeIndex(["2024-01-02T00:00:00Z", "2024-01-01T00:00:00Z", "2024-01-03T00:00:00Z"]),
        pd.DatetimeIndex(["2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z", "2024-01-03T00:00:00Z"]),
    ],
)
def test_validator_rejects_noncanonical_index_order(index):
    result = _result()
    result.equity.index = index
    result.returns.index = index

    with pytest.raises(ValueError, match="equity index"):
        validate_backtest_result(result)


def test_validator_rejects_equity_return_index_mismatch():
    result = _result()
    result.returns.index = result.returns.index + pd.Timedelta(hours=1)

    with pytest.raises(ValueError, match="exactly align"):
        validate_backtest_result(result)


def test_validator_rejects_naive_datetime_index():
    result = _result()
    result.equity.index = result.equity.index.tz_localize(None)
    result.returns.index = result.returns.index.tz_localize(None)

    with pytest.raises(ValueError, match="timezone-aware UTC"):
        validate_backtest_result(result)


def test_validator_rejects_nonfinite_numeric_nested_in_list():
    result = _result()
    result.raw_metrics = {"third_party": [{"score": np.nan}]}

    with pytest.raises(ValueError, match=r"raw_metrics.third_party\[0\].score"):
        validate_backtest_result(result)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda trade, index: setattr(trade, "exit_timestamp", index[0] - pd.Timedelta(days=1)),
        lambda trade, index: setattr(trade, "exit_price", None),
        lambda trade, index: setattr(trade, "timestamp", index[0] + pd.Timedelta(hours=1)),
    ],
)
def test_validator_rejects_invalid_trade_linkage(mutation):
    result = _result()
    mutation(result.trades[0], result.equity.index)

    with pytest.raises(ValueError, match=r"trade\[0\]"):
        validate_backtest_result(result)


def test_validator_rejects_inconsistent_cost_metadata():
    result = _result()
    result.metadata.update(
        total_commission=1.0,
        total_slippage=0.5,
        total_execution_cost=2.0,
        net_final_equity=result.final_equity,
        cost_addback_final_equity=result.final_equity + 2.0,
    )

    with pytest.raises(ValueError, match="total_execution_cost"):
        validate_backtest_result(result)


def test_validator_rejects_standalone_inconsistent_total_execution_cost():
    result = _result()
    result.metadata["total_execution_cost"] = 99.0

    with pytest.raises(ValueError, match="total_execution_cost"):
        validate_backtest_result(result)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("data_source", ""),
        ("cost_fidelity", " "),
        ("date_range", {"start": "bad", "end": "2024-01-03T00:00:00Z"}),
    ],
)
def test_validator_rejects_malformed_known_metadata(field_name, value):
    result = _result()
    result.metadata[field_name] = value

    with pytest.raises(ValueError, match=f"metadata.{field_name}"):
        validate_backtest_result(result)


def test_persist_result_validates_before_creating_output(tmp_path):
    result = _result()
    result.capital = np.nan

    with pytest.raises(ValueError, match="capital"):
        persist_result(result, tmp_path)

    assert not (tmp_path / "result.json").exists()


def test_persist_result_rejects_nested_nonfinite_json_value(tmp_path):
    result = _result()
    result.params = {"grid": [1.0, np.nan]}

    with pytest.raises(ValueError, match="non-finite JSON value"):
        persist_result(result, tmp_path)

    assert not (tmp_path / "result.json").exists()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.pop("capital"), "capital"),
        (lambda payload: payload["equity"].update(values="bad"), "equity"),
        (lambda payload: payload["returns"]["values"][0].update(timestamp="not-a-date"), "returns"),
        (lambda payload: payload["equity"]["values"][0].update(value="NaN"), "equity"),
    ],
)
def test_load_result_rejects_corrupt_fields_with_value_error(tmp_path, mutate, message):
    path = persist_result(_result(), tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_result(path)


def test_load_result_rejects_invalid_json(tmp_path):
    path = tmp_path / "result.json"
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid JSON"):
        load_result(path)
