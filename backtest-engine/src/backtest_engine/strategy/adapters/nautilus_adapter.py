"""NautilusTrader replay adapter.

This module is deliberately optional.  Importing the backtest engine does not
import NautilusTrader; selecting this adapter does.  The adapter uses the
low-level Nautilus backtest engine so the same precomputed signals used by the
VectorBT and Backtrader adapters are replayed through a real event-driven
venue.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping
from importlib import import_module
from numbers import Real
from typing import Any, cast

import pandas as pd

from backtest_engine.strategy.result import BacktestResult, TradeRecord, validate_backtest_result


def _import_nautilus() -> dict[str, Any]:
    try:
        engine = import_module("nautilus_trader.backtest.engine")
        config = import_module("nautilus_trader.config")
        currencies = import_module("nautilus_trader.model.currencies")
        data = import_module("nautilus_trader.model.data")
        enums = import_module("nautilus_trader.model.enums")
        identifiers = import_module("nautilus_trader.model.identifiers")
        instruments = import_module("nautilus_trader.model.instruments")
        objects = import_module("nautilus_trader.model.objects")
        strategy = import_module("nautilus_trader.trading.strategy")
    except ImportError as exc:
        raise RuntimeError(
            "NautilusTrader replay requires the optional execution extra; "
            'install with `pip install -e ".[execution]"`'
        ) from exc

    return {
        "BacktestEngine": engine.BacktestEngine,
        "BacktestEngineConfig": config.BacktestEngineConfig,
        "LoggingConfig": config.LoggingConfig,
        "StrategyConfig": config.StrategyConfig,
        "USD": currencies.USD,
        "Bar": data.Bar,
        "BarType": data.BarType,
        "AccountType": enums.AccountType,
        "OmsType": enums.OmsType,
        "OrderSide": enums.OrderSide,
        "TimeInForce": enums.TimeInForce,
        "InstrumentId": identifiers.InstrumentId,
        "Symbol": identifiers.Symbol,
        "TraderId": identifiers.TraderId,
        "Venue": identifiers.Venue,
        "Equity": instruments.Equity,
        "Money": objects.Money,
        "Price": objects.Price,
        "Quantity": objects.Quantity,
        "Strategy": strategy.Strategy,
    }


def _bars_from_ohlc(
    ohlc: pd.DataFrame, *, symbol: str, nautilus: dict[str, Any]
) -> tuple[Any, list[Any]]:
    Bar = nautilus["Bar"]
    BarType = nautilus["BarType"]
    Price = nautilus["Price"]
    Quantity = nautilus["Quantity"]

    def price(value: object) -> Any:
        return Price.from_str(f"{float(cast(Any, value)):.2f}")

    bar_type = BarType.from_str(f"{symbol}.XNAS-1-DAY-LAST-EXTERNAL")
    bars = []
    for timestamp, row in ohlc.iterrows():
        ts_ns = int(pd.Timestamp(cast(Any, timestamp)).tz_convert("UTC").value)
        bars.append(
            Bar(
                bar_type,
                price(row["open"]),
                price(row["high"]),
                price(row["low"]),
                price(row["close"]),
                Quantity.from_int(
                    max(1, int(float(row["volume"]))),
                ),
                ts_ns,
                ts_ns,
            )
        )
    return bar_type, bars


def _report_series(report: pd.DataFrame, *, capital: float) -> pd.Series:
    """Extract a UTC equity series from Nautilus' account report."""
    if report.empty:
        return pd.Series(dtype="float64", index=pd.DatetimeIndex([], tz="UTC"))

    frame = report.copy()
    timestamp_column = next(
        (column for column in ("timestamp", "ts_init", "ts_event") if column in frame), None
    )
    value_column = next(
        (
            column
            for column in ("total", "balance_total", "equity", "account_value")
            if column in frame
        ),
        None,
    )
    if value_column is None:
        raise RuntimeError(
            "Nautilus account report did not contain a timestamp and equity column; "
            f"columns={list(frame.columns)}"
        )

    timestamps = (
        pd.to_datetime(frame[timestamp_column], utc=True)
        if timestamp_column is not None
        else pd.to_datetime(frame.index, utc=True)
    )
    values = pd.to_numeric(frame[value_column], errors="coerce")
    series = pd.Series(values.to_numpy(dtype="float64"), index=pd.DatetimeIndex(timestamps))
    return series.dropna().sort_index()


def _trade_records(report: pd.DataFrame, *, symbol: str) -> list[TradeRecord]:
    if report.empty:
        return []
    records: list[TradeRecord] = []
    for _, row in report.iterrows():
        timestamp_key = next(
            (column for column in ("timestamp", "ts_init", "ts_event") if column in report), None
        )
        price_key = next(
            (column for column in ("last_px", "price", "fill_price") if column in report), None
        )
        quantity_key = next(
            (column for column in ("last_qty", "quantity", "fill_qty") if column in report), None
        )
        side_key = next((column for column in ("order_side", "side") if column in report), None)
        if timestamp_key is None or price_key is None or quantity_key is None:
            continue
        side = str(row[side_key]).upper() if side_key else "BUY"
        records.append(
            TradeRecord(
                timestamp=pd.to_datetime(cast(Any, row[timestamp_key]), utc=True),
                symbol=symbol,
                side="LONG" if "BUY" in side else "EXIT",
                quantity=float(row[quantity_key]),
                fill_price=float(row[price_key]),
                commission=0.0,
                slippage_cost=0.0,
            )
        )
    return records


def _sanitize_metrics(value: Any) -> Any:
    """Replace undefined third-party metric values without touching result inputs."""
    if isinstance(value, Mapping):
        return {key: _sanitize_metrics(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_metrics(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_metrics(item) for item in value)
    if isinstance(value, Real) and not isinstance(value, bool) and not math.isfinite(float(value)):
        return None
    return value


def _equity_from_fills(
    ohlc: pd.DataFrame,
    fills: list[TradeRecord],
    *,
    capital: float,
) -> pd.Series:
    """Mark the native fills to the canonical close series."""
    cash = capital
    quantity = 0.0
    by_timestamp = sorted(fills, key=lambda fill: fill.timestamp)
    fill_index = 0
    values: list[float] = []
    for timestamp, row in ohlc.iterrows():
        bar_timestamp = pd.Timestamp(cast(Any, timestamp)).tz_convert("UTC")
        while (
            fill_index < len(by_timestamp) and by_timestamp[fill_index].timestamp <= bar_timestamp
        ):
            fill = by_timestamp[fill_index]
            signed_quantity = fill.quantity if fill.side == "LONG" else -fill.quantity
            cash -= signed_quantity * fill.fill_price
            quantity += signed_quantity
            fill_index += 1
        values.append(cash + quantity * float(row["close"]))
    return pd.Series(values, index=pd.DatetimeIndex(ohlc.index), dtype="float64")


class NautilusAdapter:
    """Replay one signal stream through NautilusTrader's simulated venue."""

    name = "nautilus"

    def run(
        self,
        signals: pd.DataFrame,
        ohlc: pd.DataFrame,
        *,
        capital: float,
        cost_model: str,
        strategy_name: str,
        universe_ref: str,
        params: dict[str, Any],
        run_id: str | None = None,
    ) -> BacktestResult:
        nautilus = _import_nautilus()
        if cost_model != "zero":
            raise ValueError(
                "Nautilus replay currently supports only the zero cost model; "
                "use VectorBT or Backtrader for modeled research costs"
            )
        BacktestEngine = nautilus["BacktestEngine"]
        BacktestEngineConfig = nautilus["BacktestEngineConfig"]
        LoggingConfig = nautilus["LoggingConfig"]
        StrategyConfig = nautilus["StrategyConfig"]
        Strategy = nautilus["Strategy"]
        USD = nautilus["USD"]
        AccountType = nautilus["AccountType"]
        OmsType = nautilus["OmsType"]
        OrderSide = nautilus["OrderSide"]
        TimeInForce = nautilus["TimeInForce"]
        InstrumentId = nautilus["InstrumentId"]
        Symbol = nautilus["Symbol"]
        TraderId = nautilus["TraderId"]
        Venue = nautilus["Venue"]
        Equity = nautilus["Equity"]
        Money = nautilus["Money"]
        Price = nautilus["Price"]
        Quantity = nautilus["Quantity"]

        symbol = str(ohlc.attrs.get("symbol", "UNKNOWN")).upper()
        if symbol == "UNKNOWN":
            raise ValueError("Nautilus replay requires ohlc.attrs['symbol']")
        bar_type, bars = _bars_from_ohlc(ohlc, symbol=symbol, nautilus=nautilus)
        instrument_id = InstrumentId.from_str(f"{symbol}.XNAS")
        instrument = Equity(
            instrument_id=instrument_id,
            raw_symbol=Symbol(symbol),
            currency=USD,
            price_precision=2,
            price_increment=Price.from_str("0.01"),
            lot_size=Quantity.from_int(1),
            ts_event=0,
            ts_init=0,
        )

        signal_frame = signals.copy()
        signal_frame.index = pd.DatetimeIndex(signal_frame.index).tz_convert("UTC").normalize()
        trade_log: list[TradeRecord] = []

        class ReplayConfig(StrategyConfig):  # type: ignore[valid-type,misc]
            instrument_id: Any
            bar_type: Any
            signals: Any
            quantity: Any
            trade_log: Any

        class ReplayStrategy(Strategy):  # type: ignore[valid-type,misc]
            def __init__(self, config):
                super().__init__(config)
                self._pending = False

            def on_start(self):
                self.subscribe_bars(self.config.bar_type)

            def on_bar(self, bar):
                timestamp = pd.to_datetime(bar.ts_event, unit="ns", utc=True).normalize()
                row = self.config.signals.loc[self.config.signals.index == timestamp]
                if row.empty or self._pending:
                    return
                entry = bool(row.iloc[0].get("entry", False))
                exit_ = bool(row.iloc[0].get("exit", False))
                if entry and self.portfolio.is_flat(self.config.instrument_id):
                    order = self.order_factory.market(
                        self.config.instrument_id,
                        OrderSide.BUY,
                        self.config.quantity,
                        time_in_force=TimeInForce.GTC,
                    )
                    self._pending = True
                    self.submit_order(order)
                elif exit_ and self.portfolio.is_net_long(self.config.instrument_id):
                    self._pending = True
                    self.close_all_positions(self.config.instrument_id)

            def on_order_filled(self, event):
                self._pending = False
                self.config.trade_log.append(
                    TradeRecord(
                        timestamp=pd.to_datetime(event.ts_event, unit="ns", utc=True),
                        symbol=symbol,
                        side="LONG" if "BUY" in str(event.order_side).upper() else "EXIT",
                        quantity=float(event.last_qty),
                        fill_price=float(event.last_px),
                        commission=0.0,
                        slippage_cost=0.0,
                    )
                )

            def on_order_rejected(self, event):
                self._pending = False

        quantity = instrument.make_qty(capital / max(float(ohlc["close"].iloc[0]), 1e-6) * 0.99)
        config = BacktestEngineConfig(
            trader_id=TraderId("BACKTESTER-001"),
            logging=LoggingConfig(log_level="ERROR", bypass_logging=True),
        )
        engine = BacktestEngine(config=config)
        try:
            engine.add_venue(
                venue=Venue("XNAS"),
                oms_type=OmsType.NETTING,
                account_type=AccountType.CASH,
                base_currency=USD,
                starting_balances=[Money(capital, USD)],
            )
            engine.add_instrument(instrument)
            engine.add_data(bars)
            engine.add_strategy(
                ReplayStrategy(
                    ReplayConfig(
                        instrument_id=instrument_id,
                        bar_type=bar_type,
                        signals=signal_frame,
                        quantity=quantity,
                        trade_log=trade_log,
                    )
                )
            )
            engine.run()
            account_report = engine.trader.generate_account_report(Venue("XNAS"))
            fills_report = engine.trader.generate_fills_report()
            report_trades = _trade_records(fills_report, symbol=symbol)
            trades = report_trades or trade_log
            equity = _equity_from_fills(ohlc, trades, capital=capital)
            if equity.empty:
                equity = _report_series(account_report, capital=capital)
            returns = equity.pct_change().fillna(0.0)
            return validate_backtest_result(
                BacktestResult(
                    run_id=run_id or f"nautilus-{uuid.uuid4().hex[:8]}",
                    strategy_name=strategy_name,
                    engine=self.name,
                    params=dict(params),
                    capital=capital,
                    cost_model=cost_model,
                    universe_ref=universe_ref,
                    equity=equity,
                    returns=returns,
                    trades=trades,
                    raw_metrics={
                        "nautilus_stats": _sanitize_metrics(engine.get_result().stats_returns)
                    },
                )
            )
        finally:
            engine.dispose()
