"""Unified statistical and market-structure price levels."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from math import isfinite, sqrt
from typing import Any, Protocol

from .config import AnalyticsConfig
from .models import (
    InstrumentSpec,
    MetricMetadata,
    MetricResult,
    MetricStatus,
    Provenance,
    Side,
    _require_utc,
)


class LevelFamily(StrEnum):
    DEALER_POSITIONING = "dealer_positioning"
    OPTIONS = "options"
    ORDER_FLOW = "order_flow"
    PRICE_STRUCTURE = "price_structure"
    STATISTICAL = "statistical"
    VOLUME_STRUCTURE = "volume_structure"
    VWAP = "vwap"


class LevelDirection(StrEnum):
    SUPPORT = "support"
    RESISTANCE = "resistance"
    NEUTRAL = "neutral"


class HorizonUnit(StrEnum):
    CALENDAR_DAYS = "calendar_days"
    TRADING_SESSIONS = "trading_sessions"
    INTRADAY = "intraday"


@dataclass(frozen=True, slots=True)
class Level:
    price: float
    source: str
    subtype: str
    family: LevelFamily
    direction: LevelDirection
    timeframe: str
    horizon: int | None
    horizon_unit: HorizonUnit | None
    strength: float
    valid_from: datetime
    valid_until: datetime | None
    metadata: MetricMetadata
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "family", LevelFamily(self.family))
        object.__setattr__(self, "direction", LevelDirection(self.direction))
        object.__setattr__(
            self,
            "horizon_unit",
            None if self.horizon_unit is None else HorizonUnit(self.horizon_unit),
        )
        if not isfinite(self.price) or self.price <= 0:
            raise ValueError("level price must be positive and finite")
        if not self.source or not self.subtype or not self.timeframe:
            raise ValueError("level source, subtype, and timeframe are required")
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError("level strength must be between zero and one")
        _require_utc(self.valid_from, "level valid_from")
        if self.valid_until is not None:
            _require_utc(self.valid_until, "level valid_until")
            if self.valid_until < self.valid_from:
                raise ValueError("level validity interval is reversed")

    @property
    def confidence(self) -> float:
        """Return the canonical metric quality as a 0-1 confidence value."""
        return self.metadata.quality_score / 100.0


@dataclass(frozen=True, slots=True)
class LevelZone:
    lower: float
    upper: float
    center: float
    direction: LevelDirection
    score: float
    families: tuple[LevelFamily, ...]
    levels: tuple[Level, ...]
    metadata: MetricMetadata

    def __post_init__(self) -> None:
        object.__setattr__(self, "direction", LevelDirection(self.direction))
        object.__setattr__(
            self, "families", tuple(LevelFamily(family) for family in self.families)
        )
        object.__setattr__(self, "levels", tuple(self.levels))
        if not all(
            isfinite(value) and value > 0
            for value in (self.lower, self.upper, self.center)
        ):
            raise ValueError("level-zone prices must be positive and finite")
        if self.lower > self.upper or not self.lower <= self.center <= self.upper:
            raise ValueError("level-zone price bounds are invalid")
        if not 0.0 <= self.score <= 100.0:
            raise ValueError("level-zone score must be between zero and one hundred")


@dataclass(frozen=True, slots=True)
class LevelContext:
    instrument: InstrumentSpec
    spot: float
    as_of: datetime
    volatility: Any = None
    vwap: Any = None
    profiles: Mapping[str, Any] = field(default_factory=dict)
    positioning: Any = None
    dom: Any = None
    flow: Any = None
    config: AnalyticsConfig = field(default_factory=AnalyticsConfig)

    def __post_init__(self) -> None:
        _require_utc(self.as_of, "level context as_of")
        if not isfinite(self.spot) or self.spot <= 0:
            raise ValueError("level context spot must be positive and finite")


@dataclass(frozen=True, slots=True)
class LevelAnalysis:
    levels: tuple[Level, ...]
    zones: tuple[LevelZone, ...]


class LevelProvider(Protocol):
    def calculate(self, context: LevelContext) -> tuple[Level, ...]: ...


class IVBandLevelProvider:
    def __init__(self, horizon_days: int) -> None:
        if horizon_days <= 0:
            raise ValueError("IV band horizon must be positive")
        self.horizon_days = horizon_days

    def calculate(self, context: LevelContext) -> tuple[Level, ...]:
        state = context.volatility
        if state is None:
            return ()
        iv_result = state.implied_by_horizon.get(self.horizon_days)
        if iv_result is None or iv_result.value is None:
            return ()
        levels: list[Level] = []
        for sigma in context.config.levels.expected_move_sigmas:
            move = (
                context.spot * iv_result.value * sqrt(self.horizon_days / 365.0) * sigma
            )
            strength = min(1.0, 0.75 / sigma)
            levels.extend(
                (
                    _make_level(
                        context,
                        context.spot + move,
                        "iv_band",
                        f"{sigma}sigma_upper",
                        LevelFamily.OPTIONS,
                        LevelDirection.RESISTANCE,
                        strength,
                        iv_result.metadata,
                        {"sigma": sigma, "unit": "calendar_days"},
                        self.horizon_days,
                        HorizonUnit.CALENDAR_DAYS,
                    ),
                    _make_level(
                        context,
                        max(context.instrument.tick_size, context.spot - move),
                        "iv_band",
                        f"{sigma}sigma_lower",
                        LevelFamily.OPTIONS,
                        LevelDirection.SUPPORT,
                        strength,
                        iv_result.metadata,
                        {"sigma": sigma, "unit": "calendar_days"},
                        self.horizon_days,
                        HorizonUnit.CALENDAR_DAYS,
                    ),
                )
            )
        return tuple(levels)


class RealizedVolatilityBandProvider:
    def __init__(self, window_sessions: int) -> None:
        if window_sessions <= 1:
            raise ValueError("realized-volatility window must be greater than one")
        self.window_sessions = window_sessions

    def calculate(self, context: LevelContext) -> tuple[Level, ...]:
        state = context.volatility
        if state is None:
            return ()
        rv_result = state.realized_by_window.get(self.window_sessions)
        if rv_result is None or rv_result.value is None:
            return ()
        levels: list[Level] = []
        for sigma in context.config.levels.expected_move_sigmas:
            move = (
                context.spot
                * rv_result.value
                * sqrt(self.window_sessions / 252.0)
                * sigma
            )
            strength = min(1.0, 0.75 / sigma)
            levels.extend(
                (
                    _make_level(
                        context,
                        context.spot + move,
                        "realized_volatility_band",
                        f"{sigma}sigma_upper",
                        LevelFamily.STATISTICAL,
                        LevelDirection.RESISTANCE,
                        strength,
                        rv_result.metadata,
                        {"sigma": sigma, "unit": "trading_sessions"},
                        self.window_sessions,
                        HorizonUnit.TRADING_SESSIONS,
                    ),
                    _make_level(
                        context,
                        max(context.instrument.tick_size, context.spot - move),
                        "realized_volatility_band",
                        f"{sigma}sigma_lower",
                        LevelFamily.STATISTICAL,
                        LevelDirection.SUPPORT,
                        strength,
                        rv_result.metadata,
                        {"sigma": sigma, "unit": "trading_sessions"},
                        self.window_sessions,
                        HorizonUnit.TRADING_SESSIONS,
                    ),
                )
            )
        return tuple(levels)


class VWAPBandProvider:
    def calculate(self, context: LevelContext) -> tuple[Level, ...]:
        snapshot = context.vwap
        metrics = getattr(snapshot, "metrics", {})
        levels: list[Level] = []
        for name, metric in metrics.items():
            if not isinstance(metric, MetricResult) or metric.value is None:
                continue
            if name == "session_vwap":
                subtype = name
                strength = 0.85
                direction = LevelDirection.NEUTRAL
            elif name.startswith("vwap_upper_"):
                subtype = name
                strength = 0.55
                direction = LevelDirection.RESISTANCE
            elif name.startswith("vwap_lower_"):
                subtype = name
                strength = 0.55
                direction = LevelDirection.SUPPORT
            else:
                continue
            levels.append(
                _make_level(
                    context,
                    metric.value,
                    "vwap",
                    subtype,
                    LevelFamily.VWAP,
                    direction,
                    strength,
                    metric.metadata,
                    {},
                    None,
                    HorizonUnit.INTRADAY,
                )
            )
        return tuple(levels)


class ProfileLevelProvider:
    def calculate(self, context: LevelContext) -> tuple[Level, ...]:
        levels: list[Level] = []
        for name, snapshot in context.profiles.items():
            metrics = getattr(snapshot, "metrics", {})
            for metric_name, metric in metrics.items():
                if metric_name not in {"tpo_poc", "tpo_vah", "tpo_val", "tpo_midpoint"}:
                    continue
                if metric.value is None:
                    continue
                direction = _profile_direction(metric_name)
                levels.append(
                    _make_level(
                        context,
                        metric.value,
                        "profile",
                        f"{name}_{metric_name}",
                        LevelFamily.VOLUME_STRUCTURE,
                        direction,
                        0.70,
                        metric.metadata,
                        {},
                        None,
                        HorizonUnit.INTRADAY,
                    )
                )
            metadata = getattr(snapshot, "metadata", None)
            if metadata is None:
                continue
            window = getattr(snapshot, "window_sessions", None)
            for field_name, direction, strength in (
                ("vpoc", LevelDirection.NEUTRAL, 0.75),
                ("vah", LevelDirection.RESISTANCE, 0.65),
                ("val", LevelDirection.SUPPORT, 0.65),
            ):
                price = getattr(snapshot, field_name, None)
                if price is None:
                    continue
                levels.append(
                    _make_level(
                        context,
                        price,
                        "volume_profile",
                        f"{name}_{field_name}",
                        LevelFamily.VOLUME_STRUCTURE,
                        direction,
                        strength,
                        metadata,
                        {"window_sessions": window},
                        window,
                        HorizonUnit.TRADING_SESSIONS
                        if window
                        else HorizonUnit.INTRADAY,
                    )
                )
            for field_name, direction, strength in (
                ("hvns", LevelDirection.NEUTRAL, 0.60),
                ("lvns", LevelDirection.NEUTRAL, 0.40),
            ):
                for index, price in enumerate(getattr(snapshot, field_name, ())):
                    levels.append(
                        _make_level(
                            context,
                            price,
                            "volume_profile",
                            f"{name}_{field_name}_{index}",
                            LevelFamily.VOLUME_STRUCTURE,
                            direction,
                            strength,
                            metadata,
                            {"window_sessions": window},
                            window,
                            HorizonUnit.TRADING_SESSIONS
                            if window
                            else HorizonUnit.INTRADAY,
                        )
                    )
        return tuple(levels)


class PositioningLevelProvider:
    def calculate(self, context: LevelContext) -> tuple[Level, ...]:
        snapshot = context.positioning
        if snapshot is None:
            return ()
        levels: list[Level] = []
        for name, metric, direction, strength in (
            (
                "call_wall",
                getattr(snapshot, "call_wall", None),
                LevelDirection.RESISTANCE,
                0.85,
            ),
            (
                "put_wall",
                getattr(snapshot, "put_wall", None),
                LevelDirection.SUPPORT,
                0.85,
            ),
        ):
            if isinstance(metric, MetricResult) and metric.value is not None:
                levels.append(
                    _make_level(
                        context,
                        metric.value,
                        "dealer_positioning",
                        name,
                        LevelFamily.DEALER_POSITIONING,
                        direction,
                        strength,
                        metric.metadata,
                        {},
                        None,
                        HorizonUnit.INTRADAY,
                    )
                )
        for name, flip in (
            ("gamma_flip", getattr(snapshot, "gamma_flip", None)),
            ("dealer_dex_flip", getattr(snapshot, "dealer_dex_flip", None)),
        ):
            root = getattr(flip, "nearest_root", None)
            metadata = getattr(flip, "metadata", None)
            if root is None or metadata is None:
                continue
            levels.append(
                _make_level(
                    context,
                    root.spot,
                    "dealer_positioning",
                    name,
                    LevelFamily.DEALER_POSITIONING,
                    _direction_for_price(root.spot, context.spot),
                    0.80,
                    metadata,
                    {"residual": root.residual},
                    None,
                    HorizonUnit.INTRADAY,
                )
            )
        exposure = getattr(snapshot, "gex_by_strike", {})
        max_exposure = max((abs(value) for value in exposure.values()), default=0.0)
        metadata = getattr(snapshot, "metadata", None)
        if metadata is not None and max_exposure > 0:
            for price, value in sorted(exposure.items()):
                if value == 0:
                    continue
                levels.append(
                    _make_level(
                        context,
                        price,
                        "dealer_positioning",
                        "gamma_concentration",
                        LevelFamily.DEALER_POSITIONING,
                        _direction_for_price(price, context.spot),
                        min(1.0, abs(value) / max_exposure),
                        metadata,
                        {"gex": value},
                        None,
                        HorizonUnit.INTRADAY,
                    )
                )
        return tuple(levels)


class DOMLiquidityLevelProvider:
    def calculate(self, context: LevelContext) -> tuple[Level, ...]:
        snapshot = context.dom
        levels: list[Level] = []
        for wall in getattr(snapshot, "walls", ()):
            levels.append(
                _make_level(
                    context,
                    wall.price,
                    "dom_liquidity",
                    "displayed_liquidity_wall",
                    LevelFamily.PRICE_STRUCTURE,
                    LevelDirection.SUPPORT
                    if wall.side is Side.BID
                    else LevelDirection.RESISTANCE,
                    min(1.0, max(0.0, wall.reliability_score)),
                    wall.metadata,
                    {
                        "reliability_score": wall.reliability_score,
                        "displayed_liquidity_only": True,
                    },
                    None,
                    HorizonUnit.INTRADAY,
                )
            )
        return tuple(levels)


class FlowStructureLevelProvider:
    def calculate(self, context: LevelContext) -> tuple[Level, ...]:
        snapshot = context.flow
        levels: list[Level] = []
        zones = getattr(snapshot, "stacked_imbalances", ()) or getattr(
            snapshot, "diagonal_imbalances", ()
        )
        for zone in zones:
            direction_text = str(zone.direction).lower()
            direction = (
                LevelDirection.SUPPORT
                if direction_text in {"buy", "bullish", "below"}
                else LevelDirection.RESISTANCE
            )
            strength = min(1.0, max(0.0, zone.number_of_levels / 5.0))
            levels.append(
                _make_level(
                    context,
                    (zone.price_low + zone.price_high) / 2.0,
                    "order_flow",
                    "imbalance_zone",
                    LevelFamily.ORDER_FLOW,
                    direction,
                    strength,
                    zone.metadata,
                    {
                        "price_low": zone.price_low,
                        "price_high": zone.price_high,
                        "ratio": zone.ratio,
                    },
                    None,
                    HorizonUnit.INTRADAY,
                )
            )
        return tuple(levels)


class LevelEngine:
    def __init__(
        self,
        config: AnalyticsConfig,
        providers: Iterable[LevelProvider] | None = None,
    ) -> None:
        self.config = config
        self.providers = (
            tuple(providers)
            if providers is not None
            else (
                IVBandLevelProvider(
                    14
                    if 14 in config.volatility.implied_horizons_days
                    else config.volatility.implied_horizons_days[0]
                ),
                RealizedVolatilityBandProvider(
                    20
                    if 20 in config.volatility.realized_windows_sessions
                    else config.volatility.realized_windows_sessions[0]
                ),
                VWAPBandProvider(),
                ProfileLevelProvider(),
                PositioningLevelProvider(),
                DOMLiquidityLevelProvider(),
                FlowStructureLevelProvider(),
            )
        )

    def calculate(self, context: LevelContext) -> LevelAnalysis:
        levels = tuple(
            sorted(
                (
                    level
                    for provider in self.providers
                    for level in provider.calculate(context)
                    if level.valid_until is None or level.valid_until >= context.as_of
                ),
                key=lambda level: (level.price, level.source, level.subtype),
            )
        )
        return LevelAnalysis(levels, self._zones(levels, context))

    def _zones(
        self, levels: tuple[Level, ...], context: LevelContext
    ) -> tuple[LevelZone, ...]:
        if not levels:
            return ()
        tolerance = max(
            context.instrument.tick_size * self.config.levels.cluster_tolerance_ticks,
            context.spot * self.config.levels.cluster_tolerance_bps / 10_000.0,
            (context.instrument.atr or 0.0) * self.config.levels.cluster_atr_fraction,
        )
        clusters: list[list[Level]] = []
        for level in levels:
            if not clusters:
                clusters.append([level])
                continue
            current = clusters[-1]
            center = _weighted_center(current)
            if abs(level.price - center) <= tolerance:
                current.append(level)
            else:
                clusters.append([level])
        zones = [self._zone(cluster, context) for cluster in clusters]
        zones.sort(
            key=lambda zone: (-zone.score, abs(zone.center - context.spot), zone.center)
        )
        return tuple(zones[: self.config.levels.max_zones])

    def _zone(self, levels: list[Level], context: LevelContext) -> LevelZone:
        families = tuple(
            sorted({level.family for level in levels}, key=lambda family: family.value)
        )
        direction_values = {level.direction for level in levels}
        direction = (
            next(iter(direction_values))
            if len(direction_values) == 1
            else LevelDirection.NEUTRAL
        )
        family_strength = sum(
            min(
                self.config.levels.same_family_strength_cap,
                sum(level.strength for level in levels if level.family is family),
            )
            for family in families
        )
        capacity = self.config.levels.same_family_strength_cap * max(1, len(families))
        diversity = min(
            1.0, len(families) / self.config.levels.min_independent_families
        )
        total_strength = sum(level.strength for level in levels)
        quality = (
            sum(level.strength * level.confidence for level in levels) / total_strength
            if total_strength
            else 0.0
        )
        score = 100.0 * (
            0.45 * min(1.0, family_strength / capacity)
            + 0.35 * diversity
            + 0.20 * quality
        )
        quality_score = quality * 100.0
        status = (
            MetricStatus.OK
            if all(level.metadata.status is MetricStatus.OK for level in levels)
            else MetricStatus.DEGRADED
        )
        metadata = MetricMetadata(
            as_of=context.as_of,
            provider="analytics",
            dataset="level_zone",
            venue_scope=context.instrument.venue,
            status=status,
            methodology="volatility-normalized family-capped level confluence",
            quality_score=quality_score,
            observed_or_modeled=Provenance.DERIVED_FROM_OBSERVED,
            reason=None
            if status is MetricStatus.OK
            else "one or more contributing levels are degraded",
        )
        lower = min(level.price for level in levels)
        upper = max(level.price for level in levels)
        center = min(upper, max(lower, _weighted_center(levels)))
        return LevelZone(
            lower,
            upper,
            center,
            direction,
            score,
            families,
            tuple(levels),
            metadata,
        )


def _make_level(
    context: LevelContext,
    price: float,
    source: str,
    subtype: str,
    family: LevelFamily,
    direction: LevelDirection,
    strength: float,
    metadata: MetricMetadata,
    details: Mapping[str, Any],
    horizon: int | None,
    horizon_unit: HorizonUnit | None,
) -> Level:
    return Level(
        price=price,
        source=source,
        subtype=subtype,
        family=family,
        direction=direction,
        timeframe=horizon_unit.value if horizon_unit is not None else "intraday",
        horizon=horizon,
        horizon_unit=horizon_unit,
        strength=max(0.0, min(1.0, strength)),
        valid_from=metadata.as_of,
        valid_until=None,
        metadata=metadata,
        details=dict(details),
    )


def _direction_for_price(price: float, spot: float) -> LevelDirection:
    if price < spot:
        return LevelDirection.SUPPORT
    if price > spot:
        return LevelDirection.RESISTANCE
    return LevelDirection.NEUTRAL


def _profile_direction(name: str) -> LevelDirection:
    if name.endswith(("_val", "_low")):
        return LevelDirection.SUPPORT
    if name.endswith(("_vah", "_high")):
        return LevelDirection.RESISTANCE
    return LevelDirection.NEUTRAL


def _weighted_center(levels: list[Level]) -> float:
    total = sum(max(level.strength, 0.01) for level in levels)
    return sum(level.price * max(level.strength, 0.01) for level in levels) / total
