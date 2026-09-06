"""Option normalization, implied volatility, and surface analytics."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from math import exp, isfinite, log, sqrt
from statistics import NormalDist, linear_regression, median
from zoneinfo import ZoneInfo

from .config import AnalyticsConfig, OptionsConfig, SessionConfig
from .models import (
    CallPut,
    MetricMetadata,
    MetricResult,
    MetricStatus,
    OptionChainEvent,
    OptionContractInput,
    Provenance,
    _require_utc,
)
from .providers import CapabilityRegistry

_NORMAL = NormalDist()


class OptionQualityStatus(StrEnum):
    INVALID = "invalid"
    LOW_CONFIDENCE = "low_confidence"
    VALID = "valid"
    HIGH_CONFIDENCE = "high_confidence"


@dataclass(frozen=True, slots=True)
class OptionQuoteQuality:
    valid: bool
    status: OptionQualityStatus
    confidence: float
    flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", OptionQualityStatus(self.status))
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("option quote confidence must be between zero and one")
        object.__setattr__(self, "flags", tuple(dict.fromkeys(self.flags)))


@dataclass(frozen=True, slots=True)
class OptionContract:
    underlying: str
    expiration: date
    strike: float
    call_put: CallPut
    contract_multiplier: float
    bid: float | None
    ask: float | None
    mid: float | None
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
    adjusted: bool
    adjustment_reason: str | None
    bid_size: float | None = None
    ask_size: float | None = None
    quality: OptionQuoteQuality = OptionQuoteQuality(
        True, OptionQualityStatus.HIGH_CONFIDENCE, 1.0
    )


@dataclass(frozen=True, slots=True)
class OptionRejection:
    contract: OptionContractInput
    reason: str


@dataclass(frozen=True, slots=True)
class NormalizedOptionChain:
    accepted: tuple[OptionContract, ...]
    rejected: tuple[OptionRejection, ...]
    symbol: str
    spot: float
    timestamp: datetime
    provider: str
    dataset: str


class OptionChainNormalizer:
    def __init__(self, config: AnalyticsConfig | None = None) -> None:
        self.config = config or AnalyticsConfig()

    def normalize(
        self,
        snapshot: OptionChainEvent,
        *,
        capabilities: CapabilityRegistry | None = None,
    ) -> NormalizedOptionChain:
        accepted: list[OptionContract] = []
        rejected: list[OptionRejection] = []
        for raw in snapshot.contracts:
            reason = self._rejection_reason(raw, snapshot)
            if reason is not None:
                rejected.append(OptionRejection(raw, reason))
                continue
            accepted.append(self._to_contract(raw, snapshot, capabilities))
        return NormalizedOptionChain(
            tuple(accepted),
            tuple(rejected),
            snapshot.symbol,
            snapshot.spot,
            snapshot.timestamp,
            snapshot.provider,
            snapshot.dataset,
        )

    def _rejection_reason(
        self, raw: OptionContractInput, snapshot: OptionChainEvent
    ) -> str | None:
        if raw.underlying != snapshot.symbol:
            return "underlying mismatch"
        expiration_at_close = datetime.combine(
            raw.expiration,
            self.config.session.rth_end,
            tzinfo=ZoneInfo(self.config.session.timezone),
        )
        if expiration_at_close <= snapshot.timestamp.astimezone(
            ZoneInfo(self.config.session.timezone)
        ):
            return "expired contract"
        if raw.strike <= 0:
            return "invalid strike"
        if raw.contract_multiplier <= 0:
            return "invalid multiplier"
        if raw.volume is not None and raw.volume < 0:
            return "negative volume"
        if raw.open_interest is not None and raw.open_interest < 0:
            return "negative open interest"
        if raw.bid is not None and raw.bid < 0:
            return "negative bid"
        if raw.ask is not None and raw.ask <= 0:
            return "nonpositive ask"
        if raw.bid_size is not None and raw.bid_size < 0:
            return "negative bid size"
        if raw.ask_size is not None and raw.ask_size < 0:
            return "negative ask size"
        if raw.last is not None and raw.last < 0:
            return "negative last"
        if raw.bid is not None and raw.ask is not None and raw.bid > raw.ask:
            return "bid above ask"
        prices = [price for price in (raw.bid, raw.ask, raw.last) if price is not None]
        if (not prices or not any(price > 0 for price in prices)) and (
            raw.iv is None or raw.iv <= 0
        ):
            return "missing positive option price"
        if raw.iv is not None and not (
            self.config.options.min_iv <= raw.iv <= self.config.options.max_iv
        ):
            return "invalid implied volatility"
        if raw.adjusted:
            return "adjusted contract unsupported"
        if raw.quote_timestamp is not None:
            age = snapshot.timestamp - raw.quote_timestamp
            if age > self.config.options.max_quote_age:
                return "stale option quote"
            if age.total_seconds() < 0:
                return "future option quote"
        if raw.trade_timestamp is not None and raw.trade_timestamp > snapshot.timestamp:
            return "future option trade"
        if raw.oi_as_of is not None and raw.oi_as_of > snapshot.timestamp:
            return "future open interest"
        return None

    def _to_contract(
        self,
        raw: OptionContractInput,
        snapshot: OptionChainEvent,
        capabilities: CapabilityRegistry | None,
    ) -> OptionContract:
        supports_bid_ask = capabilities is None or capabilities.supports_option_bid_ask
        supports_volume = capabilities is None or capabilities.supports_option_volume
        bid = raw.bid if supports_bid_ask else None
        ask = raw.ask if supports_bid_ask else None
        volume = raw.volume if supports_volume else None
        mid = (
            (bid + ask) / 2
            if bid is not None and ask is not None
            else bid
            if bid is not None
            else ask
            if ask is not None
            else raw.last
        )
        contract = OptionContract(
            underlying=raw.underlying,
            expiration=raw.expiration,
            strike=raw.strike,
            call_put=raw.call_put,
            contract_multiplier=raw.contract_multiplier,
            bid=bid,
            ask=ask,
            mid=mid,
            last=raw.last,
            volume=volume,
            open_interest=raw.open_interest,
            iv=raw.iv,
            delta=raw.delta,
            gamma=raw.gamma,
            theta=raw.theta,
            vega=raw.vega,
            quote_timestamp=raw.quote_timestamp,
            trade_timestamp=raw.trade_timestamp,
            oi_as_of=raw.oi_as_of,
            greeks_source=raw.greeks_source,
            iv_source=raw.iv_source,
            adjusted=raw.adjusted,
            adjustment_reason=raw.adjustment_reason,
            bid_size=raw.bid_size if supports_bid_ask else None,
            ask_size=raw.ask_size if supports_bid_ask else None,
        )
        return replace(contract, quality=self._quote_quality(contract, snapshot))

    def _quote_quality(
        self, contract: OptionContract, snapshot: OptionChainEvent
    ) -> OptionQuoteQuality:
        flags: list[str] = []
        penalties = 0.0
        if contract.bid == 0:
            flags.append("zero_bid")
            penalties += 0.12
        if contract.volume == 0:
            flags.append("zero_volume")
            penalties += 0.10
        elif (
            contract.volume is not None
            and contract.volume < self.config.volatility.min_volume
        ):
            flags.append("low_volume")
            penalties += 0.10
        if (
            contract.open_interest is not None
            and contract.open_interest < self.config.volatility.min_open_interest
        ):
            flags.append("low_open_interest")
            penalties += 0.10
        if contract.bid is None or contract.ask is None:
            flags.append("missing_bid_ask")
            penalties += 0.15
        elif contract.ask > 0:
            mid = (contract.bid + contract.ask) / 2
            if (
                mid > 0
                and (contract.ask - contract.bid) / mid
                > self.config.volatility.max_relative_spread
            ):
                flags.append("wide_spread")
                penalties += 0.25
        if contract.quote_timestamp is None:
            flags.append("missing_quote_timestamp")
            penalties += 0.10
        else:
            age_seconds = abs(
                (snapshot.timestamp - contract.quote_timestamp).total_seconds()
            )
            if age_seconds > self.config.volatility.max_timestamp_skew.total_seconds():
                flags.append("timestamp_skew")
                penalties += 0.12
            if age_seconds > self.config.options.max_quote_age.total_seconds() / 2:
                flags.append("stale_quote")
                penalties += 0.20
        if contract.bid_size == 0 or contract.ask_size == 0:
            flags.append("zero_quote_size")
            penalties += 0.08
        confidence = max(0.0, min(1.0, 1.0 - penalties))
        if not flags:
            status = OptionQualityStatus.HIGH_CONFIDENCE
        elif confidence >= 0.75:
            status = OptionQualityStatus.VALID
        else:
            status = OptionQualityStatus.LOW_CONFIDENCE
        return OptionQuoteQuality(True, status, confidence, tuple(flags))


@dataclass(frozen=True, slots=True)
class Greeks:
    price: float
    delta: float
    gamma: float
    theta: float
    vega: float


class EuropeanBlackScholes:
    def __init__(self, config: OptionsConfig | AnalyticsConfig | None = None) -> None:
        if config is None:
            config = OptionsConfig()
        if isinstance(config, AnalyticsConfig):
            session = config.session
            config = config.options
        else:
            session = SessionConfig()
        self.config = config
        self.session = session

    def greeks(
        self,
        spot: float,
        contract: OptionContract,
        volatility: float,
        as_of: datetime,
    ) -> Greeks:
        _require_utc(as_of, "as_of")
        if spot <= 0 or volatility <= 0:
            raise ValueError("spot and volatility must be positive")
        time_to_expiry = self._time_to_expiry(contract.expiration, as_of)
        if time_to_expiry <= 0:
            raise ValueError("option is expired")
        rate = self.config.risk_free_rate
        dividend = self.config.dividend_yield
        root_time = sqrt(time_to_expiry)
        d1 = (
            log(spot / contract.strike)
            + (rate - dividend + 0.5 * volatility**2) * time_to_expiry
        ) / (volatility * root_time)
        d2 = d1 - volatility * root_time
        discount_rate = exp(-rate * time_to_expiry)
        discount_dividend = exp(-dividend * time_to_expiry)
        nd1 = _NORMAL.cdf(d1)
        nd2 = _NORMAL.cdf(d2)
        if contract.call_put is CallPut.CALL:
            price = (
                spot * discount_dividend * nd1 - contract.strike * discount_rate * nd2
            )
            delta = discount_dividend * nd1
            theta = (
                -spot
                * discount_dividend
                * _NORMAL.pdf(d1)
                * volatility
                / (2 * root_time)
                - rate * contract.strike * discount_rate * nd2
                + dividend * spot * discount_dividend * nd1
            )
        else:
            price = contract.strike * discount_rate * _NORMAL.cdf(
                -d2
            ) - spot * discount_dividend * _NORMAL.cdf(-d1)
            delta = discount_dividend * (nd1 - 1)
            theta = (
                -spot
                * discount_dividend
                * _NORMAL.pdf(d1)
                * volatility
                / (2 * root_time)
                + rate * contract.strike * discount_rate * _NORMAL.cdf(-d2)
                - dividend * spot * discount_dividend * _NORMAL.cdf(-d1)
            )
        gamma = discount_dividend * _NORMAL.pdf(d1) / (spot * volatility * root_time)
        vega = spot * discount_dividend * _NORMAL.pdf(d1) * root_time
        return Greeks(price, delta, gamma, theta, vega)

    def implied_volatility(
        self, spot: float, contract: OptionContract, as_of: datetime
    ) -> float | None:
        target = contract.mid if contract.mid is not None else contract.last
        if target is None or target <= 0:
            return None
        low = self.config.min_iv
        high = self.config.max_iv
        try:
            low_price = self.greeks(spot, contract, low, as_of).price
            high_price = self.greeks(spot, contract, high, as_of).price
        except ValueError:
            return None
        if target < low_price or target > high_price:
            return None
        for _ in range(100):
            midpoint = (low + high) / 2
            model_price = self.greeks(spot, contract, midpoint, as_of).price
            if model_price < target:
                low = midpoint
            else:
                high = midpoint
        return (low + high) / 2

    def _time_to_expiry(self, expiration: date, as_of: datetime) -> float:
        expiry = datetime.combine(
            expiration,
            self.session.rth_end,
            tzinfo=ZoneInfo(self.session.timezone),
        ).astimezone(UTC)
        return (expiry - as_of).total_seconds() / (365.0 * 24 * 60 * 60)


@dataclass(frozen=True, slots=True)
class IVSurfaceSnapshot:
    by_expiration: dict[date, dict[tuple[float, CallPut], MetricResult[float]]]
    atm_iv: MetricResult[float]
    skew: dict[date, MetricResult[float]]
    slope: dict[date, MetricResult[float]]
    curvature: dict[date, MetricResult[float]]
    anomalies: dict[tuple[date, float, CallPut], MetricResult[float]]
    heatmap: dict[tuple[date, float, CallPut], float]
    liquidity_quality: MetricResult[float] | None = None
    iv_change: dict[tuple[date, float, CallPut], MetricResult[float]] = field(
        default_factory=dict
    )
    quote_quality: dict[tuple[date, float, CallPut], MetricResult[float]] = field(
        default_factory=dict
    )
    liquidity_components: dict[tuple[date, float, CallPut], dict[str, float]] = field(
        default_factory=dict
    )
    rejections: tuple[OptionRejection, ...] = ()


class IVSurfaceAnalyzer:
    def __init__(self, config: AnalyticsConfig) -> None:
        self.config = config
        self.normalizer = OptionChainNormalizer(config)
        self.black_scholes = EuropeanBlackScholes(config)
        self._previous_iv: dict[tuple[str, date, float, CallPut], float] = {}

    def analyze(
        self,
        chain: NormalizedOptionChain | OptionChainEvent,
        spot: float,
        as_of: datetime,
        *,
        supports_iv: bool = True,
        capabilities: CapabilityRegistry | None = None,
    ) -> IVSurfaceSnapshot:
        _require_utc(as_of, "as_of")
        if spot <= 0 or not isfinite(spot):
            raise ValueError("spot must be positive and finite")
        if isinstance(chain, OptionChainEvent):
            normalized = self.normalizer.normalize(chain, capabilities=capabilities)
        else:
            normalized = chain
        context_age = as_of - normalized.timestamp
        if context_age > self.config.options.max_quote_age:
            return self._empty_snapshot(
                as_of, normalized, "option chain underlying context is stale"
            )
        if context_age.total_seconds() < 0:
            return self._empty_snapshot(
                as_of, normalized, "option chain timestamp is after analysis time"
            )
        if not supports_iv:
            quote_quality, liquidity_quality, liquidity_components = (
                self._quality_outputs(normalized, as_of)
            )
            unavailable = self._unavailable(
                as_of, normalized, "IV capability is unsupported"
            )
            return IVSurfaceSnapshot(
                by_expiration={},
                atm_iv=unavailable,
                skew={},
                slope={},
                curvature={},
                anomalies={},
                heatmap={},
                liquidity_quality=liquidity_quality,
                quote_quality=quote_quality,
                liquidity_components=liquidity_components,
                rejections=normalized.rejected,
            )
        by_expiration: dict[date, dict[tuple[float, CallPut], MetricResult[float]]] = {}
        for contract in normalized.accepted:
            result = self._contract_iv(contract, spot, as_of, normalized)
            by_expiration.setdefault(contract.expiration, {})[
                (contract.strike, contract.call_put)
            ] = result
        valid: list[tuple[date, float, CallPut, MetricResult[float], float]] = []
        for expiration, strikes in by_expiration.items():
            for (strike, call_put), result in strikes.items():
                if result.value is not None:
                    valid.append((expiration, strike, call_put, result, result.value))
        iv_change = self._iv_changes(normalized, valid, as_of)
        quote_quality, liquidity_quality, liquidity_components = self._quality_outputs(
            normalized, as_of
        )
        if not valid:
            unavailable = self._unavailable(
                as_of, normalized, "no valid implied volatility"
            )
            return IVSurfaceSnapshot(
                by_expiration=by_expiration,
                atm_iv=unavailable,
                skew={},
                slope={},
                curvature={},
                anomalies={},
                heatmap={},
                liquidity_quality=liquidity_quality,
                iv_change=iv_change,
                quote_quality=quote_quality,
                liquidity_components=liquidity_components,
                rejections=normalized.rejected,
            )
        _, _, _, atm_iv, _ = min(
            valid,
            key=lambda item: (abs(item[1] - spot), item[1], item[2].value),
        )
        skew: dict[date, MetricResult[float]] = {}
        slope: dict[date, MetricResult[float]] = {}
        curvature: dict[date, MetricResult[float]] = {}
        for expiration, strikes in by_expiration.items():
            valid_strikes = sorted(
                (strike, call_put, result.value)
                for (strike, call_put), result in strikes.items()
                if result.value is not None
            )
            if len(valid_strikes) < 2:
                unavailable = self._unavailable(
                    as_of, normalized, "fewer than two valid strikes"
                )
                skew[expiration] = unavailable
                slope[expiration] = unavailable
                curvature[expiration] = unavailable
                continue
            skew[expiration] = self._metric(
                valid_strikes[-1][2] - valid_strikes[0][2],
                as_of,
                normalized,
                "highest-strike IV minus lowest-strike IV",
            )
            slope[expiration] = self._metric(
                _linear_slope(
                    [strike for strike, _, _ in valid_strikes],
                    [iv for _, _, iv in valid_strikes],
                ),
                as_of,
                normalized,
                "linear IV slope by strike",
            )
            if len(valid_strikes) < 3:
                curvature[expiration] = self._unavailable(
                    as_of, normalized, "fewer than three valid strikes"
                )
            else:
                curvature[expiration] = self._metric(
                    _average_second_difference([iv for _, _, iv in valid_strikes]),
                    as_of,
                    normalized,
                    "average second difference of IV by ordered strike",
                )
        all_values = [value for _, _, _, _, value in valid]
        median_iv = median(all_values)
        mad = median([abs(value - median_iv) for value in all_values])
        scale = 1.4826 * mad
        anomalies: dict[tuple[date, float, CallPut], MetricResult[float]] = {}
        heatmap: dict[tuple[date, float, CallPut], float] = {}
        for expiration, strike, call_put, _, value in valid:
            score = abs(value - median_iv) / scale if scale else 0.0
            key = (expiration, strike, call_put)
            anomalies[key] = self._metric(
                score,
                as_of,
                normalized,
                "absolute IV deviation from robust median divided by MAD scale",
            )
            heatmap[key] = value
        return IVSurfaceSnapshot(
            by_expiration=by_expiration,
            atm_iv=atm_iv,
            skew=skew,
            slope=slope,
            curvature=curvature,
            anomalies=anomalies,
            heatmap=heatmap,
            liquidity_quality=liquidity_quality,
            iv_change=iv_change,
            quote_quality=quote_quality,
            liquidity_components=liquidity_components,
            rejections=normalized.rejected,
        )

    def _iv_changes(
        self,
        chain: NormalizedOptionChain,
        valid: list[tuple[date, float, CallPut, MetricResult[float], float]],
        as_of: datetime,
    ) -> dict[tuple[date, float, CallPut], MetricResult[float]]:
        result: dict[tuple[date, float, CallPut], MetricResult[float]] = {}
        for expiration, strike, call_put, _, value in valid:
            key = (expiration, strike, call_put)
            previous = self._previous_iv.get((chain.symbol, *key))
            result[key] = (
                self._unavailable(as_of, chain, "no previous IV observation")
                if previous is None
                else self._metric(
                    value - previous,
                    as_of,
                    chain,
                    "current IV minus previous observation for the same contract",
                )
            )
            self._previous_iv[(chain.symbol, *key)] = value
        return result

    def _quality_outputs(
        self, chain: NormalizedOptionChain, as_of: datetime
    ) -> tuple[
        dict[tuple[date, float, CallPut], MetricResult[float]],
        MetricResult[float] | None,
        dict[tuple[date, float, CallPut], dict[str, float]],
    ]:
        quote_quality: dict[tuple[date, float, CallPut], MetricResult[float]] = {}
        liquidity_components: dict[tuple[date, float, CallPut], dict[str, float]] = {}
        liquidity_scores: list[float] = []
        liquidity_statuses: list[MetricStatus] = []
        for contract in chain.accepted:
            key = (contract.expiration, contract.strike, contract.call_put)
            quality, components = self._quote_quality(contract, as_of, chain)
            quote_quality[key] = quality
            liquidity_components[key] = components
            if quality.value is None:
                continue
            volume_score = (
                min(100.0, contract.volume * 10.0)
                if contract.volume is not None
                else 50.0
            )
            oi_score = (
                min(100.0, contract.open_interest)
                if contract.open_interest is not None
                else 50.0
            )
            status = quality.metadata.status
            if contract.volume is None or contract.open_interest is None:
                status = MetricStatus.DEGRADED
            score = quality.value * 0.5 + volume_score * 0.25 + oi_score * 0.25
            components.update(
                volume_score=volume_score,
                open_interest_score=oi_score,
                liquidity_score=score,
            )
            liquidity_scores.append(score)
            liquidity_statuses.append(status)
        if not liquidity_scores:
            liquidity = self._unavailable(
                as_of, chain, "no usable option quote for liquidity quality"
            )
        else:
            status = (
                MetricStatus.OK
                if all(item is MetricStatus.OK for item in liquidity_statuses)
                else MetricStatus.DEGRADED
            )
            reason = (
                None
                if status is MetricStatus.OK
                else "one or more liquidity inputs are incomplete or degraded"
            )
            liquidity = self._metric(
                sum(liquidity_scores) / len(liquidity_scores),
                as_of,
                chain,
                "weighted quote, volume, and open-interest liquidity quality",
                status=status,
                reason=reason,
            )
        return quote_quality, liquidity, liquidity_components

    def _quote_quality(
        self,
        contract: OptionContract,
        as_of: datetime,
        chain: NormalizedOptionChain,
    ) -> tuple[MetricResult[float], dict[str, float]]:
        components: dict[str, float] = {
            "has_quote": 0.0,
            "spread_bps": 0.0,
            "quote_age_seconds": 0.0,
            "bid_size": contract.bid_size or 0.0,
            "ask_size": contract.ask_size or 0.0,
            "locked": 0.0,
        }
        if (
            contract.bid is None
            or contract.ask is None
            or contract.mid is None
            or contract.mid <= 0
        ):
            return self._unavailable(
                as_of, chain, "bid/ask quote is missing"
            ), components
        components["has_quote"] = 1.0
        spread_bps = (contract.ask - contract.bid) / contract.mid * 10_000
        components["spread_bps"] = spread_bps
        locked = contract.bid == contract.ask
        components["locked"] = float(locked)
        if contract.quote_timestamp is None:
            return (
                self._metric(
                    50.0,
                    as_of,
                    chain,
                    "quote quality with missing quote timestamp",
                    provenance=Provenance.OBSERVED,
                    status=MetricStatus.DEGRADED,
                    quality=50.0,
                    reason="quote timestamp is missing",
                ),
                components,
            )
        age = as_of - contract.quote_timestamp
        if age.total_seconds() < 0:
            return self._unavailable(
                as_of, chain, "quote timestamp is after analysis time"
            ), components
        age_seconds = age.total_seconds()
        components["quote_age_seconds"] = age_seconds
        max_age = max(self.config.options.max_quote_age.total_seconds(), 1.0)
        age_score = max(0.0, 100.0 * (1.0 - age_seconds / max_age))
        spread_score = 100.0 / (1.0 + max(spread_bps, 0.0) / 10.0)
        if contract.bid_size is None or contract.ask_size is None:
            size_score = 50.0
            reason: str | None = "quote size is missing"
            status = MetricStatus.DEGRADED
        else:
            total_size = contract.bid_size + contract.ask_size
            size_score = min(100.0, total_size / 20.0 * 100.0)
            reason = "quote size is zero" if total_size == 0 else None
            status = MetricStatus.DEGRADED if total_size == 0 else MetricStatus.OK
        score = spread_score * 0.5 + age_score * 0.3 + size_score * 0.2
        if locked:
            score *= 0.5
            status = MetricStatus.DEGRADED
            reason = "quote is locked"
        elif age_seconds > max_age / 2:
            status = MetricStatus.DEGRADED
            reason = "quote is aging"
        components.update(
            spread_score=spread_score,
            age_score=age_score,
            size_score=size_score,
        )
        return (
            self._metric(
                score,
                as_of,
                chain,
                "quote quality from spread, age, displayed size, and lock state",
                provenance=Provenance.OBSERVED,
                status=status,
                quality=score,
                reason=reason,
            ),
            components,
        )

    def _empty_snapshot(
        self, as_of: datetime, chain: NormalizedOptionChain, reason: str
    ) -> IVSurfaceSnapshot:
        unavailable = self._unavailable(as_of, chain, reason)
        return IVSurfaceSnapshot(
            by_expiration={},
            atm_iv=unavailable,
            skew={},
            slope={},
            curvature={},
            anomalies={},
            heatmap={},
            liquidity_quality=unavailable,
            rejections=chain.rejected,
        )

    def _contract_iv(
        self,
        contract: OptionContract,
        spot: float,
        as_of: datetime,
        chain: NormalizedOptionChain,
    ) -> MetricResult[float]:
        if contract.iv is not None:
            quality = contract.quality.confidence * 100.0
            return self._metric(
                contract.iv,
                as_of,
                chain,
                "provider-supplied implied volatility",
                provenance=Provenance.OBSERVED,
                quality=quality,
                status=(
                    MetricStatus.OK
                    if contract.quality.status
                    in {OptionQualityStatus.HIGH_CONFIDENCE, OptionQualityStatus.VALID}
                    else MetricStatus.DEGRADED
                ),
                reason=(
                    None
                    if not contract.quality.flags
                    else "option quote quality flags: "
                    + ", ".join(contract.quality.flags)
                ),
            )
        if self.config.options.option_model is None:
            return self._unavailable(as_of, chain, "IV model is disabled")
        volatility = self.black_scholes.implied_volatility(spot, contract, as_of)
        if volatility is None:
            return self._unavailable(as_of, chain, "unable to solve implied volatility")
        return self._metric(
            volatility,
            as_of,
            chain,
            "European Black-Scholes bisection IV; early exercise is not modeled",
            provenance=Provenance.APPROXIMATE,
            quality=70.0,
        )

    def _metric(
        self,
        value: float,
        as_of: datetime,
        chain: NormalizedOptionChain,
        methodology: str,
        *,
        provenance: Provenance = Provenance.DERIVED_FROM_OBSERVED,
        quality: float = 100.0,
        status: MetricStatus = MetricStatus.OK,
        reason: str | None = None,
    ) -> MetricResult[float]:
        return MetricResult(
            value,
            MetricMetadata(
                as_of=as_of,
                provider=chain.provider,
                dataset=chain.dataset,
                venue_scope="",
                status=status,
                methodology=methodology,
                quality_score=quality,
                observed_or_modeled=provenance,
                reason=reason,
            ),
        )

    def _unavailable(
        self, as_of: datetime, chain: NormalizedOptionChain, reason: str
    ) -> MetricResult[float]:
        return MetricResult(
            None,
            MetricMetadata.unavailable(
                as_of=as_of,
                provider=chain.provider,
                dataset=chain.dataset,
                venue_scope="",
                reason=reason,
            ),
        )


def _linear_slope(x_values: list[float], y_values: list[float]) -> float:
    if len(x_values) < 2 or len(set(x_values)) < 2:
        return 0.0
    return linear_regression(x_values, y_values).slope


def _average_second_difference(values: list[float]) -> float:
    differences = [
        values[index + 2] - 2 * values[index + 1] + values[index]
        for index in range(len(values) - 2)
    ]
    return sum(differences) / len(differences)
