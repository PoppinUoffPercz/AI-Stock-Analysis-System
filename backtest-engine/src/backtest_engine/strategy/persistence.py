"""Canonical JSON persistence for complete backtest results."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backtest_engine.strategy.result import BacktestResult, TradeRecord

RESULT_SCHEMA_VERSION = 1


def persist_result(
    result: BacktestResult,
    output_dir: Path,
    *,
    metrics: dict[str, float] | None = None,
) -> Path:
    """Atomically write a complete result payload and return its path."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "result.json"
    payload = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "run_id": result.run_id,
        "strategy_name": result.strategy_name,
        "engine": result.engine,
        "params": result.params,
        "capital": result.capital,
        "cost_model": result.cost_model,
        "universe_ref": result.universe_ref,
        "equity": _series_to_payload(result.equity),
        "returns": _series_to_payload(result.returns),
        "trades": [_trade_to_payload(trade) for trade in result.trades],
        "raw_metrics": result.raw_metrics,
        "metrics": metrics if metrics is not None else result.metrics,
        "metadata": result.metadata,
    }
    fd, temp_name = tempfile.mkstemp(prefix=".result.", suffix=".tmp", dir=output_dir)
    os.close(fd)
    temp = Path(temp_name)
    try:
        temp.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return path


def load_result(path: Path) -> BacktestResult:
    """Load and validate a canonical result payload."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise ValueError("unsupported backtest result schema version")
    return BacktestResult(
        run_id=str(payload["run_id"]),
        strategy_name=str(payload["strategy_name"]),
        engine=str(payload["engine"]),
        params=dict(payload["params"]),
        capital=float(payload["capital"]),
        cost_model=str(payload["cost_model"]),
        universe_ref=str(payload["universe_ref"]),
        equity=_series_from_payload(payload["equity"]),
        returns=_series_from_payload(payload["returns"]),
        trades=[_trade_from_payload(item) for item in payload["trades"]],
        raw_metrics=dict(payload.get("raw_metrics", {})),
        metrics={key: float(value) for key, value in payload.get("metrics", {}).items()},
        metadata=dict(payload.get("metadata", {})),
    )


def _series_to_payload(series: pd.Series) -> dict[str, Any]:
    index = pd.DatetimeIndex(series.index)
    return {
        "values": [
            {"timestamp": index[position].isoformat(), "value": float(value)}
            for position, value in enumerate(series.to_numpy(dtype="float64"))
        ],
        "freq": index.freqstr,
        "name": index.name,
    }


def _series_from_payload(payload: dict[str, Any]) -> pd.Series:
    items = payload["values"]
    if not items:
        return pd.Series(dtype="float64", index=pd.DatetimeIndex([], tz="UTC"))
    index = pd.to_datetime([item["timestamp"] for item in items], utc=True)
    freq = payload.get("freq")
    if freq:
        index = pd.DatetimeIndex(index, freq=freq, name=payload.get("name"))
    values = [float(item["value"]) for item in items]
    return pd.Series(values, index=index, dtype="float64")


def _trade_to_payload(trade: TradeRecord) -> dict[str, Any]:
    return {
        "timestamp": trade.timestamp.isoformat(),
        "symbol": trade.symbol,
        "side": trade.side,
        "quantity": trade.quantity,
        "fill_price": trade.fill_price,
        "commission": trade.commission,
        "slippage_cost": trade.slippage_cost,
        "exit_timestamp": trade.exit_timestamp.isoformat() if trade.exit_timestamp else None,
        "exit_price": trade.exit_price,
    }


def _trade_from_payload(item: dict[str, Any]) -> TradeRecord:
    exit_timestamp = item.get("exit_timestamp")
    return TradeRecord(
        timestamp=pd.Timestamp(item["timestamp"]),
        symbol=str(item["symbol"]),
        side=str(item["side"]),
        quantity=float(item["quantity"]),
        fill_price=float(item["fill_price"]),
        commission=float(item["commission"]),
        slippage_cost=float(item["slippage_cost"]),
        exit_timestamp=pd.Timestamp(exit_timestamp) if exit_timestamp else None,
        exit_price=float(item["exit_price"]) if item.get("exit_price") is not None else None,
    )


def _json_default(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value).__name__}")
