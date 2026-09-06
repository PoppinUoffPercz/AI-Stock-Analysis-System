"""Deterministic fixture replay over the shared analytics consumer contract."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Protocol

from .models import (
    BarEvent,
    BookSnapshotEvent,
    BookUpdateEvent,
    CorporateActionEvent,
    MarketEvent,
    OptionChainEvent,
    QuoteEvent,
    TradeEvent,
    _require_utc,
)
from .providers import CapabilityRegistry


class ReplayProvider:
    """Immutable, ordered event source used by tests and offline demos."""

    def __init__(
        self,
        events: Iterable[MarketEvent],
        capabilities: CapabilityRegistry,
        provider: str = "fixture",
    ) -> None:
        self._events = tuple(events)
        self.capabilities = capabilities
        self.provider = provider
        for event in self._events:
            _require_utc(event.timestamp, "event timestamp")

    def events(self, symbol: str | None = None) -> Iterator[MarketEvent]:
        for event in self._events:
            if symbol is None or event.symbol == symbol:
                yield event

    def iter_quotes(self, symbol: str) -> Iterator[QuoteEvent]:
        return (event for event in self.events(symbol) if isinstance(event, QuoteEvent))

    def iter_bars(self, symbol: str) -> Iterator[BarEvent]:
        return (event for event in self.events(symbol) if isinstance(event, BarEvent))

    def iter_depth_events(
        self, symbol: str
    ) -> Iterator[BookSnapshotEvent | BookUpdateEvent]:
        return (
            event
            for event in self.events(symbol)
            if isinstance(event, (BookSnapshotEvent, BookUpdateEvent))
        )

    def iter_trades(self, symbol: str) -> Iterator[TradeEvent]:
        return (event for event in self.events(symbol) if isinstance(event, TradeEvent))

    def iter_option_snapshots(self, symbol: str) -> Iterator[OptionChainEvent]:
        return (
            event
            for event in self.events(symbol)
            if isinstance(event, OptionChainEvent)
        )

    def iter_corporate_actions(self, symbol: str) -> Iterator[CorporateActionEvent]:
        return (
            event
            for event in self.events(symbol)
            if isinstance(event, CorporateActionEvent)
        )


class ReplayConsumer(Protocol):
    def consume(self, event: MarketEvent) -> object | None: ...

    def finalize(self, as_of: datetime) -> object | None: ...


class ReplayEngine:
    def run(
        self,
        provider: ReplayProvider,
        consumer: ReplayConsumer,
        symbol: str,
    ) -> tuple[object, ...]:
        consume = getattr(consumer, "consume", None)
        finalize = getattr(consumer, "finalize", None)
        if not callable(consume) or not callable(finalize):
            raise TypeError(
                "replay consumer must define callable consume and finalize methods"
            )

        events = tuple(provider.events(symbol))
        snapshots: list[object] = []
        for event in events:
            result = consume(event)
            if result is not None:
                snapshots.append(result)
        if events:
            result = finalize(events[-1].timestamp)
            if result is not None:
                snapshots.append(result)
        return tuple(snapshots)
