"""Canonical JSON persistence for complete backtest results."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from backtest_engine.reproducibility import RunManifest, fallback_manifest
from backtest_engine.strategy.result import BacktestResult, TradeRecord, validate_backtest_result

RESULT_SCHEMA_VERSION = 1


def persist_result(
    result: BacktestResult,
    output_dir: Path,
    *,
    metrics: dict[str, float] | None = None,
) -> Path:
    """Atomically write a complete result payload and return its path."""
    validate_backtest_result(result)
    persisted_result = replace(result, metrics=metrics) if metrics is not None else result
    validate_backtest_result(persisted_result)
    output_dir = Path(output_dir)
    try:
        manifest = result.manifest or fallback_manifest(result)
    except ValueError as exc:
        raise ValueError("backtest result contains a non-finite JSON value") from exc
    _validate_manifest_result(manifest, result)
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
        "metrics": persisted_result.metrics,
        "metadata": result.metadata,
    }
    try:
        encoded = json.dumps(payload, indent=2, default=_json_default, allow_nan=False)
    except ValueError as exc:
        raise ValueError("backtest result contains a non-finite JSON value") from exc
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "result.json"
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        persisted_manifest = RunManifest.load(manifest_path)
        if persisted_manifest.identity_hash != manifest.identity_hash:
            raise FileExistsError(
                f"immutable manifest already exists with different identity: {manifest_path}"
            )
        manifest = persisted_manifest
    else:
        manifest = _write_manifest_once(manifest_path, manifest)
    result.manifest = manifest
    persisted_result.manifest = manifest
    _atomic_write(path, encoded, prefix=".result.")
    return path


def _atomic_write(path: Path, encoded: str, *, prefix: str) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=path.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        temp.write_text(encoded, encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _write_manifest_once(path: Path, manifest: RunManifest) -> RunManifest:
    fd, temp_name = tempfile.mkstemp(prefix=".manifest.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        temp.write_text(manifest.to_json(), encoding="utf-8")
        try:
            os.link(temp, path)
            return manifest
        except FileExistsError:
            persisted = RunManifest.load(path)
            if persisted.identity_hash != manifest.identity_hash:
                raise FileExistsError(
                    f"immutable manifest already exists with different identity: {path}"
                ) from None
            return persisted
    finally:
        temp.unlink(missing_ok=True)


def load_result(path: Path) -> BacktestResult:
    """Load and validate a canonical result payload."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in backtest result: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("backtest result JSON must contain an object")
    if payload.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise ValueError("unsupported backtest result schema version")
    required = (
        "run_id",
        "strategy_name",
        "engine",
        "params",
        "capital",
        "cost_model",
        "universe_ref",
        "equity",
        "returns",
        "trades",
    )
    missing = [field_name for field_name in required if field_name not in payload]
    if missing:
        raise ValueError(f"backtest result is missing required field: {missing[0]}")
    try:
        result = BacktestResult(
            run_id=payload["run_id"],
            strategy_name=payload["strategy_name"],
            engine=payload["engine"],
            params=_mapping(payload["params"], "params"),
            capital=_float(payload["capital"], "capital"),
            cost_model=payload["cost_model"],
            universe_ref=payload["universe_ref"],
            equity=_series_from_payload(payload["equity"], "equity"),
            returns=_series_from_payload(payload["returns"], "returns"),
            trades=_trades_from_payload(payload["trades"]),
            raw_metrics=_mapping(payload.get("raw_metrics", {}), "raw_metrics"),
            metrics=_mapping(payload.get("metrics", {}), "metrics"),
            metadata=_mapping(payload.get("metadata", {}), "metadata"),
            manifest=(
                RunManifest.load(Path(path).with_name("manifest.json"))
                if Path(path).with_name("manifest.json").exists()
                else None
            ),
        )
    except ValueError:
        raise
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError(f"malformed backtest result: {exc}") from exc
    validate_backtest_result(result)
    if result.manifest is not None:
        _validate_manifest_result(result.manifest, result)
    return result


def _validate_manifest_result(manifest: RunManifest, result: BacktestResult) -> None:
    if manifest.run_id != result.run_id:
        raise ValueError(
            f"manifest run_id {manifest.run_id!r} does not match result run_id {result.run_id!r}"
        )
    expected = {
        "engine": result.engine,
        "params": result.params,
        "capital": result.capital,
    }
    actual = {
        "engine": manifest.stable.get("engine"),
        "params": dict(manifest.stable.get("params", {})),
        "capital": manifest.stable.get("capital"),
    }
    if actual != expected:
        raise ValueError("manifest stable fields do not match persisted result")
    strategy = manifest.stable.get("strategy", {})
    cost = manifest.stable.get("cost", {})
    if strategy.get("name") != result.strategy_name or cost.get("name") != result.cost_model:
        raise ValueError("manifest stable fields do not match persisted result")
    universe = manifest.stable.get("universe", {})
    expected_universe = Path(result.universe_ref)
    portable_reference = (
        expected_universe.name if expected_universe.is_absolute() else expected_universe.as_posix()
    )
    if universe.get("reference") != portable_reference:
        raise ValueError("manifest stable fields do not match persisted result universe_ref")


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


def _series_from_payload(payload: object, field_name: str) -> pd.Series:
    if not isinstance(payload, dict) or not isinstance(payload.get("values"), list):
        raise ValueError(f"{field_name} must contain a values list")
    items = payload["values"]
    if not items:
        return pd.Series(dtype="float64", index=pd.DatetimeIndex([], tz="UTC"))
    try:
        if any(not isinstance(item, dict) for item in items):
            raise TypeError("series entries must be objects")
        index = pd.DatetimeIndex(
            pd.to_datetime(
                [item["timestamp"] for item in items], utc=True, errors="raise", format="mixed"
            ),
            name=payload.get("name"),
        )
        if payload.get("freq"):
            index = pd.DatetimeIndex(index, freq=payload["freq"], name=payload.get("name"))
        values = [_float(item["value"], field_name) for item in items]
        return pd.Series(values, index=index, dtype="float64")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith(field_name):
            raise
        raise ValueError(f"malformed {field_name} series: {exc}") from exc


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


def _trades_from_payload(payload: object) -> list[TradeRecord]:
    if not isinstance(payload, list):
        raise ValueError("trades must be a list")
    trades = []
    for position, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"trade[{position}] must be an object")
        try:
            trades.append(_trade_from_payload(item))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"malformed trade[{position}]: {exc}") from exc
    return trades


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def _float(value: object, field_name: str) -> float:
    try:
        return float(cast(Any, value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc


def _json_default(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value).__name__}")
