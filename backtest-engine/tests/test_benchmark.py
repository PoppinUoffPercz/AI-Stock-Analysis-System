from __future__ import annotations

import json

import pandas as pd
import pytest

from backtest_engine.benchmark import attach_buy_and_hold_benchmark
from backtest_engine.metrics.tearsheet import ReportConfig, render_report
from backtest_engine.pipeline import discovery
from backtest_engine.strategy.persistence import load_result
from backtest_engine.strategy.result import BacktestResult, TradeRecord
from backtest_engine.strategy.spec import StrategySpec


def _result(symbols: list[str] | None = None) -> BacktestResult:
    index = pd.date_range("2024-01-02", periods=3, tz="UTC")
    return BacktestResult(
        run_id="benchmark-run",
        strategy_name="sma_cross",
        engine="vectorbt",
        params={"fast": 2, "slow": 3},
        capital=100.0,
        cost_model="us_equity_flat",
        universe_ref="fixture",
        equity=pd.Series([100.0, 105.0, 108.0], index=index),
        returns=pd.Series([0.0, 0.05, 108 / 105 - 1], index=index),
        trades=[
            TradeRecord(index[0], "TEST", "LONG", 1.0, 100.0, 1.0, 1.0),
        ],
        metadata={
            "symbols": symbols or ["TEST"],
            "total_commission": 1.0,
            "total_slippage": 1.0,
            "total_execution_cost": 2.0,
            "net_final_equity": 108.0,
            "cost_addback_final_equity": 110.0,
        },
    )


def _ohlc() -> pd.DataFrame:
    index = pd.date_range("2024-01-02", periods=3, tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0, 105.0, 110.0],
            "high": [106.0, 111.0, 122.0],
            "low": [99.0, 104.0, 109.0],
            "close": [105.0, 110.0, 120.0],
            "volume": [1000.0, 1000.0, 1000.0],
        },
        index=index,
    )


def test_buy_and_hold_uses_first_open_to_final_close_and_labels_strategy_returns():
    result = _result()

    benchmark = attach_buy_and_hold_benchmark(result, _ohlc())

    assert {key: benchmark[key] for key in ("status", "identity", "start", "end")} == {
        "status": "available",
        "identity": "TEST buy-and-hold (first available open to final close; no costs)",
        "start": "2024-01-02T00:00:00+00:00",
        "end": "2024-01-04T00:00:00+00:00",
    }
    assert benchmark["total_return"] == pytest.approx(0.2)
    assert benchmark["strategy_cost_addback_return"] == pytest.approx(0.1)
    assert benchmark["strategy_net_return"] == pytest.approx(0.08)
    assert benchmark["relative_net_performance"] == pytest.approx(-0.12)
    assert result.metadata["benchmark"] == benchmark


def test_multi_symbol_benchmark_is_explicitly_unavailable():
    result = _result(["AAA", "BBB"])

    benchmark = attach_buy_and_hold_benchmark(result, _ohlc())

    assert benchmark["status"] == "unavailable"
    assert benchmark["reason"] == "buy-and-hold benchmark requires exactly one symbol"


def test_run_spec_attaches_benchmark_to_library_results(monkeypatch):
    class Adapter:
        def run(self, *args, **kwargs):
            return _result()

    monkeypatch.setattr(discovery, "get_adapter", lambda name: Adapter())
    monkeypatch.setattr(discovery, "build_manifest", lambda **kwargs: None)
    ohlc = _ohlc()
    ohlc.attrs["symbol"] = "TEST"
    spec = type(
        "Spec",
        (),
        {
            "cost_model": "zero",
            "capital": 100.0,
            "params": {},
            "name": "test",
            "universe_ref": "fixture",
            "signal_factory": staticmethod(lambda frame, params: frame),
            "make_signals": lambda self, frame, params: frame,
        },
    )()

    result = discovery.run_spec(spec, ohlc)

    assert result.metadata["benchmark"]["total_return"] == pytest.approx(0.2)


def test_run_spec_gross_return_matches_zero_cost_replay_not_cost_addback():
    index = pd.date_range("2024-01-01", periods=7, tz="UTC")
    prices = [10.0, 10.0, 20.0, 20.0, 10.0, 10.0, 20.0]
    ohlc = pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1_000_000.0] * len(index),
        },
        index=index,
    )
    ohlc.attrs["symbol"] = "TEST"

    def make_signals(frame, _params):
        return pd.DataFrame(
            {
                "entry": [True, False, False, True, False, False, False],
                "exit": [False, True, False, False, True, False, False],
            },
            index=frame.index,
        )

    spec = StrategySpec("compound", make_signals, capital=1_000.0)
    costly = discovery.run_spec(spec, ohlc, cost_model="us_equity_proportional")
    zero = discovery.run_spec(spec, ohlc, cost_model="zero")

    expected_gross = zero.final_equity / zero.capital - 1.0
    addback = (costly.final_equity + costly.metadata["total_execution_cost"]) / costly.capital - 1.0
    assert costly.metadata["strategy_gross_return"] == pytest.approx(expected_gross)
    assert costly.metadata["benchmark"]["strategy_gross_return"] == pytest.approx(expected_gross)
    assert costly.metadata["strategy_gross_return"] != pytest.approx(addback)


def test_report_persists_benchmark_before_metrics_and_index(tmp_path):
    result = _result()
    attach_buy_and_hold_benchmark(result, _ohlc())

    report = render_report(
        result,
        ReportConfig(
            run_id=result.run_id,
            outputs_dir=tmp_path,
            write_quantstats=False,
            write_plotly=False,
        ),
    )

    loaded = load_result(report.out_dir / "result.json")
    metrics = json.loads((report.out_dir / "metrics.json").read_text())
    index = json.loads((tmp_path / "experiments.jsonl").read_text().splitlines()[0])
    assert loaded.metadata["benchmark"]["total_return"] == pytest.approx(0.2)
    assert metrics["benchmark_total_return"] == pytest.approx(0.2)
    assert metrics["strategy_cost_addback_return"] == pytest.approx(0.1)
    assert metrics["strategy_net_return"] == pytest.approx(0.08)
    assert metrics["relative_net_performance"] == pytest.approx(-0.12)
    assert index["benchmark"]["total_return"] == pytest.approx(0.2)
    assert "Benchmark" in report.html_path.read_text()
