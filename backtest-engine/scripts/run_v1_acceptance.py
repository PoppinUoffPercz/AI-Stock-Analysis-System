"""Run the bounded real-data v1 acceptance workflow.

The command assumes the clean cache was populated by ``data.ingest``.  It
writes only ignored artifacts under ``outputs/v1-acceptance`` and is separate
from the offline unit-test suite.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from notebooks.strategy_bench import (
    _trade_returns,
    run_monte_carlo,
    run_permutation,
    run_walk_forward,
)

from backtest_engine.config import resolve_settings
from backtest_engine.data.store import read_clean
from backtest_engine.metrics.core import attach_metric_panel, total_return
from backtest_engine.metrics.tearsheet import make_report_config, render_report
from backtest_engine.pipeline.discovery import run_spec
from backtest_engine.strategy.adapters.vbt_adapter import VBTAdapter
from backtest_engine.strategy.persistence import persist_result
from backtest_engine.strategy.registry import get_strategy
from backtest_engine.strategy.spec import StrategySpec

PARAM_GRID = {"fast": [5, 10, 20], "slow": [30, 50]}
SYMBOLS = ("SPY", "QQQ", "IWM")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _summary(result: Any, *, symbol: str, metrics: dict[str, float]) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "engine": result.engine,
        "strategy": result.strategy_name,
        "symbol": symbol,
        "params": result.params,
        "capital": result.capital,
        "cost_model": result.cost_model,
        "universe_ref": result.universe_ref,
        "start": pd.Timestamp(result.equity.index[0]).isoformat(),
        "end": pd.Timestamp(result.equity.index[-1]).isoformat(),
        "final_equity": result.final_equity,
        "n_trades": result.n_trades,
        "metrics": metrics,
    }


def _set_metadata(result: Any, *, symbol: str, data_root: Path, universe_root: Path) -> None:
    result.metadata = {
        "symbols": [symbol],
        "date_range": {
            "start": pd.Timestamp(result.equity.index[0]).isoformat(),
            "end": pd.Timestamp(result.equity.index[-1]).isoformat(),
        },
        "data_source": "persisted_clean_yfinance",
        "data_root": str(data_root),
        "universe_root": str(universe_root),
        "execution": {
            "engine": result.engine,
            "cost_model": result.cost_model,
            "capital": result.capital,
        },
    }


def _write_result(result: Any, directory: Path, *, metrics: dict[str, float]) -> None:
    result.metrics = metrics
    persist_result(result, directory, metrics=metrics)


def run_acceptance(
    *,
    data_root: Path,
    universe_root: Path,
    output_root: Path,
    start: str,
    end: str,
    mc_trials: int,
    permutation_trials: int,
) -> dict[str, Any]:
    factory, defaults = get_strategy("sma_cross")
    spec = StrategySpec(
        name="sma_cross",
        signal_factory=factory,
        cost_model="zero",
        capital=100_000.0,
        universe_ref=str(universe_root),
        params=defaults,
    )
    bars = {
        symbol: read_clean(data_root / "clean", symbol, start=start, end=end)
        .set_index("timestamp")[["open", "high", "low", "close", "volume"]]
        .sort_index()
        for symbol in SYMBOLS
    }
    for symbol, frame in bars.items():
        if frame.empty:
            raise ValueError(f"no cached clean data for {symbol} in {start}..{end}")
        frame.attrs["symbol"] = symbol

    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "results").mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "workflow": "v1-real-acceptance",
        "data_source": "yfinance persisted clean data",
        "symbols": list(SYMBOLS),
        "date_range": {"start": start, "end": end},
        "parameter_grid": PARAM_GRID,
        "cost_model": spec.cost_model,
        "capital": spec.capital,
        "bars": {symbol: len(frame) for symbol, frame in bars.items()},
        "sweep": {},
    }

    for symbol, frame in bars.items():
        sweep_results = VBTAdapter().sweep(
            spec.signal_factory,
            frame,
            param_grid=PARAM_GRID,
            capital=spec.capital,
            cost_model=spec.cost_model,
            strategy_name=spec.name,
            universe_ref=spec.universe_ref,
        )
        sweep_summary = []
        for result in sweep_results:
            _set_metadata(result, symbol=symbol, data_root=data_root, universe_root=universe_root)
            metrics = attach_metric_panel(result)
            label = f"sweep-{symbol}-{result.params['fast']}-{result.params['slow']}"
            _write_result(result, output_root / "results" / label, metrics=metrics)
            sweep_summary.append(_summary(result, symbol=symbol, metrics=metrics))
        report["sweep"][symbol] = sweep_summary

    spy = bars["SPY"]
    sweep = report["sweep"]["SPY"]
    best = max(sweep, key=lambda item: item["metrics"]["total_return"])
    selected_params = dict(best["params"])
    selected_spec = StrategySpec(
        name=spec.name,
        signal_factory=spec.signal_factory,
        cost_model=spec.cost_model,
        capital=spec.capital,
        universe_ref=spec.universe_ref,
        params=selected_params,
    )

    vbt = run_spec(
        selected_spec, spy, engine="vectorbt", params=selected_params, run_id="acceptance-vbt"
    )
    bt = run_spec(
        selected_spec, spy, engine="backtrader", params=selected_params, run_id="acceptance-bt"
    )
    _set_metadata(vbt, symbol="SPY", data_root=data_root, universe_root=universe_root)
    _set_metadata(bt, symbol="SPY", data_root=data_root, universe_root=universe_root)
    vbt_metrics = attach_metric_panel(vbt)
    bt_metrics = attach_metric_panel(bt)
    _write_result(vbt, output_root / "results" / "vectorbt", metrics=vbt_metrics)
    _write_result(bt, output_root / "results" / "backtrader", metrics=bt_metrics)
    report["selected_params"] = selected_params
    report["vectorbt"] = _summary(vbt, symbol="SPY", metrics=vbt_metrics)
    report["backtrader"] = _summary(bt, symbol="SPY", metrics=bt_metrics)
    report["vectorbt_backtrader"] = {
        "absolute_total_return_gap": abs(total_return(vbt.equity) - total_return(bt.equity)),
        "vbt_total_return": total_return(vbt.equity),
        "backtrader_total_return": total_return(bt.equity),
        "execution_note": "Both use next-bar execution; remaining differences come from engine fills and sizing.",
    }

    wf = run_walk_forward(
        selected_spec,
        spy,
        is_years=3,
        oos_years=1,
        param_grid=PARAM_GRID,
        objective="total_return",
        min_valid_folds=1,
    )
    report["walk_forward"] = _jsonable(
        {
            "folds": len(wf.fold_params),
            "fold_params": wf.fold_params,
            "is_cagrs": wf.is_cagrs,
            "oos_cagrs": wf.oos_cagrs,
            "wfe": wf.wfe,
            "is_intervals": wf.is_intervals,
            "oos_intervals": wf.oos_intervals,
        }
    )

    mc = run_monte_carlo(_trade_returns(vbt), n_trials=mc_trials)
    report["monte_carlo"] = _jsonable(mc)
    permutation_window = spy.iloc[:252].copy()
    permutation = run_permutation(
        selected_spec,
        permutation_window,
        n_trials=permutation_trials,
        max_resamples=2_000,
    )
    report["permutation"] = _jsonable(permutation)
    report["permutation"]["window"] = {
        "start": pd.Timestamp(permutation_window.index[0]).isoformat(),
        "end": pd.Timestamp(permutation_window.index[-1]).isoformat(),
        "reason": "The fixed first-year window keeps comparable random-entry resampling practical while using the selected strategy policy.",
    }

    _set_metadata(vbt, symbol="SPY", data_root=data_root, universe_root=universe_root)
    final_report = render_report(
        vbt,
        make_report_config(run_id="v1-acceptance", outputs_dir=output_root),
    )
    report["report"] = {
        "html": str(final_report.html_path),
        "result": str(output_root / "v1-acceptance" / "result.json"),
    }

    try:
        nautilus = run_spec(
            selected_spec,
            spy,
            engine="nautilus",
            params=selected_params,
            run_id="acceptance-nautilus",
        )
    except (RuntimeError, ValueError) as exc:
        report["nautilus"] = {"status": "unavailable", "error": str(exc)}
    else:
        _set_metadata(nautilus, symbol="SPY", data_root=data_root, universe_root=universe_root)
        nautilus_metrics = attach_metric_panel(nautilus)
        _write_result(nautilus, output_root / "results" / "nautilus", metrics=nautilus_metrics)
        report["nautilus"] = _summary(nautilus, symbol="SPY", metrics=nautilus_metrics)
        report["nautilus"]["daily_equity_note"] = (
            "Equity is reconstructed from native fills marked to the identical canonical close bars."
        )

    (output_root / "acceptance.json").write_text(
        json.dumps(_jsonable(report), indent=2),
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--universe-root", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--mc-trials", type=int, default=1000)
    parser.add_argument("--permutation-trials", type=int, default=1000)
    args = parser.parse_args()
    settings = resolve_settings()
    report = run_acceptance(
        data_root=args.data_root or settings.data_dir,
        universe_root=args.universe_root or settings.universe_dir,
        output_root=args.output_root or settings.outputs_dir / "v1-acceptance",
        start=args.start,
        end=args.end,
        mc_trials=args.mc_trials,
        permutation_trials=args.permutation_trials,
    )
    print(json.dumps(_jsonable(report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
