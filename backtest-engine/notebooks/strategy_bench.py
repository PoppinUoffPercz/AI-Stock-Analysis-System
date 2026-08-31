"""Reusable strategy hypothesis-test bench.

Run me to take a registered strategy through the full validation chain:

    $ PYTHONPATH=src python notebooks/strategy_bench.py bollinger_breakout

The bench is intentionally framework-neutral — it imports only what every
strategy needs and prints a single verdict at the bottom. The pattern is the
default workflow for testing any new strategy hypothesis before you ever
touch real data.

What this bench does (top-down matches the validation layer in plan section 6):
  1. Run a single backtest on a multi-year window.
  2. Compute the canonical metric panel + bias-audit flags.
  3. Walk-forward: rolling 3y IS / 1y OOS, stitched OOS equity, WFE.
  4. Monte Carlo: 500 trade-order shuffles -> percentile drawdown bands.
  5. Permutation test vs random-entry H0.
  6. Print a single deploy/don't-deploy verdict.

Each step is a separate function you can copy-paste into a notebook or
adapt for your own hypothesis file.
"""

from __future__ import annotations

import sys
from itertools import product
from typing import Any

import numpy as np
import pandas as pd

from backtest_engine.metrics.core import attach_metric_panel, bias_audit, total_return
from backtest_engine.pipeline.discovery import run_spec
from backtest_engine.strategy.registry import REGISTRY, get_strategy
from backtest_engine.strategy.spec import StrategySpec
from backtest_engine.validation.monte_carlo import shuffle_trade_order
from backtest_engine.validation.permutation import EntryEvaluation, random_entry_permutation
from backtest_engine.validation.walk_forward import rolling_windows, walk_forward

# ---------------------------------------------------------------------------
# Data scaffold (replace with real ingest from data.store.read_clean in prod)
# ---------------------------------------------------------------------------


def synth_ohlc(years: int = 5, seed: int = 99) -> pd.DataFrame:
    """Synthetic daily OHLCV. Replace with `read_clean(root, symbol)` for real runs."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-02", periods=252 * years).tz_localize("UTC")
    rets = 0.0008 + rng.normal(0, 0.012, len(idx))
    px = 100 * np.exp(np.cumsum(rets))
    return pd.DataFrame(
        {
            "open": px,
            "high": px * 1.005,
            "low": px * 0.995,
            "close": px,
            "volume": rng.integers(100_000, 500_000, len(idx)).astype(float),
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# Step 1: single backtest + metrics
# ---------------------------------------------------------------------------


def run_single(spec: StrategySpec, ohlc: pd.DataFrame, engine: str = "vectorbt"):
    result = run_spec(spec, ohlc, engine=engine, run_id="bench-single")
    panel = attach_metric_panel(result)
    flags = bias_audit(panel)
    return result, panel, flags


# ---------------------------------------------------------------------------
# Step 2: walk-forward with simple in-sample grid search
# ---------------------------------------------------------------------------


DEFAULT_PARAM_GRIDS: dict[str, dict[str, list[Any]]] = {
    "sma_cross": {"fast": [5, 10, 20], "slow": [30, 50]},
    "rsi_reversion": {
        "period": [10, 14, 20],
        "entry_level": [25, 30, 35],
        "exit_level": [45, 50, 55],
    },
    "bollinger_breakout": {
        "period": [15, 20, 30],
        "std_dev": [1.5, 2.0, 2.5],
        "stop_outside": [False, True],
    },
}


def optimise_grid(
    spec: StrategySpec,
    is_ohlc: pd.DataFrame,
    *,
    param_grid: dict[str, list[Any]],
    objective: str = "total_return",
) -> dict[str, Any]:
    """Choose parameters by evaluating only the supplied in-sample bars."""
    if objective not in {"total_return", "sharpe"}:
        raise ValueError("objective must be 'total_return' or 'sharpe'")
    keys = list(param_grid)
    candidates = (dict(zip(keys, values, strict=True)) for values in product(*param_grid.values()))
    best_params: dict[str, Any] | None = None
    best_score = float("-inf")
    for candidate in candidates:
        result = run_spec(
            spec,
            is_ohlc,
            engine="vectorbt",
            params=candidate,
            run_id="bench-wf-is",
        )
        score = (
            total_return(result.equity)
            if objective == "total_return"
            else attach_metric_panel(result)["sharpe"]
        )
        if np.isfinite(score) and (best_params is None or score > best_score):
            best_score = float(score)
            best_params = candidate
    if best_params is None:
        raise ValueError("no valid parameter combination produced a finite objective")
    return best_params


def run_walk_forward(
    spec: StrategySpec,
    ohlc: pd.DataFrame,
    *,
    is_years: int = 3,
    oos_years: int = 1,
    param_grid: dict[str, list[Any]] | None = None,
    objective: str = "total_return",
    min_valid_folds: int = 1,
):
    is_windows, oos_windows = rolling_windows(ohlc, is_years=is_years, oos_years=oos_years)

    if min_valid_folds < 1:
        raise ValueError("min_valid_folds must be at least 1")
    grid = param_grid or DEFAULT_PARAM_GRIDS.get(
        spec.name, {key: [value] for key, value in spec.params.items()}
    )

    def optimise(spec_: StrategySpec, is_ohlc_: pd.DataFrame) -> dict[str, Any]:
        return optimise_grid(spec_, is_ohlc_, param_grid=grid, objective=objective)

    def _run(spec_, ohlc_, **kw):
        return run_spec(
            spec_,
            ohlc_,
            engine="vectorbt",
            params=kw.get("params", spec_.params),
            run_id=kw.get("run_id", "wf"),
            signal_ohlc=kw.get("signal_ohlc"),
        )

    result = walk_forward(
        spec,
        ohlc,
        run_engine=_run,
        optimize=optimise,
        is_windows=is_windows,
        oos_windows=oos_windows,
    )
    if len(result.fold_params) < min_valid_folds:
        raise ValueError(
            f"walk-forward produced {len(result.fold_params)} valid folds; "
            f"minimum valid folds is {min_valid_folds}"
        )
    return result


# ---------------------------------------------------------------------------
# Step 3 + 4: monte carlo + permutation
# ---------------------------------------------------------------------------


def run_monte_carlo(trade_returns: pd.Series, *, n_trials: int = 500):
    return shuffle_trade_order(trade_returns, n_trials=n_trials, rng_seed=42)


def _trade_returns(result) -> pd.Series:
    returns = [
        trade.exit_price / trade.fill_price - 1.0
        for trade in result.trades
        if trade.exit_timestamp is not None
        and trade.exit_price is not None
        and trade.fill_price > 0
    ]
    return pd.Series(returns, dtype="float64")


def _trade_exposure(result, index: pd.Index) -> pd.Series:
    exposure = pd.Series(0.0, index=index)
    for trade in result.trades:
        start = int(index.searchsorted(trade.timestamp))
        stop = (
            int(index.searchsorted(trade.exit_timestamp))
            if trade.exit_timestamp is not None
            else len(index)
        )
        exposure.iloc[start:stop] += 1.0
    return exposure


def run_permutation(
    spec: StrategySpec,
    ohlc: pd.DataFrame,
    *,
    n_trials: int = 500,
    max_resamples: int = 2_000,
):
    signals = spec.make_signals(ohlc)
    exits = signals.get("exit", pd.Series(False, index=ohlc.index)).astype(bool)

    def evaluate(candidate_entries: pd.Series) -> EntryEvaluation:
        candidate_signals = pd.DataFrame(
            {"entry": candidate_entries.astype(bool), "exit": exits}, index=ohlc.index
        )

        def candidate_factory(_bars: pd.DataFrame, _params: dict) -> pd.DataFrame:
            return candidate_signals

        candidate_spec = StrategySpec(
            name=spec.name,
            signal_factory=candidate_factory,
            cost_model=spec.cost_model,
            capital=spec.capital,
            universe_ref=spec.universe_ref,
            params=spec.params,
        )
        result = run_spec(
            candidate_spec,
            ohlc,
            engine="vectorbt",
            run_id="bench-permutation",
        )
        completed_trades = sum(
            trade.exit_timestamp is not None and trade.exit_price is not None
            for trade in result.trades
        )
        return EntryEvaluation(
            metric=total_return(result.equity),
            completed_trades=completed_trades,
            exposure=_trade_exposure(result, ohlc.index),
        )

    return random_entry_permutation(
        signals["entry"],
        evaluator=evaluate,
        n_trials=n_trials,
        max_resamples=max_resamples,
    )


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------


def _print_header(title: str) -> None:
    print(f"\n--- {title} ---")


def _print_metric_panel(panel: dict) -> None:
    for k, v in panel.items():
        if isinstance(v, (int, float)):
            print(f"  {k:22s} {float(v):+.4f}")
        else:
            print(f"  {k:22s} {v}")


# ---------------------------------------------------------------------------
# Main bench
# ---------------------------------------------------------------------------


def main(strategy_name: str | None = None) -> int:
    name = strategy_name or "sma_cross"
    if name not in REGISTRY:
        print(f"unknown strategy '{name}'; available: {sorted(REGISTRY)}")
        return 1

    factory, defaults = get_strategy(name)
    spec = StrategySpec(
        name=name,
        signal_factory=factory,
        cost_model="zero",  # IMPORTANT: zero first; add real costs after
        capital=100_000,
        universe_ref="synth",
        params=defaults,
    )

    print(f"strategy: {name}")
    print(f"params:   {defaults}")

    ohlc = synth_ohlc(years=5, seed=99)

    # 1) single run
    _print_header("SINGLE RUN METRICS")
    res, panel, flags = run_single(spec, ohlc)
    _print_metric_panel(panel)
    _print_header("BIAS FLAGS")
    for k, v in flags.items():
        print(f"  {k:20s} {v}")

    # 2) walk-forward
    _print_header("WALK-FORWARD (3y IS / 1y OOS)")
    wf = run_walk_forward(spec, ohlc)
    print(f"  folds:           {len(wf.is_cagrs)}")
    print(f"  IS CAGR (mean):  {np.mean(wf.is_cagrs):+.4f}")
    print(f"  OOS CAGR (mean): {np.mean(wf.oos_cagrs):+.4f}")
    print(f"  WFE:             {wf.wfe:+.4f}  (>= 0.5 considered robust)")

    # 3) monte carlo
    _print_header("MONTE CARLO (500 trade-order shuffles; drawdown only)")
    mc = run_monte_carlo(_trade_returns(res))
    realized_dd = float((res.equity / res.equity.cummax() - 1).min())
    print(f"  realized max-DD:        {realized_dd:+.4f}")
    print(f"  shuffled DD pctile 5:   {mc.max_dd_pctile_5:+.4f}")
    print(f"  shuffled DD pctile 95:  {mc.max_dd_pctile_95:+.4f}")

    # 4) permutation. A bounded first-year window keeps random-entry samples
    # comparable when the full multi-year path has many completed trades.
    _print_header("PERMUTATION TEST (vs random-entry H0; first year)")
    permutation_ohlc = ohlc.iloc[:252]
    perm = run_permutation(spec, permutation_ohlc)
    print(f"  real total_return:   {perm.real_metric:+.4f}")
    print(f"  random p-value:      {perm.p_value:.4f}  (lower is more significant)")

    # 5) verdict
    _print_header("VERDICT")
    wf_ok = wf.wfe >= 0.5
    perm_ok = perm.p_value <= 0.05
    bias_clean = not flags["any_flag"]
    deploy = wf_ok and perm_ok and bias_clean
    print(f"  WFE >= 0.5:                {wf_ok}")
    print(f"  perm p <= 0.05:            {perm_ok}")
    print(f"  no bias flags triggered:   {bias_clean}")
    print(f"  -> deploy? {deploy}")
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    raise SystemExit(main(target))
