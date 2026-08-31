"""Minimal buy-and-hold benchmark for canonical backtest results."""

from __future__ import annotations

from typing import Any

import pandas as pd

from backtest_engine.strategy.result import BacktestResult


def attach_buy_and_hold_benchmark(result: BacktestResult, ohlc: pd.DataFrame) -> dict[str, Any]:
    """Attach first-open to final-close buy-and-hold and strategy return conventions."""
    symbols = result.metadata.get("symbols")
    if symbols is None:
        symbol = ohlc.attrs.get("symbol")
        symbols = [str(symbol).upper()] if symbol else []
    if len(symbols) != 1:
        benchmark: dict[str, Any] = {
            "status": "unavailable",
            "reason": "buy-and-hold benchmark requires exactly one symbol",
        }
    else:
        execution_bars = ohlc[ohlc.index.isin(result.equity.index)]
        if execution_bars.empty:
            raise ValueError("benchmark has no OHLC bars aligned to the result execution period")
        total_costs = float(
            result.metadata.get(
                "total_execution_cost",
                sum(trade.commission + trade.slippage_cost for trade in result.trades),
            )
        )
        net_return = result.final_equity / result.capital - 1.0
        cost_addback_return = (result.final_equity + total_costs) / result.capital - 1.0
        benchmark_return = float(
            execution_bars["close"].iloc[-1] / execution_bars["open"].iloc[0] - 1.0
        )
        benchmark = {
            "status": "available",
            "identity": (
                f"{symbols[0]} buy-and-hold (first available open to final close; no costs)"
            ),
            "start": pd.Timestamp(execution_bars.index[0]).isoformat(),
            "end": pd.Timestamp(execution_bars.index[-1]).isoformat(),
            "total_return": benchmark_return,
            "strategy_cost_addback_return": cost_addback_return,
            "strategy_net_return": net_return,
            "relative_net_performance": net_return - benchmark_return,
        }
    result.metadata["benchmark"] = benchmark
    return benchmark
