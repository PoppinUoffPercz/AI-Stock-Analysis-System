"""Strictly local deterministic paper broker; no live broker integration exists here."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from stock_analysis.artifacts import ArtifactRef, ArtifactStore
from stock_analysis.market_analytics.models import (
    TradeEvent,
    _require_finite,
    _require_utc,
)
from stock_analysis.validation import validate_identifier


class PaperOrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class PaperOrderStatus(StrEnum):
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class PaperOrder:
    order_id: str
    symbol: str
    side: PaperOrderSide
    quantity: float
    submitted_at: datetime
    status: PaperOrderStatus = PaperOrderStatus.OPEN
    filled_quantity: float = 0.0
    rejection_reason: str | None = None

    @property
    def remaining_quantity(self) -> float:
        return max(0.0, self.quantity - self.filled_quantity)


@dataclass(frozen=True, slots=True)
class PaperFill:
    fill_id: str
    order_id: str
    symbol: str
    side: PaperOrderSide
    quantity: float
    price: float
    fee: float
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class PaperPosition:
    symbol: str
    quantity: float
    average_cost: float
    realized_gross_pnl: float = 0.0


@dataclass(frozen=True, slots=True)
class PaperBrokerState:
    initial_cash: float
    cash: float
    fee_per_share: float
    orders: tuple[PaperOrder, ...]
    fills: tuple[PaperFill, ...]
    positions: tuple[PaperPosition, ...]
    processed_event_ids: tuple[str, ...]
    last_event_at: datetime | None


@dataclass(frozen=True, slots=True)
class PaperAccountSnapshot:
    cash: float
    equity: float
    total_fees: float
    realized_pnl: float
    unrealized_pnl: float
    positions: tuple[PaperPosition, ...]


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    ok: bool
    discrepancies: tuple[str, ...]
    expected_cash: float
    actual_cash: float


class PaperBroker:
    """Replay-only long-equity broker with deterministic event-driven fills."""

    execution_mode = "paper_local_only"

    def __init__(self, initial_cash: float, *, fee_per_share: float = 0.0) -> None:
        _require_finite(initial_cash, "initial_cash")
        _require_finite(fee_per_share, "fee_per_share")
        if initial_cash < 0 or fee_per_share < 0:
            raise ValueError("paper broker cash and fees must be nonnegative")
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.fee_per_share = float(fee_per_share)
        self.orders: dict[str, PaperOrder] = {}
        self.fills: dict[str, PaperFill] = {}
        self.positions: dict[str, PaperPosition] = {}
        self.processed_event_ids: set[str] = set()
        self.last_event_at: datetime | None = None

    def submit_order(
        self,
        order_id: str,
        symbol: str,
        side: PaperOrderSide | str,
        quantity: float,
        submitted_at: datetime,
    ) -> PaperOrder:
        validate_identifier(order_id, field_name="paper order_id")
        if not symbol:
            raise ValueError("paper order symbol must not be empty")
        _require_utc(submitted_at, "paper order submitted_at")
        _require_finite(quantity, "paper order quantity")
        if quantity <= 0:
            raise ValueError("paper order quantity must be positive")
        side = PaperOrderSide(side)
        existing = self.orders.get(order_id)
        if existing is not None:
            if (
                existing.symbol == symbol
                and existing.side is side
                and existing.quantity == quantity
                and existing.submitted_at == submitted_at
            ):
                return existing
            raise ValueError(
                f"paper order_id {order_id} already exists with different terms"
            )
        available = self._position_quantity(symbol) - self._reserved_sell_quantity(
            symbol
        )
        if side is PaperOrderSide.SELL and quantity > available + 1e-12:
            order = PaperOrder(
                order_id,
                symbol,
                side,
                quantity,
                submitted_at,
                PaperOrderStatus.REJECTED,
                rejection_reason=(
                    "short selling is disabled in the local paper broker; "
                    f"{max(0.0, available):g} shares available"
                ),
            )
        else:
            order = PaperOrder(order_id, symbol, side, quantity, submitted_at)
        self.orders[order_id] = order
        return order

    def cancel_order(self, order_id: str, canceled_at: datetime) -> PaperOrder:
        _require_utc(canceled_at, "paper cancel timestamp")
        order = self._order(order_id)
        if canceled_at < order.submitted_at:
            raise ValueError("paper cancellation cannot precede order submission")
        if order.status is PaperOrderStatus.CANCELED:
            return order
        if order.status in {PaperOrderStatus.FILLED, PaperOrderStatus.REJECTED}:
            raise ValueError(f"cannot cancel terminal paper order {order_id}")
        order = replace(order, status=PaperOrderStatus.CANCELED)
        self.orders[order_id] = order
        return order

    def process_trade(self, event: TradeEvent) -> tuple[PaperFill, ...]:
        """Fill open orders in submission order up to this trade's displayed size."""
        event_id = f"{event.provider}:{event.dataset}:{event.symbol}:{event.trade_id}"
        if event_id in self.processed_event_ids:
            return ()
        if self.last_event_at is not None and event.timestamp < self.last_event_at:
            raise ValueError("paper broker received an out-of-order market event")
        before = self.state()
        try:
            emitted = self._process_trade_fills(event, event_id)
        except Exception:
            self._restore_state(before)
            raise
        self.last_event_at = event.timestamp
        self.processed_event_ids.add(event_id)
        return emitted

    def _process_trade_fills(
        self, event: TradeEvent, event_id: str
    ) -> tuple[PaperFill, ...]:
        """Apply one event's fills after its caller has captured broker state."""
        available = event.size
        emitted: list[PaperFill] = []
        active = sorted(
            (
                order
                for order in self.orders.values()
                if order.symbol == event.symbol
                and order.submitted_at <= event.timestamp
                and order.status
                in {PaperOrderStatus.OPEN, PaperOrderStatus.PARTIALLY_FILLED}
            ),
            key=lambda order: (order.submitted_at, order.order_id),
        )
        for order in active:
            if available <= 0:
                break
            quantity = min(order.remaining_quantity, available)
            if order.side is PaperOrderSide.BUY:
                per_share_cash = event.price + self.fee_per_share
                quantity = min(quantity, self.cash / per_share_cash)
                if quantity <= 1e-12:
                    self.orders[order.order_id] = replace(
                        order,
                        status=PaperOrderStatus.REJECTED,
                        rejection_reason="insufficient paper cash",
                    )
                    continue
            fill_id = f"{event_id}:{order.order_id}"
            fill = PaperFill(
                fill_id,
                order.order_id,
                order.symbol,
                order.side,
                quantity,
                event.price,
                quantity * self.fee_per_share,
                event.timestamp,
            )
            self._apply_fill(fill)
            emitted.append(fill)
            available -= quantity
        return tuple(emitted)

    def consume(self, event: object) -> tuple[PaperFill, ...] | None:
        """ReplayConsumer hook; non-trade market events do not affect paper fills."""
        if not isinstance(event, TradeEvent):
            return None
        fills = self.process_trade(event)
        return fills or None

    def finalize(self, as_of: datetime) -> PaperBrokerState:
        _require_utc(as_of, "paper replay finalize timestamp")
        if self.last_event_at is not None and as_of < self.last_event_at:
            raise ValueError(
                "paper replay finalization cannot precede processed events"
            )
        return self.state()

    def account(self, marks: dict[str, float]) -> PaperAccountSnapshot:
        unrealized = 0.0
        market_value = 0.0
        for symbol, position in self.positions.items():
            if position.quantity == 0:
                continue
            if symbol not in marks:
                raise ValueError(f"missing paper mark for {symbol}")
            mark = marks[symbol]
            _require_finite(mark, f"paper mark {symbol}")
            if mark <= 0:
                raise ValueError("paper marks must be positive")
            market_value += position.quantity * mark
            unrealized += position.quantity * (mark - position.average_cost)
        fees = sum(fill.fee for fill in self.fills.values())
        realized = (
            sum(position.realized_gross_pnl for position in self.positions.values())
            - fees
        )
        return PaperAccountSnapshot(
            self.cash,
            self.cash + market_value,
            fees,
            realized,
            unrealized,
            tuple(sorted(self.positions.values(), key=lambda item: item.symbol)),
        )

    def state(self) -> PaperBrokerState:
        return PaperBrokerState(
            self.initial_cash,
            self.cash,
            self.fee_per_share,
            tuple(sorted(self.orders.values(), key=lambda item: item.order_id)),
            tuple(sorted(self.fills.values(), key=lambda item: item.fill_id)),
            tuple(sorted(self.positions.values(), key=lambda item: item.symbol)),
            tuple(sorted(self.processed_event_ids)),
            self.last_event_at,
        )

    def save(self, store: ArtifactStore) -> ArtifactRef:
        if store.mode != "paper":
            raise ValueError("paper broker state must use ArtifactStore mode='paper'")
        return store.save("paper-broker-state", self.state())

    @classmethod
    def restore(cls, store: ArtifactStore, reference: ArtifactRef) -> PaperBroker:
        if store.mode != "paper":
            raise ValueError("paper broker state must use ArtifactStore mode='paper'")
        state = store.load(reference)
        if not isinstance(state, PaperBrokerState):
            raise TypeError("paper broker artifact did not contain PaperBrokerState")
        broker = cls(state.initial_cash, fee_per_share=state.fee_per_share)
        broker._restore_state(state)
        report = broker.reconcile()
        if not report.ok:
            raise ValueError(
                "persisted paper broker state failed reconciliation: "
                + report.discrepancies[0]
            )
        return broker

    def _restore_state(self, state: PaperBrokerState) -> None:
        """Restore a complete in-memory snapshot after failed replay work."""
        self.initial_cash = state.initial_cash
        self.cash = state.cash
        self.fee_per_share = state.fee_per_share
        self.orders = {order.order_id: order for order in state.orders}
        self.fills = {fill.fill_id: fill for fill in state.fills}
        self.positions = {position.symbol: position for position in state.positions}
        self.processed_event_ids = set(state.processed_event_ids)
        self.last_event_at = state.last_event_at

    def reconcile(self) -> ReconciliationReport:
        expected_cash = self.initial_cash
        expected_positions: dict[str, PaperPosition] = {}
        discrepancies: list[str] = []
        filled_by_order: dict[str, float] = {}
        for fill in sorted(
            self.fills.values(), key=lambda item: (item.timestamp, item.fill_id)
        ):
            order = self.orders.get(fill.order_id)
            if order is None:
                discrepancies.append(
                    f"fill {fill.fill_id} references missing order {fill.order_id}"
                )
                continue
            filled_by_order[fill.order_id] = (
                filled_by_order.get(fill.order_id, 0.0) + fill.quantity
            )
            expected_cash = self._ledger_apply(expected_cash, expected_positions, fill)
        for order_id, order in self.orders.items():
            expected_filled = filled_by_order.get(order_id, 0.0)
            if not math.isclose(
                order.filled_quantity, expected_filled, rel_tol=1e-9, abs_tol=1e-9
            ):
                discrepancies.append(
                    f"order {order_id} filled quantity does not match fill ledger"
                )
        if not math.isclose(self.cash, expected_cash, rel_tol=1e-9, abs_tol=1e-9):
            discrepancies.append("paper cash does not match fill ledger")
        symbols = set(expected_positions) | set(self.positions)
        for symbol in sorted(symbols):
            expected = expected_positions.get(symbol, PaperPosition(symbol, 0.0, 0.0))
            actual = self.positions.get(symbol, PaperPosition(symbol, 0.0, 0.0))
            for field_name in ("quantity", "average_cost", "realized_gross_pnl"):
                if not math.isclose(
                    getattr(expected, field_name),
                    getattr(actual, field_name),
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                ):
                    discrepancies.append(
                        f"paper position {symbol} {field_name} does not match fill ledger"
                    )
        return ReconciliationReport(
            not discrepancies, tuple(discrepancies), expected_cash, self.cash
        )

    def _apply_fill(self, fill: PaperFill) -> None:
        if fill.fill_id in self.fills:
            if self.fills[fill.fill_id] != fill:
                raise ValueError(
                    f"paper fill_id {fill.fill_id} was reused with different terms"
                )
            return
        order = self._order(fill.order_id)
        if fill.quantity <= 0 or fill.quantity > order.remaining_quantity + 1e-12:
            raise ValueError("paper fill quantity exceeds remaining order quantity")
        self.cash = self._ledger_apply(self.cash, self.positions, fill)
        self.fills[fill.fill_id] = fill
        filled = order.filled_quantity + fill.quantity
        status = (
            PaperOrderStatus.FILLED
            if math.isclose(filled, order.quantity, rel_tol=1e-9, abs_tol=1e-9)
            else PaperOrderStatus.PARTIALLY_FILLED
        )
        self.orders[order.order_id] = replace(
            order, status=status, filled_quantity=filled
        )

    @staticmethod
    def _ledger_apply(
        cash: float, positions: dict[str, PaperPosition], fill: PaperFill
    ) -> float:
        position = positions.get(fill.symbol, PaperPosition(fill.symbol, 0.0, 0.0))
        if fill.side is PaperOrderSide.BUY:
            cost = fill.quantity * fill.price
            new_quantity = position.quantity + fill.quantity
            average = (
                (position.quantity * position.average_cost + cost) / new_quantity
                if new_quantity
                else 0.0
            )
            positions[fill.symbol] = replace(
                position, quantity=new_quantity, average_cost=average
            )
            return cash - cost - fill.fee
        if fill.quantity > position.quantity + 1e-12:
            raise ValueError("paper sell fill would create a short position")
        realized = position.realized_gross_pnl + fill.quantity * (
            fill.price - position.average_cost
        )
        new_quantity = position.quantity - fill.quantity
        positions[fill.symbol] = PaperPosition(
            fill.symbol,
            new_quantity,
            position.average_cost if new_quantity > 1e-12 else 0.0,
            realized,
        )
        return cash + fill.quantity * fill.price - fill.fee

    def _order(self, order_id: str) -> PaperOrder:
        try:
            return self.orders[order_id]
        except KeyError as exc:
            raise KeyError(f"unknown paper order_id {order_id}") from exc

    def _position_quantity(self, symbol: str) -> float:
        position = self.positions.get(symbol)
        return 0.0 if position is None else position.quantity

    def _reserved_sell_quantity(self, symbol: str) -> float:
        active = {PaperOrderStatus.OPEN, PaperOrderStatus.PARTIALLY_FILLED}
        return sum(
            order.remaining_quantity
            for order in self.orders.values()
            if order.symbol == symbol
            and order.side is PaperOrderSide.SELL
            and order.status in active
        )
