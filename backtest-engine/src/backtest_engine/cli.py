"""`bte` CLI entry point.

Commands shipped in v1 (M2/M4/M7/M8):
  - `bte settings`    - print resolved settings
  - `bte discover`    - run a Phase 1 (vectorized) backtest on persisted clean data
  - `bte validate`   - run a Phase 2 (Backtrader) backtest on persisted clean data
  - `bte report`      - generate a QuantStats-style tearsheet for the latest run
  - `bte replay`      - replay persisted bars through NautilusTrader
  - `bte list-strats` - list built-in strategies

The CLI reads persisted clean data by default. Synthetic data is available only
when `--synthetic` is passed, keeping offline demos explicit and preventing a
missing real dataset from silently changing the backtest.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from backtest_engine import __version__
from backtest_engine.config import resolve_settings
from backtest_engine.data.store import read_clean
from backtest_engine.metrics.core import attach_metric_panel, bias_audit
from backtest_engine.metrics.tearsheet import make_report_config, render_report
from backtest_engine.pipeline.discovery import run_spec
from backtest_engine.strategy.persistence import load_result
from backtest_engine.strategy.registry import REGISTRY, get_strategy
from backtest_engine.strategy.spec import StrategySpec

# --- synth data helper (CLI-bound) ---------------------------------------


def _synthetic_ohlc(symbol: str = "SYNTH", days: int = 252 * 3, seed: int = 42) -> pd.DataFrame:
    import numpy as np

    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-02", periods=days).tz_localize("UTC")
    rets = 0.0008 + rng.normal(0, 0.012, days)
    px = 100 * np.exp(np.cumsum(rets))
    out = pd.DataFrame(
        {
            "open": px,
            "high": px * (1 + rng.uniform(0, 0.005, days)),
            "low": px * (1 - rng.uniform(0, 0.005, days)),
            "close": px,
            "volume": rng.integers(100_000, 500_000, days).astype(float),
        },
        index=idx,
    )
    out.index.name = "timestamp"
    out.attrs["symbol"] = symbol
    return out


def _clean_ohlc(
    symbol: str,
    *,
    data_root: Path,
    start: str | None,
    end: str | None,
) -> pd.DataFrame:
    """Load one symbol from the configured persisted clean-data root."""
    clean_root = data_root / "clean"
    clean = read_clean(clean_root, symbol, start=start, end=end)
    if clean.empty:
        raise ValueError(
            f"No clean data for symbol {symbol.upper()} under {clean_root}. "
            "Ingest the symbol first or pass --synthetic for an explicit demo."
        )

    required = ("timestamp", "open", "high", "low", "close", "volume")
    missing = [column for column in required if column not in clean.columns]
    if missing:
        raise ValueError(
            f"Clean data for {symbol.upper()} is missing required columns: {', '.join(missing)}"
        )
    ohlc = clean.set_index("timestamp")[list(required[1:])].sort_index()
    if len(ohlc) < 2:
        raise ValueError(f"Clean data for {symbol.upper()} must contain at least two rows")
    ohlc.attrs["symbol"] = symbol.upper()
    return ohlc


# --- argument parsers ------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bte", description="backtest-engine CLI")
    p.add_argument("--version", action="version", version=f"bte {__version__}")
    sub = p.add_subparsers(dest="cmd", required=False)

    sub.add_parser("settings", help="Print resolved settings as JSON")
    sub.add_parser("strats", help="List built-in strategies")

    d = sub.add_parser("discover", help="Phase 1 - VectorBT discovery (single persisted-data run)")
    d.add_argument("--strategy", required=True, choices=sorted(REGISTRY))
    d.add_argument(
        "--cost", default="zero", help="Cost model preset (zero|us_equity_pershare|us_equity_flat)"
    )
    d.add_argument("--capital", type=float, default=100_000)
    d.add_argument("--days", type=int, default=252 * 3)
    d.add_argument("--seed", type=int, default=42)
    d.add_argument("--engine", default="vectorbt", choices=("vectorbt", "backtrader"))
    _add_data_options(d)

    v = sub.add_parser(
        "validate", help="Phase 2 - Backtrader validation (single persisted-data run)"
    )
    v.add_argument("--strategy", required=True, choices=sorted(REGISTRY))
    v.add_argument("--cost", default="zero")
    v.add_argument("--capital", type=float, default=100_000)
    v.add_argument("--days", type=int, default=252 * 3)
    v.add_argument("--seed", type=int, default=42)
    _add_data_options(v)

    r = sub.add_parser("report", help="Generate a QuantStats-style tearsheet for a run")
    r.add_argument("--run-id", required=True, help="Run id (e.g. returned by discover/validate)")

    n = sub.add_parser("replay", help="Phase 3 - NautilusTrader execution replay")
    n.add_argument("--strategy", required=True, choices=sorted(REGISTRY))
    n.add_argument("--cost", default="zero", help="Nautilus replay currently supports zero only")
    n.add_argument("--capital", type=float, default=100_000)
    n.add_argument("--days", type=int, default=252 * 3)
    n.add_argument("--seed", type=int, default=42)
    _add_data_options(n)

    return p


def _add_data_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--symbol", default="SPY", help="Ticker in the persisted clean dataset")
    parser.add_argument("--start", help="Inclusive start date for persisted data (YYYY-MM-DD)")
    parser.add_argument("--end", help="Inclusive end date for persisted data (YYYY-MM-DD)")
    parser.add_argument(
        "--data-root",
        type=Path,
        help="Data root containing clean/<SYMBOL>/<YEAR>.parquet (default: data)",
    )
    parser.add_argument(
        "--universe-root",
        type=Path,
        help="Universe metadata root recorded with the run; does not filter bars",
    )
    parser.add_argument(
        "--universe-csv",
        type=Path,
        help="CSV whose point-in-time membership filters bars before strategy execution",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Use deterministic synthetic bars instead of persisted clean data",
    )


# --- main ----------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.cmd is None or args.cmd == "settings":
        s = resolve_settings()
        print(json.dumps({k: str(v) for k, v in s.model_dump().items()}, indent=2))
        return 0

    if args.cmd == "strats":
        for name, (_factory, defaults) in REGISTRY.items():
            print(f"{name:20} defaults={defaults}")
        return 0

    if args.cmd == "discover" or args.cmd == "validate":
        return _cmd_backtest(args)

    if args.cmd == "report":
        return _cmd_report(args)

    if args.cmd == "replay":
        return _cmd_replay(args)

    print(f"[stub] `{args.cmd}` is not implemented in v1", file=sys.stderr)
    return 2


def _cmd_backtest(args: argparse.Namespace) -> int:
    factory, default_params = get_strategy(args.strategy)
    spec = StrategySpec(
        name=args.strategy,
        signal_factory=factory,
        cost_model=args.cost,
        capital=args.capital,
        universe_ref="synth",
        params=default_params,
    )
    settings = resolve_settings()
    data_root = args.data_root or settings.data_dir
    universe_root = args.universe_root or settings.universe_dir
    if args.synthetic:
        ohlc = _synthetic_ohlc(symbol=args.symbol, days=args.days, seed=args.seed)
        source_label = "synthetic"
    else:
        try:
            ohlc = _clean_ohlc(
                args.symbol,
                data_root=data_root,
                start=args.start,
                end=args.end,
            )
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        source_label = str(data_root / "clean")
    if args.universe_csv is not None:
        spec.universe_ref = str(args.universe_csv)
    engine = "backtrader" if args.cmd == "validate" else args.engine
    run_id = f"bte-{args.cmd}-{uuid.uuid4().hex[:8]}"
    try:
        res = run_spec(spec, ohlc, engine=engine, run_id=run_id, universe=args.universe_csv)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    symbol = str(ohlc.attrs.get("symbol", args.symbol)).upper()
    res.metadata = {
        "symbols": [symbol],
        "date_range": {
            "start": pd.Timestamp(ohlc.index[0]).isoformat(),
            "end": pd.Timestamp(ohlc.index[-1]).isoformat(),
        },
        "data_source": source_label,
        "data_root": str(data_root),
        "universe_root": str(universe_root),
        "universe_csv": str(args.universe_csv) if args.universe_csv is not None else None,
        "requested_start": args.start,
        "requested_end": args.end,
        "synthetic": bool(args.synthetic),
        "execution": {
            "engine": res.engine,
            "cost_model": res.cost_model,
            "capital": res.capital,
        },
    }
    print(f"Run id: {res.run_id}")
    print(f"Engine: {res.engine}")
    print(f"Strategy: {res.strategy_name}")
    print(f"Data: {symbol} ({source_label})")
    print(f"Params: {res.params}")
    metrics = attach_metric_panel(res)
    print(
        json.dumps(
            {k: float(v) if isinstance(v, (float, int)) else str(v) for k, v in metrics.items()},
            indent=2,
        )
    )
    print(f"Bias flags: {bias_audit(metrics)}")
    report = render_report(
        res,
        make_report_config(run_id=res.run_id, outputs_dir=resolve_settings().outputs_dir),
    )
    print(f"Metrics written to {report.out_dir / 'metrics.json'}")
    print(f"Report written to {report.html_path}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:

    settings = resolve_settings()
    outputs_dir = settings.outputs_dir
    out_dir = outputs_dir / args.run_id
    result_path = out_dir / "result.json"
    if result_path.exists():
        try:
            result = load_result(result_path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"Invalid persisted result for run {args.run_id}: {exc}", file=sys.stderr)
            return 1
        report = render_report(
            result,
            make_report_config(run_id=result.run_id, outputs_dir=outputs_dir),
        )
        print(f"Report written to {report.html_path}")
        return 0

    metrics_path = out_dir / "metrics.json"
    if not metrics_path.exists():
        print(f"No metrics.json for run {args.run_id} under {outputs_dir}", file=sys.stderr)
        return 1
    metrics = json.loads(metrics_path.read_text())
    # Legacy metric-only artifacts remain readable, but new runs persist the
    # complete BacktestResult and take the branch above.
    html_path = out_dir / "report.html"
    html_path.write_text(
        f"<!doctype html><html><body><h1>Report {args.run_id}</h1>"
        f"<pre>{json.dumps(metrics, indent=2)}</pre></body></html>",
        encoding="utf-8",
    )
    print(f"Report written to {html_path}")
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    factory, default_params = get_strategy(args.strategy)
    spec = StrategySpec(
        name=args.strategy,
        signal_factory=factory,
        cost_model=args.cost,
        capital=args.capital,
        universe_ref="synth",
        params=default_params,
    )
    settings = resolve_settings()
    data_root = args.data_root or settings.data_dir
    universe_root = args.universe_root or settings.universe_dir
    if args.synthetic:
        ohlc = _synthetic_ohlc(symbol=args.symbol, days=args.days, seed=args.seed)
        source_label = "synthetic"
    else:
        try:
            ohlc = _clean_ohlc(
                args.symbol,
                data_root=data_root,
                start=args.start,
                end=args.end,
            )
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        source_label = str(data_root / "clean")

    if args.universe_csv is not None:
        spec.universe_ref = str(args.universe_csv)

    run_id = f"bte-replay-{uuid.uuid4().hex[:8]}"
    try:
        result = run_spec(spec, ohlc, engine="nautilus", run_id=run_id, universe=args.universe_csv)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    symbol = str(ohlc.attrs.get("symbol", args.symbol)).upper()
    result.metadata = {
        "symbols": [symbol],
        "date_range": {
            "start": pd.Timestamp(ohlc.index[0]).isoformat(),
            "end": pd.Timestamp(ohlc.index[-1]).isoformat(),
        },
        "data_source": source_label,
        "data_root": str(data_root),
        "universe_root": str(universe_root),
        "universe_csv": str(args.universe_csv) if args.universe_csv is not None else None,
        "requested_start": args.start,
        "requested_end": args.end,
        "synthetic": bool(args.synthetic),
        "execution": {
            "engine": result.engine,
            "cost_model": result.cost_model,
            "capital": result.capital,
        },
    }
    metrics = attach_metric_panel(result)
    report = render_report(
        result,
        make_report_config(run_id=result.run_id, outputs_dir=settings.outputs_dir),
    )
    print(f"Run id: {result.run_id}")
    print(f"Engine: {result.engine}")
    print(f"Data: {symbol} ({source_label})")
    print(json.dumps({k: float(v) for k, v in metrics.items()}, indent=2))
    print(f"Report written to {report.html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
