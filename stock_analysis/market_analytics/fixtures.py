"""Small deterministic multi-session market-event fixtures."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from .config import AnalyticsConfig
from .models import (
    AggressorSide,
    BarEvent,
    BookAction,
    BookLevel,
    BookSnapshotEvent,
    BookUpdateEvent,
    CallPut,
    InstrumentSpec,
    MarketEvent,
    OptionChainEvent,
    OptionContractInput,
    QuoteEvent,
    SessionTransitionEvent,
    Side,
    TradeEvent,
)
from .providers import CapabilityRegistry
from .replay import ReplayProvider

FIXTURE_START = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
_SESSION_GAP = timedelta(days=3)


def build_full_fixture() -> tuple[ReplayProvider, InstrumentSpec, AnalyticsConfig]:
    instrument = InstrumentSpec("AAA", "XNAS", 0.05, 2)
    config = AnalyticsConfig()
    first_close = FIXTURE_START + timedelta(hours=5)
    second_open = FIXTURE_START + _SESSION_GAP
    second_close = second_open + timedelta(hours=5)
    third_open = second_open + timedelta(days=1)
    third_close = third_open + timedelta(hours=5)
    levels = _book_levels()

    events: list[MarketEvent] = [
        _transition(FIXTURE_START, "2026-01-02", True),
        BookSnapshotEvent("AAA", FIXTURE_START, "fixture", "depth", 7, levels),
        BookUpdateEvent(
            "AAA",
            FIXTURE_START,
            "fixture",
            "depth",
            9,
            BookAction.MODIFY,
            Side.BID,
            100.0,
            12.0,
        ),
        BookSnapshotEvent("AAA", FIXTURE_START, "fixture", "depth", 20, levels),
        QuoteEvent("AAA", FIXTURE_START, "fixture", "quotes", 100.0, 100.05, 10.0, 5.0),
    ]
    events.extend(
        _trade(FIXTURE_START, price, size, side, trade_id)
        for price, size, side, trade_id in (
            (100.0, 30.0, AggressorSide.BUY, "stack-buy-1"),
            (99.95, 5.0, AggressorSide.SELL, "stack-sell-1"),
            (100.05, 30.0, AggressorSide.BUY, "stack-buy-2"),
            (100.0, 5.0, AggressorSide.SELL, "stack-sell-2"),
            (100.10, 30.0, AggressorSide.BUY, "stack-buy-3"),
            (100.05, 5.0, AggressorSide.SELL, "stack-sell-3"),
        )
    )
    events.extend(
        _trade(
            FIXTURE_START + timedelta(minutes=index), price, size, side, f"flow-{index}"
        )
        for index, (price, size, side) in enumerate(
            (
                (100.0, 20.0, AggressorSide.BUY),
                (101.0, 18.0, AggressorSide.BUY),
                (102.0, 4.0, AggressorSide.BUY),
                (103.0, 8.0, AggressorSide.SELL),
            )
        )
    )
    events.extend(
        _bar(FIXTURE_START + timedelta(minutes=offset), price)
        for offset, price in (
            (0, 100.0),
            (1, 100.05),
            (2, 100.10),
            (3, 103.0),
        )
    )
    events.extend(
        _bar(FIXTURE_START + timedelta(minutes=30), price) for price in (100.0, 100.10)
    )
    events.extend(
        (
            BookSnapshotEvent("AAA", first_close, "fixture", "depth", 21, levels),
            _chain(first_close, root=False),
            SessionTransitionEvent(
                "AAA", first_close, "fixture", "sessions", "2026-01-02", False
            ),
            SessionTransitionEvent(
                "AAA", second_open, "fixture", "sessions", "2026-01-05", True
            ),
            _bar(second_open, 100.05, low=100.05, high=100.06),
            SessionTransitionEvent(
                "AAA", second_close, "fixture", "sessions", "2026-01-05", False
            ),
            SessionTransitionEvent(
                "AAA", third_open, "fixture", "sessions", "2026-01-06", True
            ),
            _trade(third_open, 101.0, 5.0, AggressorSide.BUY, "session-3"),
            _bar(third_open, 100.05, low=100.0, high=100.1),
            BookSnapshotEvent("AAA", third_close, "fixture", "depth", 30, levels),
            _chain(third_close, root=True),
            SessionTransitionEvent(
                "AAA", third_close, "fixture", "sessions", "2026-01-06", False
            ),
        )
    )
    return ReplayProvider(events, _capabilities()), instrument, config


def build_no_root_fixture() -> tuple[ReplayProvider, InstrumentSpec, AnalyticsConfig]:
    instrument = InstrumentSpec("AAA", "XNAS", 0.05, 2)
    events: tuple[MarketEvent, ...] = (
        _chain(FIXTURE_START, root=False, include_far=False),
    )
    return ReplayProvider(events, _capabilities()), instrument, AnalyticsConfig()


def _book_levels() -> tuple[BookLevel, ...]:
    return tuple(
        [BookLevel(Side.BID, 100.00 - index * 0.05, 10.0 + index) for index in range(5)]
        + [
            BookLevel(Side.ASK, 100.05 + index * 0.05, 5.0 + index)
            for index in range(5)
        ]
    )


def _bar(
    timestamp: datetime,
    price: float,
    *,
    low: float | None = None,
    high: float | None = None,
) -> BarEvent:
    return BarEvent(
        "AAA",
        timestamp,
        "fixture",
        "bars",
        price,
        high if high is not None else price,
        low if low is not None else price,
        price,
        0.0,
    )


def _trade(
    timestamp: datetime,
    price: float,
    size: float,
    side: AggressorSide,
    trade_id: str,
) -> TradeEvent:
    return TradeEvent(
        "AAA", timestamp, "fixture", "trades", price, size, side, trade_id
    )


def _transition(
    timestamp: datetime, session_id: str, is_open: bool
) -> SessionTransitionEvent:
    return SessionTransitionEvent(
        "AAA", timestamp, "fixture", "sessions", session_id, is_open
    )


def _chain(
    timestamp: datetime, *, root: bool, include_far: bool = True
) -> OptionChainEvent:
    expirations = (
        (date(2026, 1, 9), date(2026, 2, 13)) if include_far else (date(2026, 1, 9),)
    )
    contracts: list[OptionContractInput] = []
    for expiration in expirations:
        term_adjustment = 0.0 if expiration == expirations[0] else 0.05
        if root:
            specifications: tuple[tuple[float, CallPut, float, float, float], ...] = (
                (95.0, CallPut.CALL, 0.75, 0.01, 0.20),
                (105.0, CallPut.PUT, -0.25, 0.04, 0.30),
                (100.0, CallPut.CALL, 0.50, 0.02, 0.25),
                (100.0, CallPut.PUT, -0.50, 0.02, 0.35),
            )
        else:
            specifications = (
                (95.0, CallPut.CALL, 0.75, 0.01, 0.20),
                (105.0, CallPut.CALL, 0.55, 0.01, 0.22),
            )
        contracts.extend(
            _option(
                timestamp,
                expiration,
                strike,
                call_put,
                delta,
                gamma,
                iv + term_adjustment,
            )
            for strike, call_put, delta, gamma, iv in specifications
        )
    return OptionChainEvent(
        "AAA", timestamp, "fixture", "options", 100.0, tuple(contracts)
    )


def _option(
    timestamp: datetime,
    expiration: date,
    strike: float,
    call_put: CallPut,
    delta: float,
    gamma: float,
    iv: float,
) -> OptionContractInput:
    return OptionContractInput(
        underlying="AAA",
        expiration=expiration,
        strike=strike,
        call_put=call_put,
        contract_multiplier=100.0,
        bid=1.0,
        ask=1.1,
        last=1.05,
        volume=10.0,
        open_interest=100.0,
        iv=iv,
        delta=delta,
        gamma=gamma,
        theta=-0.01,
        vega=0.10,
        quote_timestamp=timestamp,
        trade_timestamp=timestamp,
        oi_as_of=timestamp,
        greeks_source="fixture",
        iv_source="fixture",
        bid_size=20.0,
        ask_size=20.0,
    )


def _capabilities() -> CapabilityRegistry:
    return CapabilityRegistry(
        supports_l2=True,
        supports_trade_side=True,
        supports_options_chain=True,
        supports_iv=True,
        supports_greeks=True,
        supports_open_interest=True,
        supports_historical_ticks=True,
        supports_option_volume=True,
        supports_option_bid_ask=True,
    )
