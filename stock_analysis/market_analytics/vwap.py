"""Session-aware exact and explicitly approximate VWAP analytics."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from math import isfinite, sqrt
from statistics import linear_regression
from zoneinfo import ZoneInfo

from .config import AnalyticsConfig, SessionConfig
from .models import (
    BarEvent,
    MetricMetadata,
    MetricResult,
    MetricStatus,
    Provenance,
    TradeEvent,
    VolumeInputMode,
    _require_utc,
)


class SessionClock:
    def __init__(self, config: SessionConfig | AnalyticsConfig | None = None) -> None:
        if config is None:
            config = SessionConfig()
        if isinstance(config, AnalyticsConfig):
            config = config.session
        self.config = config
        self._timezone = ZoneInfo(config.timezone)

    def session_id(self, timestamp: datetime) -> str | None:
        _require_utc(timestamp, "timestamp")
        local = timestamp.astimezone(self._timezone)
        if self.config.include_extended_hours:
            return local.date().isoformat()
        if self.config.rth_start <= local.time() < self.config.rth_end:
            return local.date().isoformat()
        return None


@dataclass(frozen=True, slots=True)
class VWAPSnapshot:
    as_of: datetime
    session_id: str | None
    metrics: dict[str, MetricResult[float]]


class VWAPEngine:
    def __init__(self, config: AnalyticsConfig) -> None:
        self.config = config
        self.input_mode = config.volume_input_mode
        self.clock = SessionClock(config.session)
        self._session_id: str | None = None
        self._price_volume = 0.0
        self._price_squared_volume = 0.0
        self._volume = 0.0
        self._last_price: float | None = None
        self._vwap_samples: deque[float] = deque(maxlen=config.vwap.slope_window)
        self._has_approximate = False
        self.provider = "analytics"
        self.dataset = "vwap"
        self.venue_scope = ""

    def consume_trade(self, trade: TradeEvent) -> VWAPSnapshot:
        _require_utc(trade.timestamp, "trade timestamp")
        session_id = self.clock.session_id(trade.timestamp)
        self.provider = trade.provider
        self.dataset = trade.dataset
        if session_id is None:
            return self.snapshot(trade.timestamp)
        self._start_session(session_id)
        if self.input_mode is VolumeInputMode.TRADES:
            self._add_observation(trade.price, trade.size, approximate=False)
        self._last_price = trade.price
        return self.snapshot(trade.timestamp)

    def consume_bar(self, bar: BarEvent) -> VWAPSnapshot:
        _require_utc(bar.timestamp, "bar timestamp")
        session_id = self.clock.session_id(bar.timestamp)
        self.provider = bar.provider
        self.dataset = bar.dataset
        if session_id is None:
            return self.snapshot(bar.timestamp)
        self._start_session(session_id)
        representative_price = (bar.high + bar.low + bar.close) / 3
        if self.input_mode is VolumeInputMode.BARS and bar.volume > 0:
            self._add_observation(representative_price, bar.volume, approximate=True)
        self._last_price = representative_price
        return self.snapshot(bar.timestamp)

    def snapshot(self, as_of: datetime) -> VWAPSnapshot:
        _require_utc(as_of, "as_of")
        session_id = self.clock.session_id(as_of)
        if session_id != self._session_id or self._volume <= 0:
            return VWAPSnapshot(
                as_of,
                session_id,
                self._unavailable_metrics(as_of, "no active session volume"),
            )

        vwap = self._price_volume / self._volume
        variance = max(self._price_squared_volume / self._volume - vwap**2, 0.0)
        standard_deviation = sqrt(variance)
        provenance = (
            Provenance.APPROXIMATE
            if self._has_approximate
            else Provenance.DERIVED_FROM_OBSERVED
        )
        quality = 70.0 if provenance is Provenance.APPROXIMATE else 100.0
        metrics = {
            "session_vwap": self._metric(
                vwap,
                as_of,
                provenance=provenance,
                quality=quality,
                methodology=(
                    "sum(price * volume) divided by sum(volume)"
                    if provenance is Provenance.DERIVED_FROM_OBSERVED
                    else "volume-weighted bar representative price; (high + low + close) / 3"
                ),
            ),
            "vwap_stddev": self._metric(
                standard_deviation,
                as_of,
                provenance=provenance,
                quality=quality,
                methodology="volume-weighted square-root price dispersion around VWAP",
            ),
        }
        current_price = self._last_price
        if current_price is None:
            metrics["distance_from_vwap_bps"] = self._unavailable(
                as_of, "current price is unavailable"
            )
        else:
            metrics["distance_from_vwap_bps"] = self._metric(
                (current_price - vwap) / vwap * 10_000,
                as_of,
                provenance=provenance,
                quality=quality,
                methodology="current representative price minus VWAP in bps",
            )
        if current_price is None:
            metrics["vwap_zscore"] = self._unavailable(
                as_of, "current price is unavailable"
            )
        elif standard_deviation == 0:
            metrics["vwap_zscore"] = self._unavailable(
                as_of, "zero weighted price dispersion"
            )
        else:
            metrics["vwap_zscore"] = self._metric(
                (current_price - vwap) / standard_deviation,
                as_of,
                provenance=provenance,
                quality=quality,
                methodology="current price deviation divided by VWAP dispersion",
            )
        for index, multiplier in enumerate(self.config.vwap.band_multipliers, 1):
            metrics[f"vwap_upper_{index}"] = self._metric(
                vwap + multiplier * standard_deviation,
                as_of,
                provenance=provenance,
                quality=quality,
                methodology=f"VWAP plus {multiplier} weighted standard deviations",
            )
            metrics[f"vwap_lower_{index}"] = self._metric(
                vwap - multiplier * standard_deviation,
                as_of,
                provenance=provenance,
                quality=quality,
                methodology=f"VWAP minus {multiplier} weighted standard deviations",
            )
        if len(self._vwap_samples) < 2:
            metrics["vwap_slope"] = self._unavailable(
                as_of, "fewer than two VWAP samples"
            )
        else:
            metrics["vwap_slope"] = self._metric(
                self._slope(list(self._vwap_samples)),
                as_of,
                provenance=provenance,
                quality=quality,
                methodology="linear VWAP slope per accumulated observation",
            )
        return VWAPSnapshot(as_of, session_id, metrics)

    def _start_session(self, session_id: str) -> None:
        if session_id == self._session_id:
            return
        self._session_id = session_id
        self._price_volume = 0.0
        self._price_squared_volume = 0.0
        self._volume = 0.0
        self._last_price = None
        self._vwap_samples.clear()
        self._has_approximate = False

    def start_session(self, session_id: str) -> None:
        self._start_session(session_id)

    def _add_observation(
        self, price: float, volume: float, *, approximate: bool
    ) -> None:
        self._price_volume += price * volume
        self._price_squared_volume += price * price * volume
        self._volume += volume
        self._vwap_samples.append(self._price_volume / self._volume)
        if approximate:
            self._has_approximate = True

    def _unavailable_metrics(
        self, as_of: datetime, reason: str
    ) -> dict[str, MetricResult[float]]:
        names = [
            "session_vwap",
            "vwap_stddev",
            "distance_from_vwap_bps",
            "vwap_zscore",
            "vwap_slope",
        ]
        for index in range(1, len(self.config.vwap.band_multipliers) + 1):
            names.extend((f"vwap_upper_{index}", f"vwap_lower_{index}"))
        return {name: self._unavailable(as_of, reason) for name in names}

    def _metric(
        self,
        value: float,
        as_of: datetime,
        *,
        provenance: Provenance,
        quality: float,
        methodology: str,
        status: MetricStatus = MetricStatus.OK,
        reason: str | None = None,
    ) -> MetricResult[float]:
        if not isfinite(value):
            return self._unavailable(as_of, "non-finite VWAP metric")
        return MetricResult(
            value,
            MetricMetadata(
                as_of=as_of,
                provider=self.provider,
                dataset=self.dataset,
                venue_scope=self.venue_scope,
                status=status,
                methodology=methodology,
                quality_score=quality,
                observed_or_modeled=provenance,
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
                venue_scope=self.venue_scope,
                reason=reason,
            ),
        )

    @staticmethod
    def _slope(values: list[float]) -> float:
        return linear_regression(list(range(len(values))), values).slope
