"""Stateful order-book reconstruction and displayed-depth metrics."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import isfinite
from statistics import linear_regression, median

from .config import AnalyticsConfig
from .models import (
    BookAction,
    BookLevel,
    BookSnapshotEvent,
    BookUpdateEvent,
    InstrumentSpec,
    MetricMetadata,
    MetricResult,
    MetricStatus,
    Provenance,
    QuoteEvent,
    SessionTransitionEvent,
    Side,
    TradeEvent,
    _require_utc,
)


@dataclass(frozen=True, slots=True)
class LiquidityWall:
    price: float
    side: Side
    size: float
    normalized_size: float
    distance_bps: float
    age_ms: int
    persistence_score: float
    replenishment_score: float
    cancel_score: float
    executed_volume: float
    reliability_score: float
    metadata: MetricMetadata


@dataclass(frozen=True, slots=True)
class HeatmapObservation:
    timestamp: datetime
    values: tuple[tuple[float, float], ...]
    mode: str = "absolute_depth"


@dataclass(frozen=True, slots=True)
class HeatmapSnapshot:
    observations: tuple[HeatmapObservation, ...]


@dataclass(frozen=True, slots=True)
class DOMSnapshot:
    as_of: datetime
    symbol: str
    state: str
    metrics: dict[str, MetricResult[float]]
    walls: tuple[LiquidityWall, ...] = ()
    heatmap: HeatmapSnapshot = HeatmapSnapshot(())


@dataclass
class _LevelStats:
    first_seen: datetime
    last_seen: datetime
    appearances: int = 1
    additions: float = 0.0
    cancellations: float = 0.0
    executions: float = 0.0
    replenishments: int = 0
    cancels_before_touch: int = 0


class DOMHeatmap:
    def __init__(self, max_observations: int, retention: timedelta) -> None:
        self.max_observations = max_observations
        self.retention = retention
        self._observations: deque[HeatmapObservation] = deque(maxlen=max_observations)

    def append(self, observation: HeatmapObservation) -> None:
        self._observations.append(observation)
        self.trim(observation.timestamp)

    def trim(self, as_of: datetime) -> None:
        cutoff = as_of - self.retention
        while self._observations and self._observations[0].timestamp < cutoff:
            self._observations.popleft()

    def view(self, mode: str) -> tuple[HeatmapObservation, ...]:
        if mode not in {
            "absolute_depth",
            "signed_depth",
            "normalized_depth",
            "persistent_depth",
            "add_cancel_activity",
        }:
            raise ValueError(f"unsupported heatmap mode: {mode}")
        observations = tuple(self._observations)
        if mode == "signed_depth":
            return tuple(
                HeatmapObservation(item.timestamp, item.values, mode)
                for item in observations
            )

        price_counts: dict[float, int] = {}
        for item in observations:
            for price, _ in item.values:
                price_counts[price] = price_counts.get(price, 0) + 1

        previous: dict[float, float] = {}
        result: list[HeatmapObservation] = []
        observation_count = max(len(observations), 1)
        for item in observations:
            current = dict(item.values)
            if mode == "add_cancel_activity":
                prices = sorted(set(previous) | set(current))
                values = tuple(
                    (price, current.get(price, 0.0) - previous.get(price, 0.0))
                    for price in prices
                )
            else:
                raw_values = item.values
                if mode == "absolute_depth":
                    values = tuple((price, abs(value)) for price, value in raw_values)
                elif mode == "normalized_depth":
                    scale = max((abs(value) for _, value in raw_values), default=0.0)
                    values = tuple(
                        (price, value / scale if scale else 0.0)
                        for price, value in raw_values
                    )
                else:
                    values = tuple(
                        (
                            price,
                            value * price_counts[price] / observation_count,
                        )
                        for price, value in raw_values
                    )
            result.append(HeatmapObservation(item.timestamp, values, mode))
            previous = current
        return tuple(result)

    @property
    def observations(self) -> tuple[HeatmapObservation, ...]:
        return tuple(self._observations)


class OrderBookState:
    def __init__(
        self,
        instrument: InstrumentSpec,
        config: AnalyticsConfig,
        provider: str = "fixture",
        dataset: str = "depth",
    ) -> None:
        self.instrument = instrument
        self.config = config
        self.provider = provider
        self.dataset = dataset
        self._bids: dict[int, float] = {}
        self._asks: dict[int, float] = {}
        self._level_stats: dict[tuple[Side, int], _LevelStats] = {}
        self._activity: deque[tuple[datetime, float, float, float, float]] = deque()
        self._depth_totals: deque[float] = deque(
            maxlen=config.dom.heatmap_max_observations
        )
        self._expected_sequence: int | None = None
        self._last_depth_timestamp: datetime | None = None
        self._state = "needs_snapshot"
        self._heatmap = DOMHeatmap(
            config.dom.heatmap_max_observations,
            config.dom.heatmap_retention,
        )

    def apply(self, event: object, as_of: datetime | None = None) -> DOMSnapshot:
        event_time = as_of or getattr(event, "timestamp", None)
        if not isinstance(event_time, datetime):
            raise TypeError("order-book events must have a timestamp")
        _require_utc(event_time, "event timestamp")

        if isinstance(event, BookSnapshotEvent):
            self._apply_snapshot(event, event_time)
        elif isinstance(event, BookUpdateEvent):
            self._apply_update(event, event_time)
        elif isinstance(event, QuoteEvent):
            pass
        elif isinstance(event, TradeEvent):
            self._record_execution(event, event_time)
        elif isinstance(event, SessionTransitionEvent):
            self._reset_for_session(event)
        else:
            raise TypeError(f"unsupported DOM event: {type(event).__name__}")
        return self.snapshot(event_time)

    def apply_modify(
        self,
        as_of: datetime,
        *,
        sequence: int,
        side: Side,
        price: float,
        size: float,
    ) -> DOMSnapshot:
        return self.apply(
            BookUpdateEvent(
                self.instrument.symbol,
                as_of,
                self.provider,
                self.dataset,
                sequence,
                BookAction.MODIFY,
                side,
                price,
                size,
            )
        )

    def snapshot(self, as_of: datetime) -> DOMSnapshot:
        _require_utc(as_of, "as_of")
        self._trim_activity(as_of)
        if (
            self._state == "valid"
            and self._last_depth_timestamp is not None
            and as_of - self._last_depth_timestamp > self.config.dom.max_age
        ):
            self._state = "stale"
        return self._render(as_of)

    def _apply_snapshot(self, event: BookSnapshotEvent, as_of: datetime) -> None:
        self._bids.clear()
        self._asks.clear()
        for level in event.levels:
            self._set_level(level, as_of, replace_stats=False)
        self._expected_sequence = event.sequence + 1
        self._last_depth_timestamp = as_of
        self._state = "valid"
        self._record_heatmap(as_of)

    def _apply_update(self, event: BookUpdateEvent, as_of: datetime) -> None:
        if self._state != "valid" or self._expected_sequence is None:
            self._state = "needs_snapshot"
            return
        if event.sequence != self._expected_sequence:
            self._state = "needs_snapshot"
            self._expected_sequence = None
            return

        key = self.instrument.price_to_ticks(event.price)
        levels = self._bids if event.side is Side.BID else self._asks
        had_level = key in levels
        old_size = levels.get(key, 0.0)
        new_size = old_size
        added = 0.0
        canceled = 0.0
        replenished = 0.0
        if event.action is BookAction.ADD:
            new_size = old_size + event.size
            added = event.size
        elif event.action is BookAction.MODIFY:
            new_size = event.size
            if new_size >= old_size:
                added = new_size - old_size
                replenished = (
                    added
                    if old_size > 0 and self._level_executed(event.side, key) > 0
                    else 0.0
                )
            else:
                canceled = old_size - new_size
        elif event.action is BookAction.CANCEL:
            canceled = min(old_size, event.size)
            new_size = old_size - canceled

        if new_size > 0:
            levels[key] = new_size
        else:
            levels.pop(key, None)
        self._touch_level(
            event.side,
            key,
            as_of,
            added,
            canceled,
            replenished,
            had_level=had_level,
            cancel_before_touch=(event.action is BookAction.CANCEL and not had_level),
        )
        self._activity.append((as_of, added, canceled, 0.0, replenished))
        self._expected_sequence += 1
        self._last_depth_timestamp = as_of
        self._state = "valid"
        self._record_heatmap(as_of)

    def _set_level(
        self, level: BookLevel, as_of: datetime, *, replace_stats: bool
    ) -> None:
        key = self.instrument.price_to_ticks(level.price)
        levels = self._bids if level.side is Side.BID else self._asks
        levels[key] = levels.get(key, 0.0) + level.size
        if replace_stats or (level.side, key) not in self._level_stats:
            self._level_stats[(level.side, key)] = _LevelStats(as_of, as_of)
        else:
            stats = self._level_stats[(level.side, key)]
            stats.appearances += 1
            stats.last_seen = as_of

    def _touch_level(
        self,
        side: Side,
        key: int,
        as_of: datetime,
        added: float,
        canceled: float,
        replenished: float,
        *,
        had_level: bool,
        cancel_before_touch: bool = False,
    ) -> None:
        stats = self._level_stats.get((side, key))
        if stats is None:
            stats = _LevelStats(as_of, as_of)
            self._level_stats[(side, key)] = stats
        else:
            stats.appearances += 1
            stats.last_seen = as_of
        stats.additions += added
        stats.cancellations += canceled
        stats.replenishments += int(replenished > 0)
        if cancel_before_touch or (canceled > 0 and not had_level):
            stats.cancels_before_touch += 1

    def _record_execution(self, event: TradeEvent, as_of: datetime) -> None:
        key = self.instrument.price_to_ticks(event.price)
        side = self._execution_side(event)
        if side is None:
            return
        stats = self._level_stats.get((side, key))
        if stats is None:
            stats = _LevelStats(as_of, as_of)
            self._level_stats[(side, key)] = stats
        stats.executions += event.size
        self._activity.append((as_of, 0.0, 0.0, event.size, 0.0))

    def _execution_side(self, event: TradeEvent) -> Side | None:
        if event.aggressor_side is None:
            return None
        return Side.ASK if event.aggressor_side.value == "buy" else Side.BID

    def _level_executed(self, side: Side, key: int) -> float:
        stats = self._level_stats.get((side, key))
        return stats.executions if stats else 0.0

    def _reset_for_session(self, event: SessionTransitionEvent) -> None:
        if event.is_open:
            self._bids.clear()
            self._asks.clear()
            self._level_stats.clear()
            self._activity.clear()
            self._depth_totals.clear()
            self._heatmap = DOMHeatmap(
                self.config.dom.heatmap_max_observations,
                self.config.dom.heatmap_retention,
            )
            self._expected_sequence = None
            self._state = "needs_snapshot"
            self._last_depth_timestamp = None

    def _trim_activity(self, as_of: datetime) -> None:
        cutoff = as_of - self.config.dom.velocity_window
        while self._activity and self._activity[0][0] < cutoff:
            self._activity.popleft()

    def _record_heatmap(self, as_of: datetime) -> None:
        values = tuple(
            (self.instrument.ticks_to_price(key), size if side is Side.BID else -size)
            for side, side_map in ((Side.BID, self._bids), (Side.ASK, self._asks))
            for key, size in sorted(side_map.items())
        )
        self._depth_totals.append(sum(self._bids.values()) + sum(self._asks.values()))
        self._heatmap.append(HeatmapObservation(as_of, values, "signed_depth"))

    def _render(self, as_of: datetime) -> DOMSnapshot:
        state = self._book_state()
        if state not in {"valid", "stale"}:
            if state in {"locked", "crossed"}:
                metrics = self._render_metrics(as_of, state)
            else:
                metrics = {
                    name: self._unavailable(as_of, f"DOM state is {state}")
                    for name in self._metric_names()
                }
            return DOMSnapshot(
                as_of,
                self.instrument.symbol,
                state,
                metrics,
                (),
                HeatmapSnapshot(self._heatmap.observations),
            )
        return DOMSnapshot(
            as_of,
            self.instrument.symbol,
            state,
            self._render_metrics(as_of, state),
            self._render_walls(as_of),
            HeatmapSnapshot(self._heatmap.observations),
        )

    def _book_state(self) -> str:
        if self._state != "valid":
            return self._state
        if not self._bids or not self._asks:
            return "valid"
        best_bid = max(self._bids)
        best_ask = min(self._asks)
        if best_bid > best_ask:
            return "crossed"
        if best_bid == best_ask:
            return "locked"
        return "valid"

    def _render_walls(self, as_of: datetime) -> tuple[LiquidityWall, ...]:
        if not self._bids or not self._asks:
            return ()
        best_bid = max(self._bids)
        best_ask = min(self._asks)
        midpoint = (
            self.instrument.ticks_to_price(best_bid)
            + self.instrument.ticks_to_price(best_ask)
        ) / 2
        if midpoint <= 0:
            return ()

        median_total_depth = median(self._depth_totals) if self._depth_totals else 0.0
        level_count = len(self._bids) + len(self._asks)
        symbol_level_baseline = (
            median_total_depth / level_count
            if level_count and median_total_depth
            else 0.0
        )
        all_levels = {
            Side.BID: sorted(self._bids.items(), reverse=True),
            Side.ASK: sorted(self._asks.items()),
        }
        walls: list[LiquidityWall] = []
        for side, levels in all_levels.items():
            other_levels = all_levels[Side.ASK if side is Side.BID else Side.BID]
            for index, (key, size) in enumerate(levels):
                stats = self._level_stats.get((side, key))
                if stats is None:
                    continue
                nearby = [
                    nearby_size
                    for nearby_index, (_, nearby_size) in enumerate(levels)
                    if nearby_index != index
                    and abs(nearby_index - index) <= 2
                    and nearby_size > 0
                ]
                if not nearby:
                    nearby = [
                        nearby_size
                        for _, nearby_size in other_levels
                        if nearby_size > 0
                    ]
                neighbor_baseline = median(nearby) if nearby else size
                reference_values = [neighbor_baseline]
                if symbol_level_baseline > 0:
                    reference_values.append(symbol_level_baseline)
                normalized_size = size / max(median(reference_values), 1e-12)
                price = self.instrument.ticks_to_price(key)
                distance_bps = abs(price - midpoint) / midpoint * 10_000
                age_ms = max(
                    0, round((as_of - stats.first_seen).total_seconds() * 1000)
                )
                persistence_score = self._clip(
                    age_ms / self.config.dom.wall_min_persistence_ms
                    if self.config.dom.wall_min_persistence_ms
                    else 1.0
                )
                replenishment_score = self._clip(
                    stats.replenishments / self.config.dom.wall_target_replenishments
                )
                executed_score = self._clip(stats.executions / max(size, 1.0))
                appearance_score = self._clip(
                    (stats.appearances - 1) / self.config.dom.wall_target_appearances
                )
                activity_total = (
                    stats.additions + stats.cancellations + stats.cancels_before_touch
                )
                cancel_rate = (
                    (stats.cancellations + stats.cancels_before_touch) / activity_total
                    if activity_total
                    else 0.0
                )
                cancel_score = 1.0 - self._clip(cancel_rate)
                reliability_score = self._clip(
                    sum(
                        weight * score
                        for weight, score in zip(
                            self.config.dom.wall_reliability_weights,
                            (
                                persistence_score,
                                replenishment_score,
                                executed_score,
                                appearance_score,
                                cancel_score,
                            ),
                            strict=True,
                        )
                    )
                )
                if (
                    size < self.config.dom.wall_min_symbol_size
                    or normalized_size < self.config.dom.wall_min_normalized_size
                    or distance_bps > self.config.dom.wall_max_distance_bps
                    or persistence_score < 1.0
                    or reliability_score < self.config.dom.wall_min_reliability
                ):
                    continue
                walls.append(
                    LiquidityWall(
                        price=price,
                        side=side,
                        size=size,
                        normalized_size=normalized_size,
                        distance_bps=distance_bps,
                        age_ms=age_ms,
                        persistence_score=persistence_score,
                        replenishment_score=replenishment_score,
                        cancel_score=cancel_score,
                        executed_volume=stats.executions,
                        reliability_score=reliability_score,
                        metadata=MetricMetadata(
                            as_of=as_of,
                            provider=self.provider,
                            dataset=self.dataset,
                            venue_scope=self.instrument.venue,
                            freshness_ms=age_ms,
                            methodology=(
                                "displayed-liquidity reliability from persistence, "
                                "replenishment, executions, appearances, and cancels"
                            ),
                            quality_score=reliability_score * 100,
                            observed_or_modeled=Provenance.DERIVED_FROM_OBSERVED,
                        ),
                    )
                )
        walls.sort(
            key=lambda wall: (-wall.reliability_score, wall.side.value, wall.price)
        )
        return tuple(walls)

    @staticmethod
    def _clip(value: float) -> float:
        return max(0.0, min(1.0, value))

    def _render_metrics(
        self, as_of: datetime, state: str
    ) -> dict[str, MetricResult[float]]:
        metrics: dict[str, MetricResult[float]] = {}
        bid_levels = sorted(self._bids.items(), reverse=True)
        ask_levels = sorted(self._asks.items())
        for n in self.config.dom.imbalance_levels:
            bid_depth = sum(size for _, size in bid_levels[:n])
            ask_depth = sum(size for _, size in ask_levels[:n])
            denominator = bid_depth + ask_depth
            if denominator == 0:
                metrics[f"book_imbalance_l{n}"] = self._metric(
                    0.0,
                    as_of,
                    status=MetricStatus.DEGRADED,
                    methodology=f"{n}-level OBI; zero total displayed depth returns zero",
                    quality=50.0,
                    reason="zero total displayed depth",
                )
            else:
                value = max(-1.0, min(1.0, (bid_depth - ask_depth) / denominator))
                metrics[f"book_imbalance_l{n}"] = self._metric(
                    value,
                    as_of,
                    methodology=f"{n}-level displayed-depth imbalance",
                )

        best_bid = bid_levels[0] if bid_levels else None
        best_ask = ask_levels[0] if ask_levels else None
        if best_bid is None or best_ask is None:
            for name in (
                "midprice",
                "microprice",
                "microprice_minus_mid_bps",
                "spread",
                "spread_bps",
            ):
                metrics[name] = self._unavailable(as_of, "missing best bid or ask")
        elif state in {"crossed", "locked"}:
            for name in (
                "midprice",
                "microprice",
                "microprice_minus_mid_bps",
                "spread",
                "spread_bps",
            ):
                metrics[name] = self._unavailable(as_of, f"book is {state}")
        else:
            bid_price = self.instrument.ticks_to_price(best_bid[0])
            ask_price = self.instrument.ticks_to_price(best_ask[0])
            mid = (bid_price + ask_price) / 2
            size_sum = best_bid[1] + best_ask[1]
            micro = (
                (ask_price * best_bid[1] + bid_price * best_ask[1]) / size_sum
                if size_sum > 0
                else None
            )
            metrics["midprice"] = self._metric(
                mid, as_of, methodology="best bid/ask midpoint"
            )
            metrics["spread"] = self._metric(
                ask_price - bid_price, as_of, methodology="best ask minus best bid"
            )
            metrics["spread_bps"] = self._metric(
                (ask_price - bid_price) / mid * 10_000,
                as_of,
                methodology="spread divided by midpoint in bps",
            )
            if micro is None:
                metrics["microprice"] = self._unavailable(
                    as_of, "zero top-of-book queue size"
                )
                metrics["microprice_minus_mid_bps"] = self._unavailable(
                    as_of, "microprice unavailable"
                )
            else:
                metrics["microprice"] = self._metric(
                    micro, as_of, methodology="queue-size weighted microprice"
                )
                metrics["microprice_minus_mid_bps"] = self._metric(
                    (micro - mid) / mid * 10_000,
                    as_of,
                    methodology="microprice minus midpoint in bps",
                )

        for side_name, levels in (("bid", bid_levels), ("ask", ask_levels)):
            metrics[f"depth_slope_{side_name}"] = self._slope_metric(
                levels, as_of, side_name
            )
            total = sum(size for _, size in levels)
            metrics[f"depth_concentration_{side_name}"] = (
                self._metric(
                    levels[0][1] / total,
                    as_of,
                    methodology=f"top-level {side_name} depth concentration",
                )
                if levels and total > 0
                else self._unavailable(as_of, f"no {side_name} depth")
            )
        bid_total = sum(size for _, size in bid_levels[:10])
        ask_total = sum(size for _, size in ask_levels[:10])
        metrics["bid_ask_depth_ratio"] = (
            self._metric(
                bid_total / ask_total,
                as_of,
                methodology="top-ten bid depth divided by ask depth",
            )
            if ask_total > 0
            else self._unavailable(as_of, "zero ask depth")
        )
        metrics["distance_weighted_imbalance"] = self._distance_weighted_metric(
            bid_levels, ask_levels, as_of
        )
        metrics.update(self._activity_metrics(as_of))
        if state == "stale":
            metrics = {
                name: self._mark_stale(metric) for name, metric in metrics.items()
            }
        return metrics

    @staticmethod
    def _mark_stale(metric: MetricResult[float]) -> MetricResult[float]:
        if metric.value is None:
            return metric
        return replace(
            metric,
            metadata=replace(
                metric.metadata,
                status=MetricStatus.STALE,
                reason="last depth update exceeded configured freshness limit",
            ),
        )

    def _slope_metric(
        self, levels: list[tuple[int, float]], as_of: datetime, side: str
    ) -> MetricResult[float]:
        if len(levels) < 2:
            return self._unavailable(as_of, f"fewer than two {side} levels")
        x = list(range(len(levels)))
        y = [size for _, size in levels]
        slope = linear_regression(x, y).slope
        return self._metric(
            slope, as_of, methodology=f"linear size slope by {side} level rank"
        )

    def _distance_weighted_metric(
        self,
        bid_levels: list[tuple[int, float]],
        ask_levels: list[tuple[int, float]],
        as_of: datetime,
    ) -> MetricResult[float]:
        bid_weighted = sum(
            size / (1 + index) for index, (_, size) in enumerate(bid_levels[:10])
        )
        ask_weighted = sum(
            size / (1 + index) for index, (_, size) in enumerate(ask_levels[:10])
        )
        denominator = bid_weighted + ask_weighted
        if denominator == 0:
            return self._unavailable(as_of, "no displayed depth for weighted imbalance")
        return self._metric(
            (bid_weighted - ask_weighted) / denominator,
            as_of,
            methodology="inverse-level-distance weighted displayed-depth imbalance",
        )

    def _activity_metrics(self, as_of: datetime) -> dict[str, MetricResult[float]]:
        seconds = max(self.config.dom.velocity_window.total_seconds(), 1.0)
        adds = sum(item[1] for item in self._activity)
        cancels = sum(item[2] for item in self._activity)
        depletion = sum(item[3] for item in self._activity)
        replenishment = sum(item[4] for item in self._activity)
        return {
            "order_add_velocity": self._metric(
                adds / seconds, as_of, methodology="displayed additions per second"
            ),
            "cancel_velocity": self._metric(
                cancels / seconds,
                as_of,
                methodology="displayed cancellations per second",
            ),
            "queue_depletion": self._metric(
                depletion / seconds,
                as_of,
                methodology="executed volume per second at displayed levels",
            ),
            "queue_replenishment": self._metric(
                replenishment / seconds,
                as_of,
                methodology="replenished displayed volume per second",
            ),
        }

    def _metric_names(self) -> tuple[str, ...]:
        return (
            *(f"book_imbalance_l{n}" for n in self.config.dom.imbalance_levels),
            "midprice",
            "microprice",
            "microprice_minus_mid_bps",
            "spread",
            "spread_bps",
            "depth_slope_bid",
            "depth_slope_ask",
            "bid_ask_depth_ratio",
            "depth_concentration_bid",
            "depth_concentration_ask",
            "distance_weighted_imbalance",
            "order_add_velocity",
            "cancel_velocity",
            "queue_depletion",
            "queue_replenishment",
        )

    def _metric(
        self,
        value: float,
        as_of: datetime,
        *,
        status: MetricStatus = MetricStatus.OK,
        methodology: str,
        quality: float = 100.0,
        reason: str | None = None,
    ) -> MetricResult[float]:
        if not isfinite(value):
            return self._unavailable(as_of, "non-finite computed metric")
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
