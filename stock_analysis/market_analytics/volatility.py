"""Provider-neutral implied and realized volatility state."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from math import ceil, isfinite, log, sqrt
from statistics import mean, median, stdev
from zoneinfo import ZoneInfo

from .config import AnalyticsConfig
from .models import (
    CallPut,
    InstrumentSpec,
    MetricMetadata,
    MetricResult,
    MetricStatus,
    OptionChainEvent,
    Provenance,
    _require_utc,
)
from .options import IVSurfaceAnalyzer, NormalizedOptionChain
from .providers import CapabilityRegistry


class IVRVClassification(StrEnum):
    IV_DEEPLY_BELOW_RV = "iv_deeply_below_rv"
    IV_BELOW_RV = "iv_below_rv"
    IV_NEAR_RV = "iv_near_rv"
    IV_ABOVE_RV = "iv_above_rv"
    IV_FAR_ABOVE_RV = "iv_far_above_rv"
    UNAVAILABLE = "unavailable"


class TermStructureClassification(StrEnum):
    STEEP_CONTANGO = "steep_contango"
    CONTANGO = "contango"
    FLAT = "flat"
    BACKWARDATION = "backwardation"
    STEEP_BACKWARDATION = "steep_backwardation"
    INSUFFICIENT_DATA = "insufficient_data"


class SkewClassification(StrEnum):
    STRONG_PUT_SKEW = "strong_put_skew"
    PUT_SKEW = "put_skew"
    BALANCED = "balanced"
    CALL_SKEW = "call_skew"
    STRONG_CALL_SKEW = "strong_call_skew"
    INSUFFICIENT_DATA = "insufficient_data"


class EventVolatilitySeverity(StrEnum):
    NONE = "none"
    ELEVATED = "elevated"
    EXTREME = "extreme"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ATMVolatility:
    expiration: date
    dte_days: int
    time_to_expiry_years: float
    call_iv: MetricResult[float]
    put_iv: MetricResult[float]
    atm_iv: MetricResult[float]

    @property
    def confidence(self) -> float:
        return self.atm_iv.metadata.quality_score / 100.0


@dataclass(frozen=True, slots=True)
class IVHistoryContext:
    horizon_days: int
    window_sessions: int
    current: MetricResult[float]
    mean: MetricResult[float]
    median: MetricResult[float]
    standard_deviation: MetricResult[float]
    percentile: MetricResult[float]
    rank: MetricResult[float]
    z_score: MetricResult[float]
    observation_count: int


@dataclass(frozen=True, slots=True)
class IVRVComparison:
    horizon_days: int
    realized_window_sessions: int | None
    iv: MetricResult[float]
    rv: MetricResult[float]
    spread: MetricResult[float]
    ratio: MetricResult[float]
    implied_variance: MetricResult[float]
    realized_variance: MetricResult[float]
    variance_spread: MetricResult[float]
    classification: IVRVClassification


@dataclass(frozen=True, slots=True)
class TermStructureState:
    by_horizon: dict[int, MetricResult[float]]
    spreads: dict[tuple[int, int], MetricResult[float]]
    normalized_slopes: dict[tuple[int, int], MetricResult[float]]
    classification: TermStructureClassification
    metadata: MetricMetadata


@dataclass(frozen=True, slots=True)
class EventVolatilityState:
    detected: bool
    severity: EventVolatilitySeverity
    expiration: date | None
    premium_by_pair: dict[tuple[int, int], MetricResult[float]]
    front_variance_excess: MetricResult[float]
    event_date: datetime | None
    metadata: MetricMetadata


@dataclass(frozen=True, slots=True)
class SkewState:
    expiration: date
    atm_iv: MetricResult[float]
    put_25_delta_iv: MetricResult[float]
    call_25_delta_iv: MetricResult[float]
    put_skew: MetricResult[float]
    call_skew: MetricResult[float]
    risk_reversal: MetricResult[float]
    butterfly: MetricResult[float]
    classification: SkewClassification
    metadata: MetricMetadata


@dataclass(frozen=True, slots=True)
class VolatilityState:
    as_of: datetime
    symbol: str
    spot: float
    atm_by_expiration: dict[date, ATMVolatility]
    implied_by_horizon: dict[int, MetricResult[float]]
    realized_by_window: dict[int, MetricResult[float]]
    iv_history: dict[int, dict[int, IVHistoryContext]]
    iv_rv: dict[int, IVRVComparison]
    term_structure: TermStructureState
    event: EventVolatilityState
    skew_by_expiration: dict[date, SkewState]
    surface_confidence: MetricResult[float]
    metadata: MetricMetadata


class VolatilityEngine:
    """Calculate all stock-wide volatility state from point-in-time inputs."""

    def __init__(
        self,
        config: AnalyticsConfig,
        instrument: InstrumentSpec | None = None,
        provider: str = "analytics",
    ) -> None:
        self.config = config
        self.instrument = instrument or InstrumentSpec("UNKNOWN", "UNKNOWN", 0.01)
        self.provider = provider
        self.dataset = "volatility"
        max_close_window = max(config.volatility.realized_windows_sessions, default=2)
        max_history = max(config.volatility.max_iv_history, 1)
        self._closes: deque[tuple[str, float, datetime]] = deque(
            maxlen=max(max_close_window + 1, 2)
        )
        self._iv_history: dict[int, deque[float]] = {
            horizon: deque(maxlen=max_history)
            for horizon in config.volatility.implied_horizons_days
        }
        self._finalized_sessions: set[str] = set()
        self._latest_state: VolatilityState | None = None
        self._last_chain: NormalizedOptionChain | None = None
        self._last_spot: float | None = None
        self._last_supports_iv = True
        self._last_event_dates: tuple[datetime, ...] = ()
        self._surface = IVSurfaceAnalyzer(config)

    def analyze(
        self,
        chain: NormalizedOptionChain | OptionChainEvent | None,
        spot: float | None,
        as_of: datetime,
        *,
        supports_iv: bool = True,
        capabilities: CapabilityRegistry | None = None,
        event_dates: Iterable[datetime] = (),
    ) -> VolatilityState:
        _require_utc(as_of, "as_of")
        normalized: NormalizedOptionChain | None
        if isinstance(chain, OptionChainEvent):
            normalized = self._surface.normalizer.normalize(
                chain, capabilities=capabilities
            )
            if spot is None:
                spot = chain.spot
        else:
            normalized = chain
        if spot is None:
            spot = self._last_spot
        if spot is None or spot <= 0 or not isfinite(spot):
            raise ValueError("spot must be positive and finite")
        events = tuple(event_dates)
        for event_date in events:
            _require_utc(event_date, "event date")
        self._last_chain = normalized
        self._last_spot = spot
        self._last_supports_iv = supports_iv
        self._last_event_dates = events
        state = self._build_state(normalized, spot, as_of, supports_iv, events)
        self._latest_state = state
        return state

    def finalize_session(
        self,
        session_id: str,
        close: float,
        as_of: datetime,
        *,
        include_iv_observation: bool = True,
    ) -> None:
        """Append one completed close and the current IV observation once."""
        _require_utc(as_of, "as_of")
        if not session_id:
            raise ValueError("session_id must not be empty")
        if close <= 0 or not isfinite(close):
            raise ValueError("close must be positive and finite")
        if session_id in self._finalized_sessions:
            return
        self._finalized_sessions.add(session_id)
        self._closes.append((session_id, close, as_of))
        if self._latest_state is None or not include_iv_observation:
            return
        for horizon, result in self._latest_state.implied_by_horizon.items():
            if result.value is not None:
                self._iv_history.setdefault(
                    horizon, deque(maxlen=self.config.volatility.max_iv_history)
                ).append(result.value)
        realized = self._realized_metrics(as_of)
        comparisons = self._iv_rv_metrics(
            self._latest_state.implied_by_horizon, realized, as_of
        )
        self._latest_state = replace(
            self._latest_state,
            realized_by_window=realized,
            iv_rv=comparisons,
        )

    def observe_spot(self, spot: float, as_of: datetime) -> VolatilityState:
        """Refresh the point-in-time state when a new underlying price arrives."""
        _require_utc(as_of, "as_of")
        if self._last_chain is None:
            return self.analyze(None, spot, as_of, supports_iv=False)
        state = self._build_state(
            self._last_chain,
            spot,
            as_of,
            self._last_supports_iv,
            self._last_event_dates,
        )
        self._last_spot = spot
        self._latest_state = state
        return state

    def current(self) -> VolatilityState | None:
        return self._latest_state

    def _build_state(
        self,
        chain: NormalizedOptionChain | None,
        spot: float,
        as_of: datetime,
        supports_iv: bool,
        event_dates: tuple[datetime, ...],
    ) -> VolatilityState:
        provider = chain.provider if chain is not None else self.provider
        dataset = chain.dataset if chain is not None else self.dataset
        implied: dict[int, MetricResult[float]] = {}
        atm: dict[date, ATMVolatility] = {}
        skew: dict[date, SkewState] = {}
        if chain is not None and supports_iv and self._chain_is_current(chain, as_of):
            surface = self._surface.analyze(chain, spot, as_of, supports_iv=True)
            surface_points = sum(
                result.value is not None
                for values in surface.by_expiration.values()
                for result in values.values()
            )
            if surface_points >= self.config.volatility.min_surface_points:
                atm = self._atm_by_expiration(chain, surface.by_expiration, spot, as_of)
                implied = self._implied_horizons(atm, as_of, provider, dataset)
                skew = self._skew_by_expiration(
                    chain, surface.by_expiration, atm, as_of
                )
            else:
                reason = (
                    f"at least {self.config.volatility.min_surface_points} valid "
                    f"surface points are required; received {surface_points}"
                )
                implied = {
                    horizon: self._unavailable(as_of, provider, dataset, reason)
                    for horizon in self.config.volatility.implied_horizons_days
                }
        else:
            reason = (
                "IV capability is unsupported"
                if not supports_iv
                else "no current option chain"
                if chain is None
                else "option chain is stale or after analysis time"
            )
            implied = {
                horizon: self._unavailable(as_of, provider, dataset, reason)
                for horizon in self.config.volatility.implied_horizons_days
            }
        realized = self._realized_metrics(as_of)
        history = self._history_context(implied, as_of, provider, dataset)
        comparisons = self._iv_rv_metrics(implied, realized, as_of)
        term = self._term_structure(implied, as_of, provider, dataset)
        event = self._event_state(implied, atm, as_of, provider, dataset, event_dates)
        confidence = self._surface_confidence(atm, as_of, provider, dataset)
        metadata = self._metadata(
            as_of,
            provider,
            dataset,
            "system-wide implied and realized volatility state",
            quality=confidence.value or 0.0,
            status=(
                MetricStatus.UNAVAILABLE
                if confidence.value is None
                else MetricStatus.OK
                if confidence.value >= 100
                else MetricStatus.DEGRADED
            ),
            reason=confidence.metadata.reason,
        )
        return VolatilityState(
            as_of=as_of,
            symbol=chain.symbol if chain is not None else self.instrument.symbol,
            spot=spot,
            atm_by_expiration=atm,
            implied_by_horizon=implied,
            realized_by_window=realized,
            iv_history=history,
            iv_rv=comparisons,
            term_structure=term,
            event=event,
            skew_by_expiration=skew,
            surface_confidence=confidence,
            metadata=metadata,
        )

    def _chain_is_current(self, chain: NormalizedOptionChain, as_of: datetime) -> bool:
        age = as_of - chain.timestamp
        return age.total_seconds() >= 0 and age <= self.config.options.max_quote_age

    def _atm_by_expiration(
        self,
        chain: NormalizedOptionChain,
        by_expiration: Mapping[
            date, Mapping[tuple[float, CallPut], MetricResult[float]]
        ],
        spot: float,
        as_of: datetime,
    ) -> dict[date, ATMVolatility]:
        result: dict[date, ATMVolatility] = {}
        for expiration, values in sorted(by_expiration.items()):
            time_to_expiry = self._time_to_expiry(expiration, as_of)
            if time_to_expiry <= 0:
                continue
            call = self._strike_atm(
                values, CallPut.CALL, spot, as_of, chain.provider, chain.dataset
            )
            put = self._strike_atm(
                values, CallPut.PUT, spot, as_of, chain.provider, chain.dataset
            )
            atm = self._combine_atm(call, put, as_of, chain.provider, chain.dataset)
            if atm.value is None:
                continue
            result[expiration] = ATMVolatility(
                expiration=expiration,
                dte_days=max(1, ceil(time_to_expiry * 365.0)),
                time_to_expiry_years=time_to_expiry,
                call_iv=call,
                put_iv=put,
                atm_iv=atm,
            )
        return result

    def _strike_atm(
        self,
        values: Mapping[tuple[float, CallPut], MetricResult[float]],
        call_put: CallPut,
        spot: float,
        as_of: datetime,
        provider: str,
        dataset: str,
    ) -> MetricResult[float]:
        points = sorted(
            (strike, metric)
            for (strike, side), metric in values.items()
            if side is call_put and metric.value is not None
        )
        if not points:
            return self._unavailable(
                as_of, provider, dataset, f"no valid {call_put.value} IV observations"
            )
        exact = next((metric for strike, metric in points if strike == spot), None)
        if exact is not None:
            return exact
        lower = next(
            ((strike, metric) for strike, metric in reversed(points) if strike < spot),
            None,
        )
        upper = next(
            ((strike, metric) for strike, metric in points if strike > spot), None
        )
        if lower is not None and upper is not None:
            lower_strike, lower_metric = lower
            upper_strike, upper_metric = upper
            weight = (spot - lower_strike) / (upper_strike - lower_strike)
            quality = min(
                lower_metric.metadata.quality_score,
                upper_metric.metadata.quality_score,
            )
            status = (
                MetricStatus.OK
                if lower_metric.metadata.status is MetricStatus.OK
                and upper_metric.metadata.status is MetricStatus.OK
                else MetricStatus.DEGRADED
            )
            lower_value = lower_metric.value
            upper_value = upper_metric.value
            assert lower_value is not None and upper_value is not None
            return self._metric(
                (1.0 - weight) * lower_value + weight * upper_value,
                as_of,
                provider,
                dataset,
                "linear strike interpolation of surrounding ATM IV observations",
                quality=quality,
                status=status,
                reason="one or more surrounding IV observations are degraded"
                if status is MetricStatus.DEGRADED
                else None,
            )
        nearest = min(points, key=lambda item: (abs(item[0] - spot), item[0]))[1]
        return self._metric(
            nearest.value,
            as_of,
            provider,
            dataset,
            "nearest available strike used because ATM interpolation was one-sided",
            quality=min(75.0, nearest.metadata.quality_score),
            status=MetricStatus.DEGRADED,
            reason="no valid IV observations on both sides of spot",
        )

    def _combine_atm(
        self,
        call: MetricResult[float],
        put: MetricResult[float],
        as_of: datetime,
        provider: str,
        dataset: str,
    ) -> MetricResult[float]:
        values = [result for result in (call, put) if result.value is not None]
        if not values:
            return self._unavailable(
                as_of, provider, dataset, "call and put ATM IV are unavailable"
            )
        quality = min(item.metadata.quality_score for item in values)
        status = (
            MetricStatus.OK
            if len(values) == 2
            and all(item.metadata.status is MetricStatus.OK for item in values)
            else MetricStatus.DEGRADED
        )
        numeric_values = [item.value for item in values]
        assert all(value is not None for value in numeric_values)
        return self._metric(
            sum(value for value in numeric_values if value is not None)
            / len(numeric_values),
            as_of,
            provider,
            dataset,
            "average of call and put ATM IV"
            if len(values) == 2
            else "one-sided ATM IV",
            quality=quality,
            status=status,
            reason="one ATM option side is unavailable" if len(values) == 1 else None,
        )

    def _implied_horizons(
        self,
        atm: Mapping[date, ATMVolatility],
        as_of: datetime,
        provider: str,
        dataset: str,
    ) -> dict[int, MetricResult[float]]:
        points = sorted(
            (item.time_to_expiry_years, item.atm_iv)
            for item in atm.values()
            if item.atm_iv.value is not None
        )
        result: dict[int, MetricResult[float]] = {}
        for horizon in self.config.volatility.implied_horizons_days:
            target = horizon / 365.0
            if len(points) < 1 or target < points[0][0] or target > points[-1][0]:
                result[horizon] = self._unavailable(
                    as_of,
                    provider,
                    dataset,
                    f"target horizon {horizon}d is not bracketed by option expirations",
                )
                continue
            if len(points) == 1:
                point_time, point_iv = points[0]
                if abs(target - point_time) > 1e-9:
                    result[horizon] = self._unavailable(
                        as_of,
                        provider,
                        dataset,
                        f"target horizon {horizon}d has no bracketing expiration",
                    )
                    continue
                result[horizon] = point_iv
                continue
            upper_index = next(
                index
                for index, (point_time, _) in enumerate(points)
                if point_time >= target
            )
            if points[upper_index][0] == target or upper_index == 0:
                lower_index = upper_index
            else:
                lower_index = upper_index - 1
            lower_time, lower_iv = points[lower_index]
            upper_time, upper_iv = points[upper_index]
            if lower_index == upper_index:
                result[horizon] = lower_iv
                continue
            weight = (target - lower_time) / (upper_time - lower_time)
            lower_value = lower_iv.value
            upper_value = upper_iv.value
            assert lower_value is not None and upper_value is not None
            lower_variance = lower_value**2 * lower_time
            upper_variance = upper_value**2 * upper_time
            quality = min(
                lower_iv.metadata.quality_score,
                upper_iv.metadata.quality_score,
            )
            status = (
                MetricStatus.OK
                if lower_iv.metadata.status is MetricStatus.OK
                and upper_iv.metadata.status is MetricStatus.OK
                else MetricStatus.DEGRADED
            )
            result[horizon] = self._metric(
                sqrt(
                    ((1.0 - weight) * lower_variance + weight * upper_variance) / target
                ),
                as_of,
                provider,
                dataset,
                "linear interpolation of total variance in time space",
                quality=quality,
                status=status,
                reason="one bracketing expiration is degraded"
                if status is MetricStatus.DEGRADED
                else None,
            )
        return result

    def _skew_by_expiration(
        self,
        chain: NormalizedOptionChain,
        by_expiration: Mapping[
            date, Mapping[tuple[float, CallPut], MetricResult[float]]
        ],
        atm: Mapping[date, ATMVolatility],
        as_of: datetime,
    ) -> dict[date, SkewState]:
        result: dict[date, SkewState] = {}
        contracts = {
            (contract.expiration, contract.strike, contract.call_put): contract
            for contract in chain.accepted
        }
        for expiration, atm_value in atm.items():
            values = by_expiration.get(expiration, {})
            put_points: list[tuple[float, MetricResult[float]]] = []
            call_points: list[tuple[float, MetricResult[float]]] = []
            for key, metric in values.items():
                contract = contracts.get((expiration, key[0], key[1]))
                if contract is None or contract.delta is None or metric.value is None:
                    continue
                target = abs(contract.delta)
                if contract.call_put is CallPut.PUT:
                    put_points.append((target, metric))
                else:
                    call_points.append((target, metric))
            put_iv = self._delta_target(put_points, as_of, chain, "put")
            call_iv = self._delta_target(call_points, as_of, chain, "call")
            put_skew = self._difference_metric(
                put_iv, atm_value.atm_iv, as_of, chain, "put skew"
            )
            call_skew = self._difference_metric(
                call_iv, atm_value.atm_iv, as_of, chain, "call skew"
            )
            rr = self._difference_metric(
                call_iv, put_iv, as_of, chain, "25-delta risk reversal"
            )
            butterfly = self._average_difference_metric(
                put_iv, call_iv, atm_value.atm_iv, as_of, chain, "25-delta butterfly"
            )
            classification = self._skew_classification(put_skew, call_skew)
            metrics = [put_iv, call_iv, put_skew, call_skew, rr, butterfly]
            available = [
                metric.metadata.quality_score
                for metric in metrics
                if metric.value is not None
            ]
            metadata = self._metadata(
                as_of,
                chain.provider,
                chain.dataset,
                "25-delta put/call IV skew and smile metrics",
                quality=min(available) if available else 0.0,
                status=MetricStatus.OK
                if len(available) == len(metrics)
                else MetricStatus.UNAVAILABLE,
                reason=None
                if len(available) == len(metrics)
                else "one or more 25-delta skew observations are unavailable",
            )
            result[expiration] = SkewState(
                expiration=expiration,
                atm_iv=atm_value.atm_iv,
                put_25_delta_iv=put_iv,
                call_25_delta_iv=call_iv,
                put_skew=put_skew,
                call_skew=call_skew,
                risk_reversal=rr,
                butterfly=butterfly,
                classification=classification,
                metadata=metadata,
            )
        return result

    def _delta_target(
        self,
        points: list[tuple[float, MetricResult[float]]],
        as_of: datetime,
        chain: NormalizedOptionChain,
        side: str,
    ) -> MetricResult[float]:
        points.sort(key=lambda item: item[0])
        target = 0.25
        if not points:
            return self._unavailable(
                as_of, chain.provider, chain.dataset, f"no {side} delta observations"
            )
        exact = next((metric for delta, metric in points if delta == target), None)
        if exact is not None:
            return exact
        lower = next(
            ((delta, metric) for delta, metric in reversed(points) if delta < target),
            None,
        )
        upper = next(
            ((delta, metric) for delta, metric in points if delta > target), None
        )
        if lower is None or upper is None:
            nearest = min(points, key=lambda item: (abs(item[0] - target), item[0]))[1]
            return self._metric(
                nearest.value,
                as_of,
                chain.provider,
                chain.dataset,
                f"nearest available {side} delta IV used for 25-delta target",
                quality=min(75.0, nearest.metadata.quality_score),
                status=MetricStatus.DEGRADED,
                reason=f"{side} delta observations do not bracket 25 delta",
            )
        lower_delta, lower_metric = lower
        upper_delta, upper_metric = upper
        weight = (target - lower_delta) / (upper_delta - lower_delta)
        lower_value = lower_metric.value
        upper_value = upper_metric.value
        assert lower_value is not None and upper_value is not None
        return self._metric(
            (1.0 - weight) * lower_value + weight * upper_value,
            as_of,
            chain.provider,
            chain.dataset,
            f"linear delta interpolation of {side} IV to 25 delta",
            quality=min(
                lower_metric.metadata.quality_score, upper_metric.metadata.quality_score
            ),
            status=MetricStatus.OK
            if lower_metric.metadata.status is MetricStatus.OK
            and upper_metric.metadata.status is MetricStatus.OK
            else MetricStatus.DEGRADED,
        )

    def _history_context(
        self,
        implied: Mapping[int, MetricResult[float]],
        as_of: datetime,
        provider: str,
        dataset: str,
    ) -> dict[int, dict[int, IVHistoryContext]]:
        result: dict[int, dict[int, IVHistoryContext]] = {}
        for horizon, current in implied.items():
            result[horizon] = {}
            for window in self.config.volatility.iv_history_windows:
                prior = list(self._iv_history.get(horizon, ()))[-window:]
                result[horizon][window] = self._history_for(
                    horizon, window, current, prior, as_of, provider, dataset
                )
        return result

    def _history_for(
        self,
        horizon: int,
        window: int,
        current: MetricResult[float],
        prior: list[float],
        as_of: datetime,
        provider: str,
        dataset: str,
    ) -> IVHistoryContext:
        def unavailable(reason: str) -> MetricResult[float]:
            return self._unavailable(as_of, provider, dataset, reason)
        if current.value is None:
            missing = unavailable("current IV is unavailable")
            return IVHistoryContext(
                horizon,
                window,
                current,
                missing,
                missing,
                missing,
                missing,
                missing,
                missing,
                len(prior),
            )
        history_mean = (
            self._history_metric(
                mean(prior),
                current,
                as_of,
                provider,
                dataset,
                "rolling historical IV mean",
            )
            if prior
            else unavailable("no prior IV observations")
        )
        history_median = (
            self._history_metric(
                median(prior),
                current,
                as_of,
                provider,
                dataset,
                "rolling historical IV median",
            )
            if prior
            else unavailable("no prior IV observations")
        )
        deviation = stdev(prior) if len(prior) >= 2 else None
        standard_deviation = (
            self._history_metric(
                deviation,
                current,
                as_of,
                provider,
                dataset,
                "sample standard deviation of prior IV observations",
            )
            if deviation is not None
            else unavailable(
                "at least two prior IV observations are required for standard deviation"
            )
        )
        percentile = (
            self._history_metric(
                100.0 * sum(value < current.value for value in prior) / len(prior),
                current,
                as_of,
                provider,
                dataset,
                "percentage of prior IV observations below current IV",
            )
            if prior
            else unavailable("no prior IV observations")
        )
        if prior and max(prior) > min(prior):
            rank_value = (
                100.0 * (current.value - min(prior)) / (max(prior) - min(prior))
            )
            rank = self._history_metric(
                max(0.0, min(100.0, rank_value)),
                current,
                as_of,
                provider,
                dataset,
                "historical IV rank from prior low and high",
            )
        else:
            rank = unavailable("historical IV range is unavailable or zero")
        if deviation is not None and deviation > 0:
            z_score = self._history_metric(
                (current.value - mean(prior)) / deviation,
                current,
                as_of,
                provider,
                dataset,
                "current IV z-score against prior observations",
            )
        else:
            z_score = unavailable(
                "nonzero historical IV standard deviation is required for z-score"
            )
        return IVHistoryContext(
            horizon,
            window,
            current,
            history_mean,
            history_median,
            standard_deviation,
            percentile,
            rank,
            z_score,
            len(prior),
        )

    def _realized_metrics(self, as_of: datetime) -> dict[int, MetricResult[float]]:
        result: dict[int, MetricResult[float]] = {}
        closes = list(self._closes)
        for window in self.config.volatility.realized_windows_sessions:
            if len(closes) < window + 1:
                result[window] = self._unavailable(
                    as_of,
                    self.provider,
                    "realized_volatility",
                    f"{window + 1} completed closes are required",
                )
                continue
            values = [close for _, close, _ in closes[-(window + 1) :]]
            returns = [
                log(values[index] / values[index - 1])
                for index in range(1, len(values))
            ]
            volatility = stdev(returns) * sqrt(252.0)
            result[window] = self._metric(
                volatility,
                as_of,
                self.provider,
                "realized_volatility",
                "close-to-close sample log-return volatility annualized with sqrt(252)",
            )
        return result

    def _iv_rv_metrics(
        self,
        implied: Mapping[int, MetricResult[float]],
        realized: Mapping[int, MetricResult[float]],
        as_of: datetime,
    ) -> dict[int, IVRVComparison]:
        result: dict[int, IVRVComparison] = {}
        for horizon, iv in implied.items():
            available_windows = [
                window
                for window, metric in realized.items()
                if metric.value is not None
            ]
            if not available_windows:
                rv_window = None
                rv = self._unavailable(
                    as_of,
                    self.provider,
                    "realized_volatility",
                    "no realized volatility window is available",
                )
            else:
                rv_window = min(
                    available_windows,
                    key=lambda window: (abs(window - horizon), window),
                )
                rv = realized[rv_window]
            if iv.value is None or rv.value is None or rv.value <= 0:
                unavailable = self._unavailable(
                    as_of,
                    self.provider,
                    "volatility_comparison",
                    "both IV and positive RV are required",
                )
                result[horizon] = IVRVComparison(
                    horizon,
                    rv_window,
                    iv,
                    rv,
                    unavailable,
                    unavailable,
                    unavailable,
                    unavailable,
                    unavailable,
                    IVRVClassification.UNAVAILABLE,
                )
                continue
            iv_value = iv.value
            rv_value = rv.value
            assert iv_value is not None and rv_value is not None
            spread = self._derived_metric(
                iv_value - rv_value,
                iv,
                rv,
                as_of,
                "implied volatility minus realized volatility",
            )
            ratio = self._derived_metric(
                iv_value / rv_value,
                iv,
                rv,
                as_of,
                "implied volatility divided by realized volatility",
            )
            implied_variance = self._derived_metric(
                iv_value**2,
                iv,
                iv,
                as_of,
                "implied volatility squared",
            )
            realized_variance = self._derived_metric(
                rv_value**2,
                rv,
                rv,
                as_of,
                "realized volatility squared",
            )
            implied_variance_value = implied_variance.value
            realized_variance_value = realized_variance.value
            assert (
                implied_variance_value is not None
                and realized_variance_value is not None
            )
            variance_spread = self._derived_metric(
                implied_variance_value - realized_variance_value,
                implied_variance,
                realized_variance,
                as_of,
                "implied variance minus realized variance",
            )
            result[horizon] = IVRVComparison(
                horizon,
                rv_window,
                iv,
                rv,
                spread,
                ratio,
                implied_variance,
                realized_variance,
                variance_spread,
                self._iv_rv_classification(spread.value),
            )
        return result

    def _term_structure(
        self,
        implied: Mapping[int, MetricResult[float]],
        as_of: datetime,
        provider: str,
        dataset: str,
    ) -> TermStructureState:
        available = sorted(
            (horizon, metric)
            for horizon, metric in implied.items()
            if metric.value is not None
        )
        spreads: dict[tuple[int, int], MetricResult[float]] = {}
        slopes: dict[tuple[int, int], MetricResult[float]] = {}
        reason: str | None
        for first, second in ((7, 30), (14, 30), (30, 60), (30, 90)):
            first_metric = implied.get(first)
            second_metric = implied.get(second)
            if (
                first_metric is None
                or second_metric is None
                or first_metric.value is None
                or second_metric.value is None
            ):
                missing = self._unavailable(
                    as_of,
                    provider,
                    dataset,
                    f"term spread {first}d/{second}d is unavailable",
                )
                spreads[(first, second)] = missing
                slopes[(first, second)] = missing
                continue
            spreads[(first, second)] = self._derived_metric(
                first_metric.value - second_metric.value,
                first_metric,
                second_metric,
                as_of,
                f"{first}d IV minus {second}d IV",
            )
            slopes[(first, second)] = self._derived_metric(
                (second_metric.value - first_metric.value) / (second - first),
                first_metric,
                second_metric,
                as_of,
                f"normalized IV slope from {first}d to {second}d",
            )
        if len(available) < 2:
            classification = TermStructureClassification.INSUFFICIENT_DATA
            quality = 0.0
            status = MetricStatus.UNAVAILABLE
            reason = "at least two interpolated or observed IV horizons are required"
        else:
            _, first_metric = available[0]
            _, last_metric = available[-1]
            first_value = first_metric.value
            last_value = last_metric.value
            assert first_value is not None and last_value is not None
            difference = last_value - first_value
            threshold = self.config.volatility.term_steep_threshold
            if abs(difference) <= threshold / 2:
                classification = TermStructureClassification.FLAT
            elif difference > 0:
                classification = (
                    TermStructureClassification.STEEP_CONTANGO
                    if difference >= threshold
                    else TermStructureClassification.CONTANGO
                )
            else:
                classification = (
                    TermStructureClassification.STEEP_BACKWARDATION
                    if difference <= -threshold
                    else TermStructureClassification.BACKWARDATION
                )
            quality = min(
                first_metric.metadata.quality_score, last_metric.metadata.quality_score
            )
            status = MetricStatus.OK if quality >= 100 else MetricStatus.DEGRADED
            reason = (
                None
                if status is MetricStatus.OK
                else "one or more term-structure inputs are degraded"
            )
        metadata = self._metadata(
            as_of,
            provider,
            dataset,
            "IV term structure and normalized slope",
            quality,
            status,
            reason,
        )
        return TermStructureState(
            dict(implied), spreads, slopes, classification, metadata
        )

    def _event_state(
        self,
        implied: Mapping[int, MetricResult[float]],
        atm: Mapping[date, ATMVolatility],
        as_of: datetime,
        provider: str,
        dataset: str,
        event_dates: tuple[datetime, ...],
    ) -> EventVolatilityState:
        pairs = ((7, 30), (14, 30))
        premiums: dict[tuple[int, int], MetricResult[float]] = {}
        excess = self._unavailable(
            as_of, provider, dataset, "front variance excess is unavailable"
        )
        detected = False
        best_premium: float | None = None
        selected_expiration: date | None = None
        for first, second in pairs:
            first_metric = implied.get(first)
            second_metric = implied.get(second)
            if (
                first_metric is None
                or second_metric is None
                or first_metric.value is None
                or second_metric.value is None
            ):
                premiums[(first, second)] = self._unavailable(
                    as_of,
                    provider,
                    dataset,
                    f"event premium {first}d/{second}d is unavailable",
                )
                continue
            premium = self._derived_metric(
                first_metric.value - second_metric.value,
                first_metric,
                second_metric,
                as_of,
                f"front {first}d IV minus {second}d IV",
            )
            premiums[(first, second)] = premium
            premium_value = premium.value
            assert premium_value is not None
            if best_premium is None or premium_value > best_premium:
                best_premium = premium_value
            if premium_value >= self.config.volatility.event_premium_threshold:
                detected = True
                candidate = min(
                    atm.values(),
                    key=lambda item: abs(item.dte_days - first),
                    default=None,
                )
                selected_expiration = (
                    candidate.expiration if candidate is not None else None
                )
            if (
                first == 7
                and first_metric.value is not None
                and second_metric.value is not None
            ):
                excess = self._derived_metric(
                    first_metric.value**2 * (first / 365.0)
                    - second_metric.value**2 * (first / 365.0),
                    first_metric,
                    second_metric,
                    as_of,
                    "front variance above scaled long-horizon variance",
                )
        premium_value = best_premium or 0.0
        if not detected:
            severity = (
                EventVolatilitySeverity.NONE
                if best_premium is not None
                else EventVolatilitySeverity.UNAVAILABLE
            )
        elif premium_value >= 2 * self.config.volatility.event_premium_threshold:
            severity = EventVolatilitySeverity.EXTREME
        else:
            severity = EventVolatilitySeverity.ELEVATED
        event_date = min(
            event_dates,
            key=lambda value: abs((value - as_of).total_seconds()),
            default=None,
        )
        quality_values = [
            metric.metadata.quality_score
            for metric in premiums.values()
            if metric.value is not None
        ]
        metadata = self._metadata(
            as_of,
            provider,
            dataset,
            "short-horizon IV premium heuristic; cause is not inferred",
            min(quality_values) if quality_values else 0.0,
            MetricStatus.OK if quality_values else MetricStatus.UNAVAILABLE,
            None if quality_values else "no paired short and long IV horizons",
        )
        return EventVolatilityState(
            detected,
            severity,
            selected_expiration,
            premiums,
            excess,
            event_date,
            metadata,
        )

    def _surface_confidence(
        self,
        atm: Mapping[date, ATMVolatility],
        as_of: datetime,
        provider: str,
        dataset: str,
    ) -> MetricResult[float]:
        values = [item.atm_iv for item in atm.values() if item.atm_iv.value is not None]
        if not values:
            return self._unavailable(
                as_of, provider, dataset, "no expiration has a usable ATM IV"
            )
        quality = sum(item.metadata.quality_score for item in values) / len(values)
        return self._metric(
            quality,
            as_of,
            provider,
            dataset,
            "mean ATM IV quote quality across available expirations",
            quality=quality,
            status=MetricStatus.OK if quality >= 100 else MetricStatus.DEGRADED,
            reason=None
            if quality >= 100
            else "one or more ATM IV observations are degraded",
        )

    def _time_to_expiry(self, expiration: date, as_of: datetime) -> float:
        expiry = datetime.combine(
            expiration,
            self.config.session.rth_end,
            tzinfo=ZoneInfo(self.config.session.timezone),
        ).astimezone(UTC)
        return (expiry - as_of).total_seconds() / (365.0 * 24.0 * 60.0 * 60.0)

    def _iv_rv_classification(self, spread: float | None) -> IVRVClassification:
        if spread is None:
            return IVRVClassification.UNAVAILABLE
        near = self.config.volatility.iv_rv_near_threshold
        far = self.config.volatility.iv_rv_far_threshold
        if spread <= -far:
            return IVRVClassification.IV_DEEPLY_BELOW_RV
        if spread < -near:
            return IVRVClassification.IV_BELOW_RV
        if abs(spread) <= near:
            return IVRVClassification.IV_NEAR_RV
        if spread <= far:
            return IVRVClassification.IV_ABOVE_RV
        return IVRVClassification.IV_FAR_ABOVE_RV

    def _skew_classification(
        self, put_skew: MetricResult[float], call_skew: MetricResult[float]
    ) -> SkewClassification:
        if put_skew.value is None or call_skew.value is None:
            return SkewClassification.INSUFFICIENT_DATA
        put_threshold = self.config.volatility.skew_put_threshold
        strong_threshold = self.config.volatility.skew_strong_threshold
        if put_skew.value >= strong_threshold and put_skew.value > call_skew.value:
            return SkewClassification.STRONG_PUT_SKEW
        if put_skew.value >= put_threshold and put_skew.value > call_skew.value:
            return SkewClassification.PUT_SKEW
        if call_skew.value <= -strong_threshold and call_skew.value < put_skew.value:
            return SkewClassification.STRONG_CALL_SKEW
        if call_skew.value <= -put_threshold and call_skew.value < put_skew.value:
            return SkewClassification.CALL_SKEW
        return SkewClassification.BALANCED

    def _difference_metric(
        self,
        left: MetricResult[float],
        right: MetricResult[float],
        as_of: datetime,
        chain: NormalizedOptionChain,
        methodology: str,
    ) -> MetricResult[float]:
        if left.value is None or right.value is None:
            return self._unavailable(
                as_of,
                chain.provider,
                chain.dataset,
                f"{methodology} inputs are unavailable",
            )
        return self._derived_metric(
            left.value - right.value, left, right, as_of, methodology
        )

    def _average_difference_metric(
        self,
        put: MetricResult[float],
        call: MetricResult[float],
        atm: MetricResult[float],
        as_of: datetime,
        chain: NormalizedOptionChain,
        methodology: str,
    ) -> MetricResult[float]:
        if put.value is None or call.value is None or atm.value is None:
            return self._unavailable(
                as_of,
                chain.provider,
                chain.dataset,
                f"{methodology} inputs are unavailable",
            )
        return self._metric(
            (put.value + call.value) / 2.0 - atm.value,
            as_of,
            chain.provider,
            chain.dataset,
            methodology,
            quality=min(
                put.metadata.quality_score,
                call.metadata.quality_score,
                atm.metadata.quality_score,
            ),
            status=MetricStatus.OK
            if all(item.metadata.status is MetricStatus.OK for item in (put, call, atm))
            else MetricStatus.DEGRADED,
        )

    def _derived_metric(
        self,
        value: float,
        left: MetricResult[float],
        right: MetricResult[float],
        as_of: datetime,
        methodology: str,
    ) -> MetricResult[float]:
        return MetricResult(
            value,
            MetricMetadata(
                as_of=as_of,
                provider=left.metadata.provider,
                dataset="volatility",
                venue_scope=left.metadata.venue_scope,
                status=(
                    MetricStatus.OK
                    if left.metadata.status is MetricStatus.OK
                    and right.metadata.status is MetricStatus.OK
                    else MetricStatus.DEGRADED
                ),
                methodology=methodology,
                quality_score=min(
                    left.metadata.quality_score, right.metadata.quality_score
                ),
                observed_or_modeled=Provenance.DERIVED_FROM_OBSERVED,
                reason=None,
            ),
        )

    def _history_metric(
        self,
        value: float,
        current: MetricResult[float],
        as_of: datetime,
        provider: str,
        dataset: str,
        methodology: str,
    ) -> MetricResult[float]:
        return self._metric(
            value,
            as_of,
            provider,
            dataset,
            methodology,
            quality=current.metadata.quality_score,
        )

    def _metric(
        self,
        value: float | None,
        as_of: datetime,
        provider: str,
        dataset: str,
        methodology: str,
        *,
        quality: float = 100.0,
        status: MetricStatus = MetricStatus.OK,
        reason: str | None = None,
        provenance: Provenance = Provenance.DERIVED_FROM_OBSERVED,
    ) -> MetricResult[float]:
        return MetricResult(
            value,
            MetricMetadata(
                as_of=as_of,
                provider=provider,
                dataset=dataset,
                venue_scope=self.instrument.venue,
                status=status,
                methodology=methodology,
                quality_score=quality,
                observed_or_modeled=provenance,
                reason=reason,
            ),
        )

    def _metadata(
        self,
        as_of: datetime,
        provider: str,
        dataset: str,
        methodology: str,
        quality: float,
        status: MetricStatus,
        reason: str | None,
    ) -> MetricMetadata:
        return MetricMetadata(
            as_of=as_of,
            provider=provider,
            dataset=dataset,
            venue_scope=self.instrument.venue,
            status=status,
            methodology=methodology,
            quality_score=quality,
            observed_or_modeled=Provenance.DERIVED_FROM_OBSERVED,
            reason=reason,
        )

    def _unavailable(
        self, as_of: datetime, provider: str, dataset: str, reason: str
    ) -> MetricResult[float]:
        return MetricResult(
            None,
            MetricMetadata.unavailable(
                as_of=as_of,
                provider=provider,
                dataset=dataset,
                venue_scope=self.instrument.venue,
                reason=reason,
            ),
        )
