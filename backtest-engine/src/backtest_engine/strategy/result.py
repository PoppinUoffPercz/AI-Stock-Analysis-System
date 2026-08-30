"""Canonical result schema shared by every engine adapter.

BacktestResult holds:
  - identity: who/what/when
  - equity series (the primary metric surface downstream validation depends on)
  - ordered trades (for MC permutation) and positions
  - a raw metric dict (engine-specific; cleaner normalized metrics in metrics.core)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class TradeRecord:
    timestamp: pd.Timestamp
    symbol: str
    side: str  # "LONG" / "SHORT" / "FLAT"
    quantity: float
    fill_price: float
    commission: float
    slippage_cost: float  # extra cost beyond midpoint (>= 0)
    exit_timestamp: pd.Timestamp | None = None
    exit_price: float | None = None


@dataclass
class BacktestResult:
    run_id: str
    strategy_name: str
    engine: str  # "vectorbt" | "backtrader" | "nautilus"
    params: dict[str, Any]
    capital: float
    cost_model: str  # name of cost assumption
    universe_ref: str

    equity: pd.Series  # index: timestamp tz-aware UTC, value: portfolio equity
    returns: pd.Series  # bar returns aligned to equity
    trades: list[TradeRecord] = field(default_factory=list)

    # Optional raw engine metric blob for debugging; metrics.core computes the
    # normalized metric dict from equity/returns.
    raw_metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def final_equity(self) -> float:
        return float(self.equity.iloc[-1]) if len(self.equity) else 0.0
