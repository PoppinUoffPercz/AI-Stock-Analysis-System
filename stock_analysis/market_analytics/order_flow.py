"""Trade classification, footprint cells, cumulative delta, and VI zones."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from statistics import linear_regression

from .config import AnalyticsConfig, FlowConfig
from .models import (
    AggressorSide,
    InstrumentSpec,
    MetricMetadata,
    MetricResult,
    MetricStatus,
    Provenance,
    QuoteEvent,
    TradeEvent,
    _require_utc,
)


@dataclass(frozen=True, slots=True)
class TradeClassification:
    side: AggressorSide | None
    provenance: Provenance
    confidence: float
    reason: str


@dataclass(frozen=True, slots=True)
class FootprintCell:
    bid_aggressor_volume: float
    ask_aggressor_volume: float
    total_volume: float
    delta: float


@dataclass(frozen=True, slots=True)
class ImbalanceZone:
    bar_timestamp: datetime
    price_low: float
    price_high: float
    direction: str
    ratio: float | None
    number_of_levels: int
    volume: float
    age: timedelta
    retested: bool
    failed: bool
    metadata: MetricMetadata


@dataclass(frozen=True, slots=True)
class BarSummary:
    timestamp: datetime
    price: float
    delta: float
    cvd: float | None = None

    def __post_init__(self) -> None:
        _require_utc(self.timestamp, "bar timestamp")
        if not isfinite(self.price) or self.price <= 0:
            raise ValueError("bar price must be positive and finite")
        if not isfinite(self.delta):
            raise ValueError("bar delta must be finite")
        if self.cvd is not None and not isfinite(self.cvd):
            raise ValueError("bar CVD must be finite")


@dataclass(frozen=True, slots=True)
class FlowDeltaFlipEvent:
    timestamp: datetime
    direction: str
    pre_flip_exhaustion_score: float
    delta_before: float
    delta_after: float
    cvd_slope_before: float
    cvd_slope_after: float
    confirmation_score: float


@dataclass(frozen=True, slots=True)
class ExhaustionSnapshot:
    as_of: datetime
    bullish_exhaustion_score: MetricResult[float]
    bearish_exhaustion_score: MetricResult[float]
    flow_flip: FlowDeltaFlipEvent | None = None


@dataclass(frozen=True, slots=True)
class FlowSnapshot:
    as_of: datetime
    cells: dict[tuple[datetime, float], FootprintCell]
    flow_delta: MetricResult[float]
    cvd: MetricResult[float]
    quality: MetricResult[float]
    horizontal_imbalances: tuple[ImbalanceZone, ...] = ()
    diagonal_imbalances: tuple[ImbalanceZone, ...] = ()
    stacked_imbalances: tuple[ImbalanceZone, ...] = ()
    exhaustion: ExhaustionSnapshot | None = None


@dataclass
class _MutableCell:
    bid: float = 0.0
    ask: float = 0.0
    unknown: float = 0.0


class TradeClassifier:
    def __init__(self, fallback_confidence: float = 0.5) -> None:
        if not 0 <= fallback_confidence <= 1:
            raise ValueError("fallback_confidence must be between zero and one")
        self.fallback_confidence = fallback_confidence

    def classify(
        self,
        trade: TradeEvent,
        quote: QuoteEvent | None = None,
        *,
        allow_observed_side: bool = True,
    ) -> TradeClassification:
        if allow_observed_side and trade.aggressor_side is not None:
            return TradeClassification(
                trade.aggressor_side,
                Provenance.OBSERVED,
                1.0,
                "explicit aggressor side supplied by provider",
            )
        if quote is not None and quote.symbol == trade.symbol:
            if trade.price >= quote.ask:
                return TradeClassification(
                    AggressorSide.BUY,
                    Provenance.DERIVED_FROM_OBSERVED,
                    self.fallback_confidence,
                    "classified at or through the observed ask",
                )
            if trade.price <= quote.bid:
                return TradeClassification(
                    AggressorSide.SELL,
                    Provenance.DERIVED_FROM_OBSERVED,
                    self.fallback_confidence,
                    "classified at or through the observed bid",
                )
        return TradeClassification(
            None,
            Provenance.UNAVAILABLE,
            0.0,
            "trade has no explicit side and is between quote bounds",
        )


class FootprintEngine:
    def __init__(
        self,
        instrument: InstrumentSpec,
        config: AnalyticsConfig,
        provider: str = "fixture",
        dataset: str = "trades",
        *,
        supports_trade_side: bool = True,
    ) -> None:
        self.instrument = instrument
        self.config = config
        self.provider = provider
        self.dataset = dataset
        self.supports_trade_side = supports_trade_side
        self._classifier = TradeClassifier(config.flow.fallback_confidence)
        self._cells: dict[tuple[datetime, int], _MutableCell] = {}
        self._bar_deltas: dict[datetime, float] = {}
        self._unknown_volume = 0.0
        self._unknown_trades = 0

    def consume(
        self, trade: TradeEvent, quote: QuoteEvent | None = None
    ) -> FlowSnapshot:
        _require_utc(trade.timestamp, "trade timestamp")
        self.provider = trade.provider
        self.dataset = trade.dataset
        bar_timestamp = self._bar_start(trade.timestamp)
        key = (bar_timestamp, self.instrument.price_to_ticks(trade.price))
        cell = self._cells.setdefault(key, _MutableCell())
        classification = self._classifier.classify(
            trade,
            quote,
            allow_observed_side=self.supports_trade_side,
        )
        if classification.side is AggressorSide.BUY:
            cell.ask += trade.size
        elif classification.side is AggressorSide.SELL:
            cell.bid += trade.size
        else:
            cell.unknown += trade.size
            self._unknown_volume += trade.size
            self._unknown_trades += 1
        self._bar_deltas[bar_timestamp] = self._bar_deltas.get(bar_timestamp, 0.0) + (
            trade.size
            if classification.side is AggressorSide.BUY
            else -trade.size
            if classification.side is AggressorSide.SELL
            else 0.0
        )
        return self.snapshot(trade.timestamp)

    def snapshot(self, as_of: datetime) -> FlowSnapshot:
        _require_utc(as_of, "as_of")
        cells = {
            (bar, self.instrument.ticks_to_price(tick)): FootprintCell(
                bid_aggressor_volume=cell.bid,
                ask_aggressor_volume=cell.ask,
                total_volume=cell.bid + cell.ask + cell.unknown,
                delta=cell.ask - cell.bid,
            )
            for (bar, tick), cell in self._cells.items()
        }
        latest_bar = max(
            (bar for bar in self._bar_deltas if bar <= as_of), default=None
        )
        if latest_bar is None:
            flow_delta = self._unavailable(as_of, "no trades consumed")
            cvd = self._unavailable(as_of, "no trades consumed")
        else:
            flow_delta = self._metric(
                self._bar_deltas[latest_bar],
                as_of,
                status=(
                    MetricStatus.DEGRADED if self._unknown_volume else MetricStatus.OK
                ),
                reason=(
                    "unclassified trade volume excluded from delta"
                    if self._unknown_volume
                    else None
                ),
                quality=self._quality_value(),
                methodology="ask-aggressor volume minus bid-aggressor volume per bar",
            )
            cvd = self._metric(
                sum(
                    delta
                    for bar, delta in self._bar_deltas.items()
                    if bar <= latest_bar
                ),
                as_of,
                status=(
                    MetricStatus.DEGRADED if self._unknown_volume else MetricStatus.OK
                ),
                reason=(
                    "unclassified trade volume excluded from cumulative delta"
                    if self._unknown_volume
                    else None
                ),
                quality=self._quality_value(),
                methodology="cumulative sum of completed and current bar deltas",
            )
        quality = self._metric(
            self._quality_value(),
            as_of,
            status=MetricStatus.DEGRADED if self._unknown_volume else MetricStatus.OK,
            reason=(
                "positive-volume trades were unclassifiable"
                if self._unknown_volume
                else None
            ),
            quality=self._quality_value(),
            methodology="100 minus configured penalty per unclassifiable trade",
        )
        horizontal = self._horizontal_imbalances(as_of)
        diagonal = self._diagonal_imbalances(as_of)
        return FlowSnapshot(
            as_of=as_of,
            cells=cells,
            flow_delta=flow_delta,
            cvd=cvd,
            quality=quality,
            horizontal_imbalances=horizontal,
            diagonal_imbalances=diagonal,
            stacked_imbalances=self._stacked_imbalances(diagonal),
        )

    def bar_summary(self, timestamp: datetime, price: float) -> BarSummary:
        _require_utc(timestamp, "bar timestamp")
        bar_timestamp = self._bar_start(timestamp)
        delta = self._bar_deltas.get(bar_timestamp, 0.0)
        cvd = sum(
            value for bar, value in self._bar_deltas.items() if bar <= bar_timestamp
        )
        return BarSummary(timestamp, price, delta, cvd)

    def reset(self) -> None:
        self._cells.clear()
        self._bar_deltas.clear()
        self._unknown_volume = 0.0
        self._unknown_trades = 0

    def _bar_start(self, timestamp: datetime) -> datetime:
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        seconds = self.config.flow.bar_duration.total_seconds()
        offset = int((timestamp - epoch).total_seconds() // seconds * seconds)
        return epoch + timedelta(seconds=offset)

    def _horizontal_imbalances(self, as_of: datetime) -> tuple[ImbalanceZone, ...]:
        by_bar: dict[datetime, list[tuple[int, _MutableCell]]] = {}
        for (bar, tick), cell in self._cells.items():
            by_bar.setdefault(bar, []).append((tick, cell))
        zones: list[ImbalanceZone] = []
        for bar, cells in by_bar.items():
            for tick, cell in sorted(cells):
                if cell.ask > 0:
                    zone = self._imbalance(
                        bar,
                        tick,
                        "bullish",
                        cell.ask,
                        cell.bid,
                        as_of,
                        "horizontal ask-aggressor imbalance",
                    )
                    if zone is not None:
                        zones.append(zone)
                if cell.bid > 0:
                    zone = self._imbalance(
                        bar,
                        tick,
                        "bearish",
                        cell.bid,
                        cell.ask,
                        as_of,
                        "horizontal bid-aggressor imbalance",
                    )
                    if zone is not None:
                        zones.append(zone)
        return tuple(zones)

    def _diagonal_imbalances(self, as_of: datetime) -> tuple[ImbalanceZone, ...]:
        by_bar: dict[datetime, dict[int, _MutableCell]] = {}
        for (bar, tick), cell in self._cells.items():
            by_bar.setdefault(bar, {})[tick] = cell
        zones: list[ImbalanceZone] = []
        for bar, cells in by_bar.items():
            for tick, cell in sorted(cells.items()):
                below = cells.get(tick - 1)
                above = cells.get(tick + 1)
                if cell.ask > 0:
                    zone = self._imbalance(
                        bar,
                        tick,
                        "bullish",
                        cell.ask,
                        below.bid if below else 0.0,
                        as_of,
                        "diagonal ask at P divided by bid one tick below P",
                    )
                    if zone is not None:
                        zones.append(zone)
                if cell.bid > 0:
                    zone = self._imbalance(
                        bar,
                        tick,
                        "bearish",
                        cell.bid,
                        above.ask if above else 0.0,
                        as_of,
                        "diagonal bid at P divided by ask one tick above P",
                    )
                    if zone is not None:
                        zones.append(zone)
        return tuple(zones)

    def _imbalance(
        self,
        bar: datetime,
        tick: int,
        direction: str,
        numerator: float,
        reference: float,
        as_of: datetime,
        methodology: str,
    ) -> ImbalanceZone | None:
        if numerator <= 0:
            return None
        if reference > 0:
            ratio = numerator / reference
            if ratio < self.config.flow.imbalance_ratio:
                return None
            reason = None
        else:
            ratio = None
            reason = "positive numerator with zero comparison volume"
        price = self.instrument.ticks_to_price(tick)
        return ImbalanceZone(
            bar_timestamp=bar,
            price_low=price,
            price_high=price,
            direction=direction,
            ratio=ratio,
            number_of_levels=1,
            volume=numerator,
            age=max(as_of - bar, timedelta(0)),
            retested=False,
            failed=False,
            metadata=MetricMetadata(
                as_of=as_of,
                provider=self.provider,
                dataset=self.dataset,
                venue_scope=self.instrument.venue,
                status=MetricStatus.DEGRADED if reason else MetricStatus.OK,
                methodology=methodology,
                quality_score=80.0 if reason else 100.0,
                observed_or_modeled=Provenance.DERIVED_FROM_OBSERVED,
                reason=reason,
            ),
        )

    def _stacked_imbalances(
        self, zones: tuple[ImbalanceZone, ...]
    ) -> tuple[ImbalanceZone, ...]:
        grouped: dict[tuple[datetime, str], list[ImbalanceZone]] = {}
        for zone in zones:
            grouped.setdefault((zone.bar_timestamp, zone.direction), []).append(zone)
        stacks: list[ImbalanceZone] = []
        minimum = self.config.flow.min_stacked_levels
        for (_bar, direction), candidates in grouped.items():
            candidates.sort(key=lambda zone: zone.price_low)
            run: list[ImbalanceZone] = []
            for candidate in candidates:
                if run and self.instrument.price_to_ticks(candidate.price_low) != (
                    self.instrument.price_to_ticks(run[-1].price_high) + 1
                ):
                    if len(run) >= minimum:
                        stacks.append(self._merge_stack(run, direction))
                    run = []
                run.append(candidate)
            if len(run) >= minimum:
                stacks.append(self._merge_stack(run, direction))
        stacks.sort(
            key=lambda zone: (zone.bar_timestamp, zone.price_low, zone.direction)
        )
        return tuple(stacks)

    def _merge_stack(self, zones: list[ImbalanceZone], direction: str) -> ImbalanceZone:
        ratios = [zone.ratio for zone in zones]
        ratio = (
            min(value for value in ratios if value is not None)
            if all(value is not None for value in ratios)
            else None
        )
        reason = "stack includes a zero-reference comparison" if ratio is None else None
        first = zones[0]
        return ImbalanceZone(
            bar_timestamp=first.bar_timestamp,
            price_low=min(zone.price_low for zone in zones),
            price_high=max(zone.price_high for zone in zones),
            direction=direction,
            ratio=ratio,
            number_of_levels=len(zones),
            volume=sum(zone.volume for zone in zones),
            age=max(zone.age for zone in zones),
            retested=False,
            failed=False,
            metadata=MetricMetadata(
                as_of=max(zone.metadata.as_of for zone in zones),
                provider=self.provider,
                dataset=self.dataset,
                venue_scope=self.instrument.venue,
                status=MetricStatus.DEGRADED if reason else MetricStatus.OK,
                methodology="contiguous diagonal imbalance stack",
                quality_score=80.0 if reason else 100.0,
                observed_or_modeled=Provenance.DERIVED_FROM_OBSERVED,
                reason=reason,
            ),
        )

    def _quality_value(self) -> float:
        return max(
            0.0,
            100.0
            - self._unknown_trades * self.config.flow.unknown_trade_quality_penalty,
        )

    def _metric(
        self,
        value: float,
        as_of: datetime,
        *,
        methodology: str,
        status: MetricStatus = MetricStatus.OK,
        quality: float = 100.0,
        reason: str | None = None,
    ) -> MetricResult[float]:
        if not isfinite(value):
            return self._unavailable(as_of, "non-finite flow metric")
        return MetricResult(
            value,
            MetricMetadata(
                as_of=as_of,
                provider=self.provider,
                dataset=self.dataset,
                venue_scope=self.instrument.venue,
                status=status,
                methodology=methodology,
                quality_score=quality,
                observed_or_modeled=Provenance.DERIVED_FROM_OBSERVED,
                reason=reason,
            ),
        )

    def _unavailable(self, as_of: datetime, reason: str) -> MetricResult[float]:
        return MetricResult(
            None,
            MetricMetadata.unavailable(
                as_of=as_of,
                provider=self.provider,
                dataset=self.dataset,
                venue_scope=self.instrument.venue,
                reason=reason,
            ),
        )


class FlowDeltaExhaustionDetector:
    def __init__(self, config: FlowConfig) -> None:
        self.config = config
        self._bars: deque[BarSummary] = deque(
            maxlen=max(config.exhaustion_window_bars, config.flip_window_bars) + 1
        )

    def reset(self) -> None:
        self._bars.clear()

    def update(self, bar_summary: BarSummary) -> ExhaustionSnapshot:
        _require_utc(bar_summary.timestamp, "bar timestamp")
        if bar_summary.cvd is None:
            previous_cvd = (self._bars[-1].cvd or 0.0) if self._bars else 0.0
            bar_summary = BarSummary(
                bar_summary.timestamp,
                bar_summary.price,
                bar_summary.delta,
                previous_cvd + bar_summary.delta,
            )
        self._bars.append(bar_summary)
        as_of = bar_summary.timestamp
        bullish = self._exhaustion_score("bullish", as_of)
        bearish = self._exhaustion_score("bearish", as_of)
        return ExhaustionSnapshot(
            as_of=as_of,
            bullish_exhaustion_score=bullish,
            bearish_exhaustion_score=bearish,
            flow_flip=self._flow_flip(as_of),
        )

    def _exhaustion_score(
        self,
        direction: str,
        as_of: datetime,
        source_bars: list[BarSummary] | None = None,
    ) -> MetricResult[float]:
        bars = (list(self._bars) if source_bars is None else source_bars)[
            -self.config.exhaustion_window_bars :
        ]
        if len(bars) < 2:
            return self._metric(
                0.0,
                as_of,
                status=MetricStatus.DEGRADED,
                quality=50.0,
                reason="fewer than two bars for exhaustion features",
            )
        prices = [bar.price for bar in bars]
        deltas = [bar.delta for bar in bars]
        cvds = [bar.cvd if bar.cvd is not None else 0.0 for bar in bars]
        price_slope = self._slope(prices)
        delta_slope = self._slope(deltas)
        cvd_slope = self._slope(cvds)
        max_abs_delta = max(max(abs(delta) for delta in deltas), 1.0)
        price_range = max(max(prices) - min(prices), 1e-12)
        per_bar_price = price_range / max(len(prices) - 1, 1)
        price_direction = self._clip(
            (price_slope if direction == "bearish" else -price_slope)
            / max(per_bar_price, 1e-12)
        )
        delta_weakening = self._clip(
            (-delta_slope if direction == "bearish" else delta_slope) / max_abs_delta
        )
        cvd_stalling = self._clip(
            1.0
            - (max(cvd_slope, 0.0) if direction == "bearish" else max(-cvd_slope, 0.0))
            / max_abs_delta
        )
        divergence = self._clip(
            1.0
            if (
                (direction == "bearish" and price_slope > 0 and delta_slope < 0)
                or (direction == "bullish" and price_slope < 0 and delta_slope > 0)
            )
            else 0.0
        )
        price_per_absolute_delta = abs(prices[-1] - prices[0]) / max(
            sum(abs(delta) for delta in deltas), 1e-12
        )
        expected_efficiency = price_range / max_abs_delta
        absorption = self._clip(
            1.0 - price_per_absolute_delta / max(expected_efficiency, 1e-12)
        )
        features = (
            price_direction,
            delta_weakening,
            cvd_stalling,
            divergence,
            absorption,
        )
        score = self._clip(
            sum(
                weight * feature
                for weight, feature in zip(
                    self.config.exhaustion_weights, features, strict=True
                )
            )
        )
        return self._metric(
            score,
            as_of,
            status=MetricStatus.OK,
            quality=100.0,
            methodology=(
                "weighted clipped price slope, delta slope, CVD stalling, "
                "divergence, and price-per-absolute-delta absorption"
            ),
        )

    def _flow_flip(self, as_of: datetime) -> FlowDeltaFlipEvent | None:
        if len(self._bars) < 2:
            return None
        bars = list(self._bars)
        previous, current = bars[-2], bars[-1]
        if previous.delta > 0 and current.delta < 0:
            direction = "bearish"
            price_confirmed = current.price >= previous.price
        elif previous.delta < 0 and current.delta > 0:
            direction = "bullish"
            price_confirmed = current.price <= previous.price
        else:
            return None
        before = bars[:-1]
        exhaustion = self._exhaustion_score(direction, as_of, before).value or 0.0
        cvd_slope_before = self._slope(
            [bar.cvd or 0.0 for bar in before][-self.config.flip_window_bars :]
        )
        cvd_slope_after = self._slope(
            [bar.cvd or 0.0 for bar in bars[-self.config.flip_window_bars :]]
        )
        max_abs_delta = max(max(abs(bar.delta) for bar in bars), 1.0)
        delta_confirmation = self._clip(abs(current.delta) / max_abs_delta)
        cvd_confirmed = (
            cvd_slope_after < cvd_slope_before
            if direction == "bearish"
            else cvd_slope_after > cvd_slope_before
        )
        confirmation_score = (
            float(price_confirmed) + delta_confirmation + float(cvd_confirmed)
        ) / 3.0
        if confirmation_score < self.config.min_confirmation_score:
            return None
        return FlowDeltaFlipEvent(
            timestamp=as_of,
            direction=direction,
            pre_flip_exhaustion_score=exhaustion,
            delta_before=previous.delta,
            delta_after=current.delta,
            cvd_slope_before=cvd_slope_before,
            cvd_slope_after=cvd_slope_after,
            confirmation_score=confirmation_score,
        )

    @staticmethod
    def _slope(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        return linear_regression(list(range(len(values))), values).slope

    @staticmethod
    def _clip(value: float) -> float:
        return max(0.0, min(1.0, value))

    @staticmethod
    def _metric(
        value: float,
        as_of: datetime,
        *,
        status: MetricStatus,
        quality: float,
        reason: str | None = None,
        methodology: str = "",
    ) -> MetricResult[float]:
        return MetricResult(
            value,
            MetricMetadata(
                as_of=as_of,
                provider="analytics",
                dataset="flow",
                venue_scope="",
                status=status,
                methodology=methodology,
                quality_score=quality,
                observed_or_modeled=Provenance.DERIVED_FROM_OBSERVED,
                reason=reason,
            ),
        )
