"""Backtrader adapter (Phase 2): event-driven validation with realistic fills.

Plan section 3.2: BTAdapter wraps Cerebro, injects our CostModel via a custom
broker-like scheme, and writes to BacktestResult via a custom Analyzer.

Decisions made:
  - Orders fill at next-bar open by Backtrader's default. On completion, the
    CostModel computes commission and volume-impact slippage from the executed
    quantity, price, and bar volume; the combined cost is debited from broker
    cash and the same values are written to the TradeRecord.
  - Strategy is generated programmatically from the entry/exit signal frame
    (same `signals` object the VBTAdapter consumes), so the SAME signal logic
    runs through both engines. This is the portability contract from M5 in
    practice.
"""

from __future__ import annotations

import uuid
from typing import Any

import backtrader as bt
import pandas as pd

from backtest_engine.execution.costs import get_preset
from backtest_engine.strategy.result import BacktestResult, TradeRecord


class _SignalDrivenStrategy(bt.Strategy):
    """Drives entry/exit from a precomputed signal frame.

    Reads `entry` and `exit` boolean Series indexed by timestamp (tz-aware
    UTC; backtrader auto-converts). Each bar, if `entry` is True at this bar's
    date and we're flat, go long (close-to-close comparison uses the
    Backtrader-resolved timestamps). If `exit` is True and we're long, flatten.
    """

    params = (("signals", None), ("cost_model_name", "zero"), ("trade_log", None))

    def __init__(self) -> None:
        self._entry = self.params.signals.get("entry")  # type: ignore[attr-defined]
        self._exit = self.params.signals.get("exit")  # type: ignore[attr-defined]
        self._cm = get_preset(self.params.cost_model_name)  # type: ignore[attr-defined]
        # IMPORTANT: rename our list from `_trades` to `_trade_log` — `bt.Strategy`
        # holds its own `self._trades` (DefaultDict keyed by data) set up by the
        # metaclass. Shadowing it crashes inside BT's notify path.
        self._trade_log: list = self.params.trade_log  # type: ignore[attr-defined]
        self._pending_order_ref: int | None = None

    def next(self) -> None:
        if self._pending_order_ref is not None:
            return

        # Backtrader feeds us naive datetime objects; the entry/exit series
        # passed in via params were stripped of tz upstream (UTC naive). The
        # lookup day-normalizes both sides.
        bt_dt = self.datas[0].datetime.datetime(0)  # already datetime (naive)
        ts_naive = pd.Timestamp(bt_dt).normalize()
        try:
            entry = bool(self._entry.loc[ts_naive])
        except KeyError:
            entry = False
        try:
            exit_ = bool(self._exit.loc[ts_naive]) if self._exit is not None else False
        except KeyError:
            exit_ = False

        pos = self.getposition(self.datas[0])
        price = float(self.datas[0].close[0])
        sym = self.datas[0]._name or "UNKNOWN"

        if entry and pos.size == 0:
            size = int(self.broker.getvalue() / max(price, 1e-6) * 0.99)
            if size > 0:
                order = self.buy(data=self.datas[0], size=size)
                self._track_order(order, sym, side="LONG")
        elif exit_ and pos.size > 0:
            order = self.close(data=self.datas[0])
            self._track_order(order, sym, side="EXIT")

    def _track_order(self, order, sym: str, side: str) -> None:
        if order is None:
            return
        order.addinfo(symbol=sym, side=side)
        self._pending_order_ref = order.ref

    def notify_order(self, order) -> None:
        if self._pending_order_ref != order.ref:
            return

        if order.status == order.Completed:
            ts_raw = bt.num2date(order.executed.dt)
            timestamp = (
                pd.Timestamp(ts_raw).tz_convert("UTC")
                if ts_raw.tzinfo
                else pd.Timestamp(ts_raw).tz_localize("UTC")
            )
            quantity = abs(float(order.executed.size))
            fill_price = float(order.executed.price)
            bar_volume = float(self.datas[0].volume[0])
            commission = self._cm.commission(quantity, fill_price)
            slippage_cost = self._cm.slippage_cost(quantity, fill_price, bar_volume)
            # Backtrader's commission hook cannot receive bar volume. Debit the
            # volume-impact estimate through the broker after the real fill so
            # accounting and the trade log use the same executed-fill inputs.
            self.broker.cash -= commission + slippage_cost
            self.broker._get_value()  # refresh cached equity before analyzers run
            self._trade_log.append(
                TradeRecord(
                    timestamp=timestamp,
                    symbol=getattr(order.info, "symbol", "UNKNOWN"),
                    side=getattr(order.info, "side", "LONG"),
                    quantity=quantity,
                    fill_price=fill_price,
                    commission=commission,
                    slippage_cost=slippage_cost,
                )
            )
            self._pending_order_ref = None
        elif order.status in (
            order.Canceled,
            order.Margin,
            order.Rejected,
            order.Expired,
        ):
            self._pending_order_ref = None


class _EquityAnalyzer(bt.Analyzer):
    """Captures daily equity values for the canonical BacktestResult."""

    def __init__(self) -> None:
        self._equity: list[tuple[pd.Timestamp, float]] = []
        self._returns: list[tuple[pd.Timestamp, float]] = []
        self._prev_equity: float | None = None

    def next(self) -> None:
        bt_dt = self.strategy.datas[0].datetime.datetime(0)
        ts = pd.Timestamp(bt_dt)
        eq = float(self.strategy.broker.getvalue())
        ts = ts.tz_convert("UTC") if ts.tzinfo else ts.tz_localize("UTC")
        self._equity.append((ts.normalize(), eq))
        if self._prev_equity is not None and self._prev_equity > 0:
            r = eq / self._prev_equity - 1.0
        else:
            r = 0.0
        self._returns.append((ts.normalize(), r))
        self._prev_equity = eq

    def get_analysis(self) -> dict[str, pd.Series]:
        if not self._equity:
            return {"equity": pd.Series(dtype=float), "returns": pd.Series(dtype=float)}
        idx = pd.DatetimeIndex([t for t, _ in self._equity])
        eq = pd.Series([v for _, v in self._equity], index=idx)
        rr = pd.Series([v for _, v in self._returns], index=idx)
        return {"equity": eq, "returns": rr}


class BTAdapter:
    """Backtrader adapter. Wraps Cerebro, applies our cost model, returns BacktestResult."""

    name = "backtrader"

    def __init__(self):
        # We defer construction of Cerebro to run() so the adapter is reusable.
        pass

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
        """Execute one backtest through Cerebro and emit a canonical BacktestResult."""
        # Strip tz from signals index (Backtrader prefers naive datetimes).
        sig_naive = signals.copy()
        if sig_naive.index.tz is not None:  # type: ignore[attr-defined]
            sig_naive.index = sig_naive.index.tz_convert("UTC").tz_localize(None)  # type: ignore[attr-defined]

        ohlc_naive = ohlc.copy()
        if ohlc_naive.index.tz is not None:  # type: ignore[attr-defined]
            ohlc_naive.index = ohlc_naive.index.tz_convert("UTC").tz_localize(None)  # type: ignore[attr-defined]

        feed = bt.feeds.PandasData(
            dataname=ohlc_naive[["open", "high", "low", "close", "volume"]],
            open="open",
            high="high",
            low="low",
            close="close",
            volume="volume",
            openinterest=-1,
        )
        feed._name = ohlc.attrs.get("symbol", "UNKNOWN")

        cerebro = bt.Cerebro(stdstats=False)
        cerebro.broker.setcash(capital)
        cerebro.broker.set_coc(
            False
        )  # no cheat-on-close: fill at next bar open (look-ahead defense)
        cerebro.adddata(feed)

        # Build the strategy class with frozen args (Backtrader uses its params system).
        trade_log: list[TradeRecord] = []

        # backtrader.Strategy subclass is instantiated by Cerebro. We deliver
        # state via .params (the dataclass on the class), so we wrap closure vars.
        class _Bound(_SignalDrivenStrategy):
            params = (  # type: ignore[assignment]
                ("signals", {"entry": sig_naive["entry"], "exit": sig_naive.get("exit")}),
                ("cost_model_name", cost_model),
                ("trade_log", trade_log),
            )

        cerebro.addstrategy(_Bound)
        cerebro.addanalyzer(_EquityAnalyzer, _name="equity")
        cerebro.run()

        # Extract analyzer output. Backtrader exposes analyzers differently
        # across versions; try the modern API then fall back to dict-like access.
        strat = cerebro.runningstrats[0]
        analyzer = getattr(strat.analyzers, "equity", None)
        if analyzer is None:
            try:
                analyzer = strat.analyzers.get("equity")
            except AttributeError:
                analyzer = strat.analyzers._analyzers.get("equity")
        eq_data = analyzer.get_analysis()
        equity = eq_data.get("equity", pd.Series(dtype=float))
        returns = eq_data.get("returns", pd.Series(dtype=float))

        # Align to UTC
        if not equity.empty and equity.index.tz is None:
            equity.index = equity.index.tz_localize("UTC")
        if not returns.empty and returns.index.tz is None:
            returns.index = returns.index.tz_localize("UTC")

        return BacktestResult(
            run_id=run_id or f"bt-{uuid.uuid4().hex[:8]}",
            strategy_name=strategy_name,
            engine=self.name,
            params=dict(params),
            capital=capital,
            cost_model=cost_model,
            universe_ref=universe_ref,
            equity=equity,
            returns=returns,
            trades=trade_log,
        )

    def sweep(self, *args, **kw) -> list[BacktestResult]:
        raise NotImplementedError(
            "BTAdapter.sweep: vectorized sweep not supported; use VBTAdapter."
        )
