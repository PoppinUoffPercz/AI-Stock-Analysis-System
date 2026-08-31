from __future__ import annotations

import json

import pandas as pd
import pytest

from backtest_engine import cli
from backtest_engine.strategy.persistence import persist_result
from backtest_engine.strategy.result import BacktestResult


def _persist(outputs, run_id: str, final: float, benchmark: float) -> None:
    index = pd.date_range("2024-01-01", periods=3, tz="UTC")
    result = BacktestResult(
        run_id=run_id,
        strategy_name="sma_cross",
        engine="vectorbt",
        params={"fast": 5},
        capital=100.0,
        cost_model="zero",
        universe_ref="fixture",
        equity=pd.Series([100.0, 90.0, final], index=index),
        returns=pd.Series([0.0, -0.1, final / 90.0 - 1], index=index),
        metrics={
            "total_return": final / 100.0 - 1,
            "max_drawdown": -0.1,
            "n_trades": 0.0,
            "benchmark_total_return": benchmark,
            "strategy_cost_addback_return": final / 100.0 - 1,
            "strategy_net_return": final / 100.0 - 1,
        },
        metadata={
            "symbols": ["TEST"],
            "date_range": {"start": index[0].isoformat(), "end": index[-1].isoformat()},
            "total_execution_cost": 0.0,
            "benchmark": {"status": "available", "total_return": benchmark},
        },
    )
    persist_result(result, outputs / run_id)


def test_cli_compare_outputs_deterministic_json_for_explicit_runs(tmp_path, capsys):
    outputs = tmp_path / "custom-outputs"
    _persist(outputs, "run-b", 120.0, 0.15)
    _persist(outputs, "run-a", 110.0, 0.15)

    rc = cli.main(
        [
            "compare",
            "--run-id",
            "run-b",
            "--run-id",
            "run-a",
            "--outputs-root",
            str(outputs),
            "--json",
        ]
    )

    assert rc == 0
    rows = json.loads(capsys.readouterr().out)
    assert [row["run_id"] for row in rows] == ["run-b", "run-a"]
    assert list(rows[0]) == [
        "run_id",
        "strategy",
        "params",
        "engine",
        "period",
        "total_return",
        "gross_return",
        "net_return",
        "benchmark",
        "max_drawdown",
        "total_costs",
        "trade_count",
    ]
    assert rows[0]["total_return"] == pytest.approx(0.2)
    assert rows[0]["benchmark"] == pytest.approx(0.15)


def test_cli_compare_reports_missing_and_corrupt_results(tmp_path, capsys):
    outputs = tmp_path / "outputs"
    assert cli.main(["compare", "--run-id", "missing", "--outputs-root", str(outputs)]) == 1
    assert "Missing result artifact for run missing" in capsys.readouterr().err

    bad = outputs / "bad"
    bad.mkdir(parents=True)
    (bad / "result.json").write_text("{broken", encoding="utf-8")
    assert cli.main(["compare", "--run-id", "bad", "--outputs-root", str(outputs)]) == 1
    assert "Invalid result artifact for run bad" in capsys.readouterr().err
