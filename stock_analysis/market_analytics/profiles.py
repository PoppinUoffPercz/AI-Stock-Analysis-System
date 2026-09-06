"""Time-price opportunity and volume profile analytics."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from math import ceil, isfinite

from .config import AnalyticsConfig
from .models import (
    BarEvent,
    InstrumentSpec,
    MetricMetadata,
    MetricResult,
    MetricStatus,
    Provenance,
    TradeEvent,
    VolumeInputMode,
    _require_utc,
)
from .vwap import SessionClock


@dataclass(frozen=True, slots=True)
class SinglePrintZone:
    low: float
    high: float
    creation_time: datetime
    direction: str
    confirmed: bool
    filled: bool
    first_retest_time: datetime | None
    age_sessions: int
    retest_count: int = 0
    last_retest_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class TPOProfileSnapshot:
    as_of: datetime
    session_id: str | None
    metrics: dict[str, MetricResult[float]]
    single_prints: tuple[SinglePrintZone, ...] = ()


class TPOEngine:
    def __init__(self, instrument: InstrumentSpec, config: AnalyticsConfig) -> None:
        self.instrument = instrument
        self.config = config
        self.provider = "analytics"
        self.dataset = "tpo"
        self.clock = SessionClock(config.session)
        self._session_id: str | None = None
        self._row_brackets: dict[int, set[datetime]] = {}
        self._bracket_ranges: dict[datetime, tuple[float, float]] = {}
        self._finalized = False
        self._confirmed_single_prints: dict[tuple[str, int], SinglePrintZone] = {}

    def consume_bar(self, bar: BarEvent) -> TPOProfileSnapshot:
        _require_utc(bar.timestamp, "bar timestamp")
        session_id = self.clock.session_id(bar.timestamp)
        if session_id is None:
            return self.snapshot(bar.timestamp)
        if self._session_id != session_id:
            self._reset(session_id)
        self._update_single_prints(bar)
        self.provider = bar.provider
        self.dataset = bar.dataset
        bracket = self._bracket_start(bar.timestamp)
        low_row = self._price_to_row(bar.low)
        high_row = self._price_to_row(bar.high)
        for row in range(min(low_row, high_row), max(low_row, high_row) + 1):
            self._row_brackets.setdefault(row, set()).add(bracket)
        previous_range = self._bracket_ranges.get(bracket)
        if previous_range is None:
            self._bracket_ranges[bracket] = (bar.low, bar.high)
        else:
            self._bracket_ranges[bracket] = (
                min(previous_range[0], bar.low),
                max(previous_range[1], bar.high),
            )
        self._finalized = False
        return self.snapshot(bar.timestamp)

    def snapshot(self, as_of: datetime) -> TPOProfileSnapshot:
        _require_utc(as_of, "as_of")
        rows = {
            row: {bracket for bracket in brackets if bracket <= as_of}
            for row, brackets in self._row_brackets.items()
        }
        rows = {row: brackets for row, brackets in rows.items() if brackets}
        return self._render(as_of, rows, self._finalized)

    def finalize_session(self, session_id: str, as_of: datetime) -> TPOProfileSnapshot:
        _require_utc(as_of, "as_of")
        self._session_id = session_id
        self._finalized = True
        return self._render(as_of, self._row_brackets, True)

    def _render(
        self,
        as_of: datetime,
        rows: dict[int, set[datetime]],
        finalized: bool,
    ) -> TPOProfileSnapshot:
        if not rows:
            return TPOProfileSnapshot(
                as_of,
                self._session_id,
                self._unavailable_metrics(as_of, "no TPO rows"),
                self._historical_single_prints(as_of),
            )
        counts = {row: len(brackets) for row, brackets in rows.items()}
        low_row = min(counts)
        high_row = max(counts)
        low_price = self._row_to_price(low_row)
        high_price = self._row_to_price(high_row)
        midpoint = (low_price + high_price) / 2
        poc_row = min(
            (row for row, count in counts.items() if count == max(counts.values())),
            key=lambda row: (abs(self._row_to_price(row) - midpoint), row),
        )
        total_count = sum(counts.values())
        target_count = ceil(total_count * self.config.profile.value_area_percentage)
        value_area_rows = self._value_area_rows(counts, poc_row, target_count, midpoint)
        ib_high, ib_low = self._initial_balance(rows)
        metrics = {
            "tpo_poc": self._metric(
                self._row_to_price(poc_row),
                as_of,
                "TPO POC: highest row count, midpoint distance, then lower row",
            ),
            "tpo_vah": self._metric(
                self._row_to_price(max(value_area_rows)),
                as_of,
                "TPO value-area high from adjacent count expansion",
            ),
            "tpo_val": self._metric(
                self._row_to_price(min(value_area_rows)),
                as_of,
                "TPO value-area low from adjacent count expansion",
            ),
            "tpo_midpoint": self._metric(
                midpoint, as_of, "midpoint between lowest and highest TPO rows"
            ),
            "tpo_count_above_poc": self._metric(
                sum(count for row, count in counts.items() if row > poc_row),
                as_of,
                "TPO count above POC",
            ),
            "tpo_count_below_poc": self._metric(
                sum(count for row, count in counts.items() if row < poc_row),
                as_of,
                "TPO count below POC",
            ),
            "tpo_total_count": self._metric(
                total_count, as_of, "sum of one TPO per bracket and normalized row"
            ),
        }
        if ib_high is None or ib_low is None:
            metrics["initial_balance_high"] = self._unavailable(
                as_of, "initial balance brackets are not available"
            )
            metrics["initial_balance_low"] = self._unavailable(
                as_of, "initial balance brackets are not available"
            )
        else:
            metrics["initial_balance_high"] = self._metric(
                ib_high, as_of, "high of the first configured TPO brackets"
            )
            metrics["initial_balance_low"] = self._metric(
                ib_low, as_of, "low of the first configured TPO brackets"
            )
        return TPOProfileSnapshot(
            as_of,
            self._session_id,
            metrics,
            self._single_prints(rows, counts, midpoint, as_of, finalized),
        )

    def _value_area_rows(
        self,
        counts: dict[int, int],
        poc_row: int,
        target_count: int,
        midpoint: float,
    ) -> set[int]:
        included = {poc_row}
        included_count = counts[poc_row]
        while included_count < target_count:
            lower = min(included)
            upper = max(included)
            candidates = [
                row
                for row in (lower - 1, upper + 1)
                if row in counts and row not in included
            ]
            if not candidates:
                break
            selected = min(
                candidates,
                key=lambda row: (
                    -counts[row],
                    abs(self._row_to_price(row) - midpoint),
                    row,
                ),
            )
            included.add(selected)
            included_count += counts[selected]
        return included

    def _initial_balance(
        self, rows: dict[int, set[datetime]]
    ) -> tuple[float | None, float | None]:
        brackets = sorted(bracket for values in rows.values() for bracket in values)
        first_brackets = list(dict.fromkeys(brackets))[
            : self.config.profile.initial_balance_brackets
        ]
        ranges = [self._bracket_ranges[bracket] for bracket in first_brackets]
        if not ranges:
            return None, None
        return max(high for _, high in ranges), min(low for low, _ in ranges)

    def _single_prints(
        self,
        rows: dict[int, set[datetime]],
        counts: dict[int, int],
        midpoint: float,
        as_of: datetime,
        finalized: bool,
    ) -> tuple[SinglePrintZone, ...]:
        result: list[SinglePrintZone] = []
        seen: set[tuple[str, int]] = set()
        for row, count in sorted(counts.items()):
            if count != 1 or row - 1 not in counts or row + 1 not in counts:
                continue
            confirmed = finalized and min(counts[row - 1], counts[row + 1]) >= (
                self.config.profile.single_print_neighbor_min_tpo
            )
            key = (self._session_id or "", row)
            seen.add(key)
            if confirmed and key not in self._confirmed_single_prints:
                self._remember_single_print(key, row, min(rows[row]), midpoint)
            result.append(
                self._confirmed_single_prints.get(key)
                or self._new_single_print(row, min(rows[row]), midpoint)
            )
        result.extend(
            zone
            for key, zone in self._confirmed_single_prints.items()
            if key not in seen and zone.creation_time <= as_of
        )
        result.sort(key=lambda zone: (zone.low, zone.creation_time))
        return tuple(result)

    def _historical_single_prints(self, as_of: datetime) -> tuple[SinglePrintZone, ...]:
        return tuple(
            zone
            for zone in sorted(
                self._confirmed_single_prints.values(),
                key=lambda item: (item.low, item.creation_time),
            )
            if zone.creation_time <= as_of
        )

    def _new_single_print(
        self, row: int, creation_time: datetime, midpoint: float
    ) -> SinglePrintZone:
        price = self._row_to_price(row)
        half_row = (self.config.profile.row_size or self.instrument.tick_size) / 2
        return SinglePrintZone(
            low=price - half_row,
            high=price + half_row,
            creation_time=creation_time,
            direction="above" if price >= midpoint else "below",
            confirmed=False,
            filled=False,
            first_retest_time=None,
            age_sessions=0,
        )

    def _remember_single_print(
        self,
        key: tuple[str, int],
        row: int,
        creation_time: datetime,
        midpoint: float,
    ) -> None:
        zone = self._new_single_print(row, creation_time, midpoint)
        self._confirmed_single_prints[key] = replace(zone, confirmed=True)

    def _update_single_prints(self, bar: BarEvent) -> None:
        for key, zone in tuple(self._confirmed_single_prints.items()):
            if bar.timestamp <= zone.creation_time:
                continue
            if bar.high < zone.low or bar.low > zone.high:
                continue
            first_retest = zone.first_retest_time or bar.timestamp
            self._confirmed_single_prints[key] = replace(
                zone,
                first_retest_time=first_retest,
                last_retest_time=bar.timestamp,
                retest_count=zone.retest_count + 1,
                filled=zone.filled or (bar.low <= zone.low and bar.high >= zone.high),
            )

    def _reset(self, session_id: str) -> None:
        for key, zone in tuple(self._confirmed_single_prints.items()):
            if zone.filled or zone.age_sessions >= (
                self.config.profile.single_print_retention_sessions
            ):
                self._confirmed_single_prints.pop(key)
            else:
                self._confirmed_single_prints[key] = replace(
                    zone, age_sessions=zone.age_sessions + 1
                )
        self._session_id = session_id
        self._row_brackets.clear()
        self._bracket_ranges.clear()
        self._finalized = False

    def start_session(self, session_id: str) -> None:
        if session_id != self._session_id:
            self._reset(session_id)

    def _bracket_start(self, timestamp: datetime) -> datetime:
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        seconds = self.config.profile.tpo_bracket.total_seconds()
        offset = int((timestamp - epoch).total_seconds() // seconds * seconds)
        return epoch + timedelta(seconds=offset)

    def _price_to_row(self, price: float) -> int:
        row_size = self.config.profile.row_size or self.instrument.tick_size
        return round(price / row_size)

    def _row_to_price(self, row: int) -> float:
        row_size = self.config.profile.row_size or self.instrument.tick_size
        return round(row * row_size, self.instrument.price_precision)

    def _unavailable_metrics(
        self, as_of: datetime, reason: str
    ) -> dict[str, MetricResult[float]]:
        names = (
            "tpo_poc",
            "tpo_vah",
            "tpo_val",
            "tpo_midpoint",
            "tpo_count_above_poc",
            "tpo_count_below_poc",
            "tpo_total_count",
            "initial_balance_high",
            "initial_balance_low",
        )
        return {name: self._unavailable(as_of, reason) for name in names}

    def _metric(
        self, value: float, as_of: datetime, methodology: str
    ) -> MetricResult[float]:
        if not isfinite(value):
            return self._unavailable(as_of, "non-finite TPO metric")
        return MetricResult(
            value,
            MetricMetadata(
                as_of=as_of,
                provider=self.provider,
                dataset=self.dataset,
                venue_scope=self.instrument.venue,
                status=MetricStatus.OK,
                methodology=methodology,
                observed_or_modeled=Provenance.DERIVED_FROM_OBSERVED,
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


@dataclass(frozen=True, slots=True)
class VolumeProfileSnapshot:
    window_sessions: int
    vpoc: float | None
    vah: float | None
    val: float | None
    profile_high: float | None
    profile_low: float | None
    total_volume: float
    hvns: tuple[float, ...]
    lvns: tuple[float, ...]
    exact_or_approximate: str
    metadata: MetricMetadata


@dataclass(frozen=True, slots=True)
class ProfileLevelCluster:
    center_price: float
    member_levels: tuple[float, ...]
    member_windows: tuple[int, ...]
    cluster_strength: float
    distance_from_spot_bps: float | None
    support_or_resistance_context: str


class VolumeProfileEngine:
    def __init__(self, instrument: InstrumentSpec, config: AnalyticsConfig) -> None:
        self.instrument = instrument
        self.config = config
        self.provider = "analytics"
        self.dataset = "volume_profile"
        self.input_mode = config.volume_input_mode
        self.clock = SessionClock(config.session)
        self._session_id: str | None = None
        self._histogram: dict[int, float] = {}
        self._has_bar = False

    def consume_trade(self, trade: TradeEvent) -> VolumeProfileSnapshot:
        _require_utc(trade.timestamp, "trade timestamp")
        if self.clock.session_id(trade.timestamp) is None:
            return self.snapshot(trade.timestamp)
        self._start_session(trade.timestamp)
        self.provider = trade.provider
        self.dataset = trade.dataset
        tick = self.instrument.price_to_ticks(trade.price)
        if self.input_mode is VolumeInputMode.TRADES:
            self._histogram[tick] = self._histogram.get(tick, 0.0) + trade.size
        return self.snapshot(trade.timestamp)

    def consume_bar(self, bar: BarEvent) -> VolumeProfileSnapshot:
        _require_utc(bar.timestamp, "bar timestamp")
        if self.clock.session_id(bar.timestamp) is None:
            return self.snapshot(bar.timestamp)
        self._start_session(bar.timestamp)
        self.provider = bar.provider
        self.dataset = bar.dataset
        if self.input_mode is VolumeInputMode.BARS and bar.volume > 0:
            representative = (bar.high + bar.low + bar.close) / 3
            tick = self.instrument.price_to_ticks(representative)
            self._histogram[tick] = self._histogram.get(tick, 0.0) + bar.volume
        self._has_bar = self.input_mode is VolumeInputMode.BARS
        return self.snapshot(bar.timestamp)

    def snapshot(self, as_of: datetime) -> VolumeProfileSnapshot:
        _require_utc(as_of, "as_of")
        return _make_volume_snapshot(
            self.instrument,
            self.config,
            self._histogram,
            1 if self._histogram else 0,
            not self._has_bar,
            as_of,
            self.provider,
            self.dataset,
        )

    @property
    def histogram(self) -> dict[int, float]:
        return dict(self._histogram)

    def _start_session(self, timestamp: datetime) -> None:
        session_id = self.clock.session_id(timestamp)
        if session_id is None:
            return
        if session_id == self._session_id:
            return
        self._session_id = session_id
        self._histogram.clear()
        self._has_bar = False

    def start_session(self, session_id: str) -> None:
        if session_id != self._session_id:
            self._session_id = session_id
            self._histogram.clear()
            self._has_bar = False


@dataclass(frozen=True, slots=True)
class _CompletedVolumeSession:
    session_id: str
    histogram: dict[int, float]
    exact: bool


class RollingVolumeProfileEngine:
    def __init__(self, instrument: InstrumentSpec, config: AnalyticsConfig) -> None:
        self.instrument = instrument
        self.config = config
        self.provider = "analytics"
        self.dataset = "rolling_volume_profile"
        self._buffers: dict[int, deque[_CompletedVolumeSession]] = {
            window: deque(maxlen=window) for window in config.profile.rolling_windows
        }
        self._histograms: dict[int, dict[int, float]] = {
            window: {} for window in config.profile.rolling_windows
        }

    def finalize_session(
        self,
        session_id: str,
        histogram: Mapping[int, float],
        exact: bool,
        *,
        as_of: datetime | None = None,
    ) -> Mapping[int, VolumeProfileSnapshot]:
        if as_of is None:
            raise ValueError("as_of is required to finalize a rolling session")
        _require_utc(as_of, "as_of")
        completed = _CompletedVolumeSession(
            session_id, _validate_histogram(histogram), exact
        )
        for window, buffer in self._buffers.items():
            if len(buffer) == buffer.maxlen:
                evicted = buffer[0]
                _subtract_histogram(self._histograms[window], evicted.histogram)
            buffer.append(completed)
            _add_histogram(self._histograms[window], completed.histogram)
        return self.snapshot(as_of)

    def snapshot(self, as_of: datetime) -> Mapping[int, VolumeProfileSnapshot]:
        _require_utc(as_of, "as_of")
        snapshots: dict[int, VolumeProfileSnapshot] = {}
        for window in self.config.profile.rolling_windows:
            sessions = list(self._buffers[window])
            histogram = self._histograms[window]
            exact = all(session.exact for session in sessions)
            snapshots[window] = _make_volume_snapshot(
                self.instrument,
                self.config,
                histogram,
                len(sessions),
                exact,
                as_of,
                self.provider,
                self.dataset,
            )
        return snapshots

    def clusters(
        self,
        as_of: datetime,
        spot: float | None = None,
    ) -> tuple[ProfileLevelCluster, ...]:
        snapshots = self.snapshot(as_of)
        members: list[tuple[float, int, str]] = []
        for window, profile in snapshots.items():
            members.extend((price, window, "hvn") for price in profile.hvns)
            members.extend((price, window, "lvn") for price in profile.lvns)
        if not members:
            return ()
        members.sort()
        groups: list[list[tuple[float, int, str]]] = []
        for member in members:
            if not groups or not self._within_cluster(
                member[0], groups[-1][-1][0], spot
            ):
                groups.append([member])
            else:
                groups[-1].append(member)
        result = []
        total_windows = len(self.config.profile.rolling_windows)
        for group in groups:
            prices = tuple(sorted({member[0] for member in group}))
            windows = tuple(sorted({member[1] for member in group}))
            center = sum(prices) / len(prices)
            distance = (
                abs(center - spot) / spot * 10_000
                if spot is not None and spot > 0
                else None
            )
            context = (
                "unknown"
                if spot is None
                else "support"
                if center <= spot
                else "resistance"
            )
            result.append(
                ProfileLevelCluster(
                    center,
                    prices,
                    windows,
                    len(windows) / total_windows,
                    distance,
                    context,
                )
            )
        return tuple(result)

    def _within_cluster(self, left: float, right: float, spot: float | None) -> bool:
        tick_tolerance = (
            self.instrument.tick_size * self.config.profile.cluster_tolerance_ticks
        )
        bps_reference = spot if spot is not None and spot > 0 else max(left, right)
        bps_tolerance = (
            bps_reference * self.config.profile.cluster_tolerance_bps / 10_000
        )
        atr_tolerance = (
            self.instrument.atr * self.config.profile.cluster_tolerance_bps / 10_000
            if self.instrument.atr is not None
            else 0.0
        )
        return abs(left - right) <= max(tick_tolerance, bps_tolerance, atr_tolerance)


def _validate_histogram(histogram: Mapping[int, float]) -> dict[int, float]:
    validated: dict[int, float] = {}
    for tick, volume in histogram.items():
        if not isinstance(tick, int):
            raise TypeError("volume-profile histogram keys must be integer ticks")
        if not isfinite(volume) or volume < 0:
            raise ValueError(
                "volume-profile histogram volume must be finite and nonnegative"
            )
        if volume > 0:
            validated[tick] = float(volume)
    return validated


def _add_histogram(target: dict[int, float], source: Mapping[int, float]) -> None:
    for tick, volume in source.items():
        target[tick] = target.get(tick, 0.0) + volume


def _subtract_histogram(target: dict[int, float], source: Mapping[int, float]) -> None:
    for tick, volume in source.items():
        remaining = target.get(tick, 0.0) - volume
        if remaining <= 0:
            target.pop(tick, None)
        else:
            target[tick] = remaining


def _make_volume_snapshot(
    instrument: InstrumentSpec,
    config: AnalyticsConfig,
    histogram: Mapping[int, float],
    window_sessions: int,
    exact: bool,
    as_of: datetime,
    provider: str,
    dataset: str,
) -> VolumeProfileSnapshot:
    bins = {tick: volume for tick, volume in histogram.items() if volume > 0}
    mode = "exact" if exact else "approximate"
    if not bins:
        return VolumeProfileSnapshot(
            window_sessions,
            None,
            None,
            None,
            None,
            None,
            0.0,
            (),
            (),
            mode,
            MetricMetadata.unavailable(
                as_of=as_of,
                provider=provider,
                dataset=dataset,
                venue_scope=instrument.venue,
                reason="no positive volume in profile",
                methodology="volume-at-price profile",
            ),
        )
    ordered = sorted(bins)
    low = instrument.ticks_to_price(ordered[0])
    high = instrument.ticks_to_price(ordered[-1])
    midpoint = (low + high) / 2
    vpoc_tick = min(
        (tick for tick, volume in bins.items() if volume == max(bins.values())),
        key=lambda tick: (abs(instrument.ticks_to_price(tick) - midpoint), tick),
    )
    total = sum(bins.values())
    target = ceil(total * config.profile.value_area_percentage)
    value_area = {vpoc_tick}
    included = bins[vpoc_tick]
    observed_index = {tick: index for index, tick in enumerate(ordered)}
    lower_index = upper_index = observed_index[vpoc_tick]
    while included < target:
        candidates = []
        if lower_index > 0:
            candidates.append(ordered[lower_index - 1])
        if upper_index + 1 < len(ordered):
            candidates.append(ordered[upper_index + 1])
        if not candidates:
            break
        selected = min(
            candidates,
            key=lambda tick: (
                -bins[tick],
                abs(instrument.ticks_to_price(tick) - midpoint),
                tick,
            ),
        )
        value_area.add(selected)
        included += bins[selected]
        selected_index = observed_index[selected]
        lower_index = min(lower_index, selected_index)
        upper_index = max(upper_index, selected_index)
    hvns: list[float] = []
    lvns: list[float] = []
    for index, tick in enumerate(ordered):
        neighbors = [
            bins[neighbor]
            for neighbor in (
                ordered[index - 1] if index else None,
                ordered[index + 1] if index + 1 < len(ordered) else None,
            )
            if neighbor is not None
        ]
        if not neighbors:
            continue
        neighbor_average = sum(neighbors) / len(neighbors)
        if bins[tick] >= neighbor_average * config.profile.hvn_neighbor_multiplier:
            hvns.append(instrument.ticks_to_price(tick))
        if bins[tick] <= neighbor_average * config.profile.lvn_neighbor_multiplier:
            lvns.append(instrument.ticks_to_price(tick))
    provenance = Provenance.DERIVED_FROM_OBSERVED if exact else Provenance.APPROXIMATE
    return VolumeProfileSnapshot(
        window_sessions,
        instrument.ticks_to_price(vpoc_tick),
        instrument.ticks_to_price(max(value_area)),
        instrument.ticks_to_price(min(value_area)),
        high,
        low,
        total,
        tuple(hvns),
        tuple(lvns),
        mode,
        MetricMetadata(
            as_of=as_of,
            provider=provider,
            dataset=dataset,
            venue_scope=instrument.venue,
            status=MetricStatus.OK,
            methodology=(
                "exact trade volume by normalized tick with adjacent volume value area"
                if exact
                else "all bar volume assigned to (high + low + close) / 3 normalized tick"
            ),
            quality_score=100.0 if exact else 70.0,
            observed_or_modeled=provenance,
        ),
    )
