"""Run the checked-in, deterministic, network-free end-to-end demo."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path
from typing import Any

from backtest_engine import cli
from backtest_engine.data.ingest import ingest_symbol
from backtest_engine.data.universe import Universe
from backtest_engine.experiment_index import ExperimentIndex
from backtest_engine.metrics.tearsheet import ReportConfig, render_report
from backtest_engine.pipeline.discovery import run_spec
from backtest_engine.strategy.persistence import load_result
from backtest_engine.strategy.registry import get_strategy
from backtest_engine.strategy.spec import StrategySpec

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "offline_demo"
RUNS = ("offline-zero", "offline-proportional")


def run_demo(output_root: Path) -> dict[str, Any]:
    output_root = Path(output_root)
    data_root = output_root / "data"
    fixture = FIXTURES / "bars.csv"
    universe_path = FIXTURES / "universe.csv"
    rows, _ = ingest_symbol(
        "DEMO",
        source="csv",
        clean_root=data_root / "clean",
        universe_root=data_root / "universe",
        cross_check=False,
        input_path=fixture,
    )
    ohlc = cli._clean_ohlc("DEMO", data_root=data_root, start=None, end=None)
    eligible = Universe.from_csv(universe_path).filter_panel(ohlc)
    factory, _ = get_strategy("sma_cross")
    params = {"fast": 3, "slow": 8}
    results = []
    for run_id, cost_model in zip(RUNS, ("zero", "us_equity_proportional"), strict=True):
        spec = StrategySpec(
            name="sma_cross",
            signal_factory=factory,
            cost_model=cost_model,
            capital=100_000.0,
            universe_ref=str(universe_path),
            params=params,
        )
        result = run_spec(
            spec,
            ohlc,
            engine="vectorbt",
            run_id=run_id,
            universe=universe_path,
            random_seed=20260829,
            relevant_args={"command": "python -m scripts.run_offline_demo"},
            dataset_identity={"kind": "checked_in_csv", "symbol": "DEMO"},
        )
        result.metadata.update(
            {
                "symbols": ["DEMO"],
                "date_range": {
                    "start": eligible.index[0].isoformat(),
                    "end": eligible.index[-1].isoformat(),
                },
                "data_source": str(fixture),
                "universe_csv": str(universe_path),
            }
        )
        render_report(
            result,
            ReportConfig(
                run_id=run_id,
                outputs_dir=output_root,
                write_quantstats=False,
                write_plotly=False,
            ),
        )
        results.append(result)

    loaded = [load_result(output_root / run_id / "result.json") for run_id in RUNS]
    index = ExperimentIndex(output_root / "experiments.jsonl")
    comparison_stdout = io.StringIO()
    with contextlib.redirect_stdout(comparison_stdout):
        compare_rc = cli.main(
            [
                "compare",
                "--run-id",
                RUNS[0],
                "--run-id",
                RUNS[1],
                "--outputs-root",
                str(output_root),
                "--json",
            ]
        )
    comparison = json.loads(comparison_stdout.getvalue()) if compare_rc == 0 else []
    proportional = results[1]
    checks = {
        "ingested_fixture": rows == 80 and len(ohlc) == 80,
        "point_in_time_universe": len(eligible) == 70 and len(results[0].equity) == 70,
        "strategy_and_signals": all(result.n_trades > 0 for result in results),
        "exact_execution_costs": proportional.metadata.get("cost_fidelity") == "exact"
        and proportional.metadata.get("total_execution_cost", 0.0) > 0.0,
        "benchmark": all(
            result.metadata.get("benchmark", {}).get("status") == "available" for result in results
        ),
        "persisted_result_and_manifest": all(
            (output_root / run_id / "result.json").is_file()
            and (output_root / run_id / "manifest.json").is_file()
            for run_id in RUNS
        ),
        "reload": [result.run_id for result in loaded] == list(RUNS),
        "experiment_index": [index.get(run_id)["run_id"] for run_id in RUNS] == list(RUNS),
        "compare": compare_rc == 0 and [row["run_id"] for row in comparison] == list(RUNS),
        "offline_report": all((output_root / run_id / "report.html").is_file() for run_id in RUNS)
        and not any((output_root / run_id / "tearsheet.html").exists() for run_id in RUNS),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "fixture_rows": rows,
        "eligible_rows": len(eligible),
        "runs": list(RUNS),
        "comparison_rows": len(comparison),
        "output_root": str(output_root.resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("outputs/offline-demo"))
    args = parser.parse_args()
    try:
        report = run_demo(args.output_root)
    except Exception as exc:  # noqa: BLE001 - acceptance command must report failure
        report = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
