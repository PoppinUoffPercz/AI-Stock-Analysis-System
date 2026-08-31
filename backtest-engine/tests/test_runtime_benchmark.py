from __future__ import annotations

from scripts.benchmark_runtime import run_benchmark


def test_runtime_benchmark_reports_context_and_workload_schema():
    report = run_benchmark()

    assert report["workload"] == {
        "seed": 20260829,
        "rows": 756,
        "symbol": "BENCH",
        "start": "2020-01-02T00:00:00+00:00",
        "end": "2022-11-24T00:00:00+00:00",
        "strategy": "sma_cross",
        "engine": "vectorbt",
        "cost_model": "us_equity_proportional",
        "capital": 100000.0,
        "params": {"fast": 10, "slow": 30},
    }
    assert isinstance(report["elapsed_seconds"], float)
    assert report["elapsed_seconds"] >= 0
    assert set(report["runtime"]) == {"python", "platform", "dependencies"}
    assert set(report["runtime"]["dependencies"]) == {
        "backtest-engine",
        "numpy",
        "pandas",
        "vectorbt",
    }
    assert report["result"]["engine"] == "vectorbt"
    assert report["result"]["cost_fidelity"] == "exact"
    assert report["result"]["bars"] == 756
