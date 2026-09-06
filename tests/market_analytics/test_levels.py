from dataclasses import dataclass

import pytest

from stock_analysis.market_analytics.config import AnalyticsConfig
from stock_analysis.market_analytics.levels import (
    IVBandLevelProvider,
    Level,
    LevelContext,
    LevelDirection,
    LevelEngine,
    LevelFamily,
    RealizedVolatilityBandProvider,
)
from stock_analysis.market_analytics.models import (
    InstrumentSpec,
    MetricMetadata,
    Provenance,
)
from stock_analysis.market_analytics.volatility import VolatilityEngine
from tests.market_analytics.support import T0
from tests.market_analytics.test_volatility import _two_expiration_chain


def _context(*, volatility=None, spot=100.0):
    return LevelContext(
        instrument=InstrumentSpec("AAA", "XNAS", 0.05, 2),
        spot=spot,
        as_of=T0,
        volatility=volatility,
    )


def _metadata(quality=100.0):
    return MetricMetadata(
        as_of=T0,
        provider="fixture",
        dataset="levels",
        venue_scope="XNAS",
        quality_score=quality,
        observed_or_modeled=Provenance.DERIVED_FROM_OBSERVED,
    )


def test_iv_bands_use_calendar_day_expected_move_and_keep_direction_structural():
    state = VolatilityEngine(AnalyticsConfig()).analyze(
        _two_expiration_chain(), 100.0, T0
    )
    levels = IVBandLevelProvider(14).calculate(_context(volatility=state))

    upper = next(
        level
        for level in levels
        if level.direction is LevelDirection.RESISTANCE
        and level.subtype == "1.0sigma_upper"
    )
    expected = 100.0 + 100.0 * state.implied_by_horizon[14].value * (14 / 365) ** 0.5

    assert upper.price == pytest.approx(expected, abs=0.05)
    assert upper.family is LevelFamily.OPTIONS
    assert upper.horizon_unit.value == "calendar_days"
    assert upper.confidence == pytest.approx(1.0)


def test_realized_bands_are_unavailable_without_enough_completed_closes():
    state = VolatilityEngine(AnalyticsConfig()).analyze(None, 100.0, T0)
    levels = RealizedVolatilityBandProvider(20).calculate(_context(volatility=state))

    assert levels == ()


@dataclass(frozen=True)
class _StaticProvider:
    values: tuple[Level, ...]

    def calculate(self, context: LevelContext) -> tuple[Level, ...]:
        return self.values


def _level(price, family, source):
    return Level(
        price=price,
        source=source,
        subtype="test",
        family=family,
        direction=LevelDirection.NEUTRAL,
        timeframe="intraday",
        horizon=None,
        horizon_unit=None,
        strength=0.8,
        valid_from=T0,
        valid_until=None,
        metadata=_metadata(),
    )


def test_confluence_rewards_independent_families_and_caps_same_family_duplicates():
    duplicated = tuple(
        _level(100.0 + index * 0.02, LevelFamily.OPTIONS, f"iv-{index}")
        for index in range(5)
    )
    independent = (
        _level(100.10, LevelFamily.VWAP, "vwap"),
        _level(100.12, LevelFamily.VOLUME_STRUCTURE, "hvn"),
        _level(100.14, LevelFamily.DEALER_POSITIONING, "gamma"),
    )
    engine = LevelEngine(
        AnalyticsConfig(),
        providers=(
            _StaticProvider(duplicated),
            _StaticProvider(independent),
        ),
    )

    result = engine.calculate(_context())

    assert len(result.zones) == 1
    assert result.zones[0].families == (
        LevelFamily.DEALER_POSITIONING,
        LevelFamily.OPTIONS,
        LevelFamily.VOLUME_STRUCTURE,
        LevelFamily.VWAP,
    )
    assert result.zones[0].score > 80.0
    assert result.zones[0].score < 100.0


def test_level_confidence_is_derived_from_metadata_and_not_strength():
    level = Level(
        price=100.0,
        source="gamma",
        subtype="gamma_wall",
        family=LevelFamily.DEALER_POSITIONING,
        direction=LevelDirection.NEUTRAL,
        timeframe="intraday",
        horizon=None,
        horizon_unit=None,
        strength=1.0,
        valid_from=T0,
        valid_until=None,
        metadata=_metadata(quality=35.0),
    )

    assert level.strength == 1.0
    assert level.confidence == pytest.approx(0.35)
