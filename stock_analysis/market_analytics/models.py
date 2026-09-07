"""Typed market events and provenance-aware metric values.

The analytics package deliberately keeps its boundary independent of vendor
SDKs.  Events are immutable so a replay can be run repeatedly without an
analytics component mutating the source fixture.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from math import isfinite
from typing import Any


class MetricStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    PARTIAL = "partial"
    STALE = "stale"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"


class Provenance(StrEnum):
    OBSERVED = "observed"
    DERIVED_FROM_OBSERVED = "derived_from_observed"
    MODELED = "modeled"
    APPROXIMATE = "approximate"
    UNAVAILABLE = "unavailable"


class Side(StrEnum):
    BID = "bid"
    ASK = "ask"


class BookAction(StrEnum):
    ADD = "add"
    MODIFY = "modify"
    CANCEL = "cancel"


class AggressorSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class CallPut(StrEnum):
    CALL = "call"
    PUT = "put"


class VolumeInputMode(StrEnum):
    TRADES = "trades"
    BARS = "bars"


def _require_utc(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{label} must be timezone-aware UTC")


def _require_finite(value: float, label: str) -> None:
    if not isfinite(value):
        raise ValueError(f"{label} must be finite")


@dataclass(frozen=True, slots=True)
class MetricMetadata:
    as_of: datetime
    provider: str
    dataset: str
    venue_scope: str
    calculation_version: str = "1"
    freshness_ms: int | None = None
    status: MetricStatus = MetricStatus.OK
    methodology: str = ""
    quality_score: float = 100.0
    observed_or_modeled: Provenance = Provenance.DERIVED_FROM_OBSERVED
    reason: str | None = None

    def __post_init__(self) -> None:
        _require_utc(self.as_of, "as_of")
        if not self.provider:
            raise ValueError("provider must not be empty")
        if not self.dataset:
            raise ValueError("dataset must not be empty")
        if self.freshness_ms is not None and self.freshness_ms < 0:
            raise ValueError("freshness_ms must be nonnegative")
        _require_finite(float(self.quality_score), "quality_score")
        if not 0 <= self.quality_score <= 100:
            raise ValueError("quality_score must be between 0 and 100")

    @classmethod
    def unavailable(
        cls,
        *,
        as_of: datetime,
        provider: str,
        dataset: str,
        venue_scope: str,
        reason: str,
        methodology: str = "",
        calculation_version: str = "1",
        freshness_ms: int | None = None,
    ) -> MetricMetadata:
        return cls(
            as_of=as_of,
            provider=provider,
            dataset=dataset,
            venue_scope=venue_scope,
            calculation_version=calculation_version,
            freshness_ms=freshness_ms,
            status=MetricStatus.UNAVAILABLE,
            methodology=methodology,
            quality_score=0.0,
            observed_or_modeled=Provenance.UNAVAILABLE,
            reason=reason,
        )


@dataclass(frozen=True)
class MetricResult[MetricValue]:
    value: MetricValue | None
    metadata: MetricMetadata

    @property
    def available(self) -> bool:
        return (
            self.value is not None
            and self.metadata.status is not MetricStatus.UNAVAILABLE
        )


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    symbol: str
    venue: str
    tick_size: float
    price_precision: int = 2
    contract_multiplier: float = 100.0
    atr: float | None = None
    instrument_id: str | None = None
    asset_class: str = "equity"
    currency: str = "USD"
    exchange_timezone: str = "America/New_York"

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol must not be empty")
        if not self.venue:
            raise ValueError("venue must not be empty")
        _require_finite(float(self.tick_size), "tick_size")
        if self.tick_size <= 0:
            raise ValueError("tick_size must be positive")
        if self.price_precision < 0:
            raise ValueError("price_precision must be nonnegative")
        _require_finite(float(self.contract_multiplier), "contract_multiplier")
        if self.contract_multiplier <= 0:
            raise ValueError("contract_multiplier must be positive")
        if self.atr is not None:
            _require_finite(float(self.atr), "atr")
            if self.atr <= 0:
                raise ValueError("atr must be positive")
        if self.instrument_id is not None and not self.instrument_id:
            raise ValueError("instrument_id must not be empty")
        if not self.asset_class or not self.currency or not self.exchange_timezone:
            raise ValueError("instrument identity metadata must not be empty")

    @property
    def stable_id(self) -> str:
        return self.instrument_id or (
            f"{self.asset_class}:{self.venue}:{self.symbol}:{self.currency}"
        )

    def price_to_ticks(self, price: float) -> int:
        _require_finite(float(price), "price")
        return round(price / self.tick_size)

    def ticks_to_price(self, ticks: int) -> float:
        return round(ticks * self.tick_size, self.price_precision)

    def normalize_price(self, price: float) -> float:
        return self.ticks_to_price(self.price_to_ticks(price))


@dataclass(frozen=True, slots=True)
class BookLevel:
    side: Side
    price: float
    size: float
    order_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", Side(self.side))
        _require_finite(float(self.price), "price")
        _require_finite(float(self.size), "size")
        if self.price <= 0:
            raise ValueError("price must be positive")
        if self.size < 0:
            raise ValueError("size must be nonnegative")


@dataclass(frozen=True, slots=True)
class QuoteEvent:
    symbol: str
    timestamp: datetime
    provider: str
    dataset: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float

    def __post_init__(self) -> None:
        _require_utc(self.timestamp, "timestamp")
        for value, label in (
            (self.bid, "bid"),
            (self.ask, "ask"),
            (self.bid_size, "bid_size"),
            (self.ask_size, "ask_size"),
        ):
            _require_finite(float(value), label)
        if self.bid <= 0 or self.ask <= 0:
            raise ValueError("quote prices must be positive")
        if self.bid_size < 0 or self.ask_size < 0:
            raise ValueError("quote sizes must be nonnegative")


@dataclass(frozen=True, slots=True)
class TradeEvent:
    symbol: str
    timestamp: datetime
    provider: str
    dataset: str
    price: float
    size: float
    aggressor_side: AggressorSide | None
    trade_id: str

    def __post_init__(self) -> None:
        _require_utc(self.timestamp, "timestamp")
        _require_finite(float(self.price), "price")
        _require_finite(float(self.size), "size")
        if self.price <= 0:
            raise ValueError("price must be positive")
        if self.size <= 0:
            raise ValueError("size must be positive")
        if not self.trade_id:
            raise ValueError("trade_id must not be empty")
        if self.aggressor_side is not None:
            object.__setattr__(
                self, "aggressor_side", AggressorSide(self.aggressor_side)
            )


@dataclass(frozen=True, slots=True)
class BookSnapshotEvent:
    symbol: str
    timestamp: datetime
    provider: str
    dataset: str
    sequence: int
    levels: tuple[BookLevel, ...]

    def __post_init__(self) -> None:
        _require_utc(self.timestamp, "timestamp")
        if self.sequence < 0:
            raise ValueError("sequence must be nonnegative")
        object.__setattr__(self, "levels", tuple(self.levels))


@dataclass(frozen=True, slots=True)
class BookUpdateEvent:
    symbol: str
    timestamp: datetime
    provider: str
    dataset: str
    sequence: int
    action: BookAction
    side: Side
    price: float
    size: float
    order_id: str | None = None

    def __post_init__(self) -> None:
        _require_utc(self.timestamp, "timestamp")
        if self.sequence < 0:
            raise ValueError("sequence must be nonnegative")
        object.__setattr__(self, "action", BookAction(self.action))
        object.__setattr__(self, "side", Side(self.side))
        _require_finite(float(self.price), "price")
        _require_finite(float(self.size), "size")
        if self.price <= 0 or self.size < 0:
            raise ValueError("book update price must be positive and size nonnegative")


@dataclass(frozen=True, slots=True)
class BarEvent:
    symbol: str
    timestamp: datetime
    provider: str
    dataset: str
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        _require_utc(self.timestamp, "timestamp")
        values = (self.open, self.high, self.low, self.close, self.volume)
        for value, label in zip(
            values, ("open", "high", "low", "close", "volume"), strict=True
        ):
            _require_finite(float(value), label)
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("bar prices must be positive")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("bar high is below a bar price")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("bar low is above a bar price")
        if self.volume < 0:
            raise ValueError("bar volume must be nonnegative")


@dataclass(frozen=True, slots=True)
class OptionContractInput:
    underlying: str
    expiration: date
    strike: float
    call_put: CallPut
    contract_multiplier: float
    bid: float | None
    ask: float | None
    last: float | None
    volume: float | None
    open_interest: float | None
    iv: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    quote_timestamp: datetime | None
    trade_timestamp: datetime | None
    oi_as_of: datetime | None
    greeks_source: str | None
    iv_source: str | None
    adjusted: bool = False
    adjustment_reason: str | None = None
    bid_size: float | None = None
    ask_size: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "call_put", CallPut(self.call_put))
        if not self.underlying:
            raise ValueError("underlying must not be empty")
        if not isinstance(self.expiration, date):
            raise TypeError("expiration must be a date")
        for numeric_value, label in (
            (self.strike, "strike"),
            (self.contract_multiplier, "contract_multiplier"),
        ):
            _require_finite(float(numeric_value), label)
        for optional_value, label in (
            (self.bid, "bid"),
            (self.ask, "ask"),
            (self.last, "last"),
            (self.volume, "volume"),
            (self.open_interest, "open_interest"),
            (self.iv, "iv"),
            (self.delta, "delta"),
            (self.gamma, "gamma"),
            (self.theta, "theta"),
            (self.vega, "vega"),
            (self.bid_size, "bid_size"),
            (self.ask_size, "ask_size"),
        ):
            if optional_value is not None:
                _require_finite(float(optional_value), label)
        for timestamp, label in (
            (self.quote_timestamp, "quote_timestamp"),
            (self.trade_timestamp, "trade_timestamp"),
            (self.oi_as_of, "oi_as_of"),
        ):
            if timestamp is not None:
                _require_utc(timestamp, label)


@dataclass(frozen=True, slots=True)
class OptionChainEvent:
    symbol: str
    timestamp: datetime
    provider: str
    dataset: str
    spot: float
    contracts: tuple[OptionContractInput, ...]

    def __post_init__(self) -> None:
        _require_utc(self.timestamp, "timestamp")
        _require_finite(float(self.spot), "spot")
        if self.spot <= 0:
            raise ValueError("spot must be positive")
        object.__setattr__(self, "contracts", tuple(self.contracts))


@dataclass(frozen=True, slots=True)
class SessionTransitionEvent:
    symbol: str
    timestamp: datetime
    provider: str
    dataset: str
    session_id: str
    is_open: bool

    def __post_init__(self) -> None:
        _require_utc(self.timestamp, "timestamp")
        if not self.session_id:
            raise ValueError("session_id must not be empty")


@dataclass(frozen=True, slots=True)
class CorporateActionEvent:
    symbol: str
    timestamp: datetime
    provider: str
    dataset: str
    action_type: str
    ratio: float
    old_symbol: str | None = None
    new_symbol: str | None = None

    def __post_init__(self) -> None:
        _require_utc(self.timestamp, "timestamp")
        _require_finite(float(self.ratio), "ratio")
        if not self.action_type:
            raise ValueError("action_type must not be empty")
        if self.ratio <= 0:
            raise ValueError("ratio must be positive")


MarketEvent = (
    QuoteEvent
    | TradeEvent
    | BookSnapshotEvent
    | BookUpdateEvent
    | BarEvent
    | OptionChainEvent
    | SessionTransitionEvent
    | CorporateActionEvent
)


@dataclass(frozen=True, slots=True)
class AnalyticsSnapshot:
    as_of: datetime
    symbol: str
    dom: Any
    flow: Any
    vwap: Any
    profiles: Any
    options: Any
    positioning: Any
    data_quality: Any
    volatility: Any = None
    levels: tuple[Any, ...] = ()
    confluence_zones: tuple[Any, ...] = ()
    credit: Any = None
    features: Any = None

    def __post_init__(self) -> None:
        _require_utc(self.as_of, "as_of")
        if not self.symbol:
            raise ValueError("symbol must not be empty")
