"""`bte` CLI entry point.

Commands shipped in v1 (M2/M4/M7/M8):
  - `bte settings`    - print resolved settings
  - `bte discover`    - run a Phase 1 (vectorized) sweep or single backtest on synth data
  - `bte validate`   - run a Phase 2 (Backtrader) backtest on synth data
  - `bte report`      - generate a QuantStats-style tearsheet for the latest run
  - `bte list-strats` - list built-in strategies

The CLI in v1 deliberately uses synthetic data so the whole pipeline runs
end-to-end without network/data-fetch setup. The data layer (M1) supports
real ingestion; CLI integration with yfinance/warchest data is the next-step
follow-up (see plan M9).
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Sequence

import pandas as pd

from backtest_engine import __version__
from backtest_engine.config import resolve_settings
from backtest_engine.metrics.core import attach_metric_panel, bias_audit
from backtest_engine.pipeline.discovery import run_spec
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


# --- argument parsers ------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bte", description="backtest-engine CLI")
    p.add_argument("--version", action="version", version=f"bte {__version__}")
    sub = p.add_subparsers(dest="cmd", required=False)

    sub.add_parser("settings", help="Print resolved settings as JSON")
    sub.add_parser("strats", help="List built-in strategies")

    d = sub.add_parser("discover", help="Phase 1 - VectorBT discovery (single run on synth data)")
    d.add_argument("--strategy", required=True, choices=sorted(REGISTRY))
    d.add_argument(
        "--cost", default="zero", help="Cost model preset (zero|us_equity_pershare|us_equity_flat)"
    )
    d.add_argument("--capital", type=float, default=100_000)
    d.add_argument("--days", type=int, default=252 * 3)
    d.add_argument("--seed", type=int, default=42)
    d.add_argument("--engine", default="vectorbt", choices=("vectorbt", "backtrader"))

    v = sub.add_parser(
        "validate", help="Phase 2 - Backtrader validation (single run on synth data)"
    )
    v.add_argument("--strategy", required=True, choices=sorted(REGISTRY))
    v.add_argument("--cost", default="zero")
    v.add_argument("--capital", type=float, default=100_000)
    v.add_argument("--days", type=int, default=252 * 3)
    v.add_argument("--seed", type=int, default=42)

    r = sub.add_parser("report", help="Generate a QuantStats-style tearsheet for a run")
    r.add_argument("--run-id", required=True, help="Run id (e.g. returned by discover/validate)")

    # placeholder subcommands referenced by docs:
    sub.add_parser("replay", help="Phase 3 - NautilusTrader replay (M9; not yet implemented)")

    return p


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
    ohlc = _synthetic_ohlc(days=args.days, seed=args.seed)
    engine = "backtrader" if args.cmd == "validate" else args.engine
    run_id = f"bte-{args.cmd}-{uuid.uuid4().hex[:8]}"
    res = run_spec(spec, ohlc, engine=engine, run_id=run_id)
    print(f"Run id: {res.run_id}")
    print(f"Engine: {res.engine}")
    print(f"Strategy: {res.strategy_name}")
    print(f"Params: {res.params}")
    metrics = attach_metric_panel(res)
    print(
        json.dumps(
            {k: float(v) if isinstance(v, (float, int)) else str(v) for k, v in metrics.items()},
            indent=2,
        )
    )
    print(f"Bias flags: {bias_audit(metrics)}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:

    settings = resolve_settings()
    outputs_dir = settings.outputs_dir
    metrics_path = outputs_dir / args.run_id / "metrics.json"
    if not metrics_path.exists():
        print(f"No metrics.json for run {args.run_id} under {outputs_dir}", file=sys.stderr)
        return 1
    metrics = json.loads(metrics_path.read_text())
    # Without preserving the full BacktestResult on disk we render a minimal
    # report from the metrics.json only. A future serialization of the result
    # (M9) would let us regen the full plotly panels here.
    out_dir = outputs_dir / args.run_id
    html_path = out_dir / "report.html"
    html_path.write_text(
        f"<!doctype html><html><body><h1>Report {args.run_id}</h1>"
        f"<pre>{json.dumps(metrics, indent=2)}</pre></body></html>",
        encoding="utf-8",
    )
    print(f"Report written to {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
