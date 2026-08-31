"""Canonical result schema shared by every engine adapter.

BacktestResult holds:
  - identity: who/what/when
  - equity series (the primary metric surface downstream validation depends on)
  - ordered trades (for MC permutation) and positions
  - a raw metric dict (engine-specific; cleaner normalized metrics in metrics.core)
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from numbers import Real
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from backtest_engine.reproducibility import RunManifest

import numpy as np
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
    metrics: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    manifest: RunManifest | None = None

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def final_equity(self) -> float:
        return float(self.equity.iloc[-1]) if len(self.equity) else 0.0


def validate_backtest_result(result: BacktestResult) -> BacktestResult:
    """Validate a complete canonical result at adapter and persistence boundaries."""
    if not isinstance(result, BacktestResult):
        raise ValueError("result must be a BacktestResult")

    for field_name in ("run_id", "strategy_name", "engine", "cost_model", "universe_ref"):
        value = getattr(result, field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a nonempty string")
    if not isinstance(result.params, dict):
        raise ValueError("params must be a mapping")
    _finite_number(result.capital, "capital")

    equity_index = _validate_series(result.equity, "equity")
    returns_index = _validate_series(result.returns, "returns")
    if len(result.equity) != len(result.returns) or not equity_index.equals(returns_index):
        raise ValueError("equity and returns must have the same length and exactly align")
    expected_returns = result.equity.pct_change().fillna(0.0).to_numpy(dtype="float64")
    actual_returns = result.returns.to_numpy(dtype="float64")
    if not np.allclose(actual_returns, expected_returns, rtol=1e-9, atol=1e-9):
        raise ValueError("returns must reconcile with equity pct_change using a zero first return")

    if not isinstance(result.trades, list):
        raise ValueError("trades must be a list")
    market_timestamps = set(equity_index)
    for position, trade in enumerate(result.trades):
        _validate_trade(trade, position, market_timestamps)

    if not isinstance(result.raw_metrics, dict):
        raise ValueError("raw_metrics must be a mapping")
    if not isinstance(result.metrics, dict):
        raise ValueError("metrics must be a mapping")
    _validate_numeric_mapping(result.raw_metrics, "raw_metrics")
    _validate_numeric_mapping(result.metrics, "metrics")
    if not isinstance(result.metadata, dict):
        raise ValueError("metadata must be a mapping")
    _validate_numeric_mapping(result.metadata, "metadata")
    _validate_metadata(result)
    return result


def _validate_series(series: object, field_name: str) -> pd.DatetimeIndex:
    if not isinstance(series, pd.Series):
        raise ValueError(f"{field_name} must be a pandas Series")
    if not isinstance(series.index, pd.DatetimeIndex):
        raise ValueError(f"{field_name} index must be a DatetimeIndex")
    index = series.index
    if index.tz is None or str(index.tz) != "UTC":
        raise ValueError(f"{field_name} index must be timezone-aware UTC")
    if not index.is_monotonic_increasing:
        raise ValueError(f"{field_name} index must be increasing")
    if not index.is_unique:
        raise ValueError(f"{field_name} index must be unique")
    try:
        values = series.to_numpy(dtype="float64")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} values must be numeric") from exc
    if not np.isfinite(values).all():
        raise ValueError(f"{field_name} values must be finite")
    return index


def _validate_trade(
    trade: object,
    position: int,
    market_timestamps: set[pd.Timestamp],
) -> None:
    prefix = f"trade[{position}]"
    if not isinstance(trade, TradeRecord):
        raise ValueError(f"{prefix} must be a TradeRecord")
    if not isinstance(trade.symbol, str) or not trade.symbol.strip():
        raise ValueError(f"{prefix}.symbol must be a nonempty string")
    if trade.side not in {"LONG", "SHORT", "EXIT", "FLAT"}:
        raise ValueError(f"{prefix}.side must be LONG, SHORT, EXIT, or FLAT")
    for field_name in ("quantity", "fill_price"):
        value = _finite_number(getattr(trade, field_name), f"{prefix}.{field_name}")
        if value <= 0:
            raise ValueError(f"{prefix}.{field_name} must be positive")
    for field_name in ("commission", "slippage_cost"):
        value = _finite_number(getattr(trade, field_name), f"{prefix}.{field_name}")
        if value < 0:
            raise ValueError(f"{prefix}.{field_name} must be nonnegative")

    entry = _utc_timestamp(trade.timestamp, f"{prefix}.timestamp")
    if market_timestamps and entry not in market_timestamps:
        raise ValueError(f"{prefix}.timestamp must belong to the result equity index")
    if (trade.exit_timestamp is None) != (trade.exit_price is None):
        raise ValueError(
            f"{prefix}.exit_timestamp and exit_price must both be set or both be absent"
        )
    if trade.exit_timestamp is not None:
        exit_timestamp = _utc_timestamp(trade.exit_timestamp, f"{prefix}.exit_timestamp")
        exit_price = _finite_number(trade.exit_price, f"{prefix}.exit_price")
        if exit_price <= 0:
            raise ValueError(f"{prefix}.exit_price must be positive")
        if exit_timestamp < entry:
            raise ValueError(f"{prefix}.exit_timestamp must not precede its entry timestamp")
        if market_timestamps and exit_timestamp not in market_timestamps:
            raise ValueError(f"{prefix}.exit_timestamp must belong to the result equity index")


def _utc_timestamp(value: object, field_name: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a parseable timestamp") from exc
    if pd.isna(timestamp):
        raise ValueError(f"{field_name} must be a parseable timestamp")
    if timestamp.tzinfo is None or str(timestamp.tz) != "UTC":
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return timestamp


def _finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _validate_numeric_mapping(mapping: Mapping[str, Any], prefix: str) -> None:
    for key, value in mapping.items():
        _validate_nested_numerics(value, f"{prefix}.{key}")


def _validate_nested_numerics(value: Any, path: str) -> None:
    if isinstance(value, Real) and not isinstance(value, bool):
        _finite_number(value, path)
    elif isinstance(value, Mapping):
        _validate_numeric_mapping(value, path)
    elif isinstance(value, (list, tuple)):
        for position, item in enumerate(value):
            _validate_nested_numerics(item, f"{path}[{position}]")


def _validate_metadata(result: BacktestResult) -> None:
    metadata = result.metadata
    for field_name in ("data_source", "cost_fidelity"):
        value = metadata.get(field_name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"metadata.{field_name} must be a nonempty string")
    symbols = metadata.get("symbols")
    if symbols is not None and (
        not isinstance(symbols, list)
        or not symbols
        or any(not isinstance(symbol, str) or not symbol.strip() for symbol in symbols)
    ):
        raise ValueError("metadata.symbols must be a nonempty list of nonempty strings")
    date_range = metadata.get("date_range")
    if date_range is not None:
        if (
            not isinstance(date_range, Mapping)
            or "start" not in date_range
            or "end" not in date_range
        ):
            raise ValueError("metadata.date_range must contain start and end timestamps")
        start = _utc_timestamp(date_range["start"], "metadata.date_range.start")
        end = _utc_timestamp(date_range["end"], "metadata.date_range.end")
        if end < start:
            raise ValueError("metadata.date_range.end must not precede start")

    cost_fields = (
        "total_commission",
        "total_slippage",
        "total_execution_cost",
        "net_final_equity",
        "cost_addback_final_equity",
    )
    costs = {
        field_name: _finite_number(metadata[field_name], f"metadata.{field_name}")
        for field_name in cost_fields
        if field_name in metadata
    }
    for field_name in ("total_commission", "total_slippage", "total_execution_cost"):
        if field_name in costs and costs[field_name] < 0:
            raise ValueError(f"metadata.{field_name} must be nonnegative")
    expected_commission = sum(trade.commission for trade in result.trades)
    expected_slippage = sum(trade.slippage_cost for trade in result.trades)
    _require_close(costs, "total_commission", expected_commission)
    _require_close(costs, "total_slippage", expected_slippage)
    _require_close(costs, "total_execution_cost", expected_commission + expected_slippage)
    if {"total_commission", "total_slippage", "total_execution_cost"} <= costs.keys():
        _require_close(
            costs,
            "total_execution_cost",
            costs["total_commission"] + costs["total_slippage"],
        )
    if "net_final_equity" in costs:
        _require_close(costs, "net_final_equity", result.final_equity)
    if {"cost_addback_final_equity", "net_final_equity", "total_execution_cost"} <= costs.keys():
        _require_close(
            costs,
            "cost_addback_final_equity",
            costs["net_final_equity"] + costs["total_execution_cost"],
        )


def _require_close(values: Mapping[str, float], field_name: str, expected: float) -> None:
    if field_name in values and not math.isclose(
        values[field_name], expected, rel_tol=1e-9, abs_tol=1e-9
    ):
        raise ValueError(f"metadata.{field_name} is inconsistent with result accounting")
