"""Run a deterministic representative VectorBT runtime benchmark."""

from __future__ import annotations

import json
import platform
import sys
from importlib.metadata import version
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd

from backtest_engine.pipeline.discovery import run_spec
from backtest_engine.strategy.registry import get_strategy
from backtest_engine.strategy.spec import StrategySpec

SEED = 20260829
ROWS = 756


def run_benchmark() -> dict[str, Any]:
    rng = np.random.default_rng(SEED)
    index = pd.bdate_range("2020-01-02", periods=ROWS, tz="UTC")
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, ROWS)))
    ohlc = pd.DataFrame(
        {
            "open": close * (1.0 + rng.normal(0.0, 0.001, ROWS)),
            "high": close * (1.0 + rng.uniform(0.001, 0.008, ROWS)),
            "low": close * (1.0 - rng.uniform(0.001, 0.008, ROWS)),
            "close": close,
            "volume": rng.integers(500_000, 2_000_000, ROWS).astype(float),
        },
        index=index,
    )
    ohlc.attrs["symbol"] = "BENCH"
    factory, params = get_strategy("sma_cross")
    spec = StrategySpec(
        name="sma_cross",
        signal_factory=factory,
        cost_model="us_equity_proportional",
        capital=100_000.0,
        universe_ref="benchmark-fixed-universe",
        params=params,
    )

    started = perf_counter()
    result = run_spec(
        spec,
        ohlc,
        engine="vectorbt",
        run_id="runtime-benchmark",
        random_seed=SEED,
        relevant_args={"command": "python -m scripts.benchmark_runtime"},
        dataset_identity={"kind": "deterministic_generated", "symbol": "BENCH"},
    )
    elapsed = perf_counter() - started

    return {
        "elapsed_seconds": elapsed,
        "workload": {
            "seed": SEED,
            "rows": ROWS,
            "symbol": "BENCH",
            "start": index[0].isoformat(),
            "end": index[-1].isoformat(),
            "strategy": spec.name,
            "engine": result.engine,
            "cost_model": result.cost_model,
            "capital": spec.capital,
            "params": params,
        },
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "dependencies": {
                package: version(package)
                for package in ("backtest-engine", "numpy", "pandas", "vectorbt")
            },
        },
        "result": {
            "bars": len(result.equity),
            "trades": result.n_trades,
            "engine": result.engine,
            "cost_fidelity": result.metadata["cost_fidelity"],
            "final_equity": result.final_equity,
        },
    }


def main() -> int:
    print(json.dumps(run_benchmark(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
