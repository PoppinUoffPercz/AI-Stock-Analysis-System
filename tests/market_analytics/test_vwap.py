from dataclasses import replace

from stock_analysis.market_analytics.config import AnalyticsConfig
from stock_analysis.market_analytics.models import (
    AggressorSide,
    BarEvent,
    Provenance,
    TradeEvent,
    VolumeInputMode,
)
from stock_analysis.market_analytics.vwap import VWAPEngine
from tests.market_analytics.support import ny_utc


def test_exact_vwap_is_hand_calculated_and_resets_at_new_rth_session():
    engine = VWAPEngine(AnalyticsConfig())
    engine.consume_trade(
        TradeEvent(
            "AAA",
            ny_utc(9, 31),
            "fixture",
            "trades",
            100.0,
            2.0,
            AggressorSide.BUY,
            "1",
        )
    )
    result = engine.consume_trade(
        TradeEvent(
            "AAA",
            ny_utc(9, 32),
            "fixture",
            "trades",
            101.0,
            1.0,
            AggressorSide.SELL,
            "2",
        )
    )

    assert result.metrics["session_vwap"].value == (100 * 2 + 101) / 3
    assert (
        result.metrics["session_vwap"].metadata.observed_or_modeled
        is Provenance.DERIVED_FROM_OBSERVED
    )

    next_day = engine.consume_trade(
        TradeEvent(
            "AAA", ny_utc(9, 31, day=3), "fixture", "trades", 110.0, 1.0, None, "3"
        )
    )
    assert next_day.metrics["session_vwap"].value == 110.0


def test_bar_vwap_is_explicitly_approximate():
    config = replace(AnalyticsConfig(), volume_input_mode=VolumeInputMode.BARS)
    result = VWAPEngine(config).consume_bar(
        BarEvent("AAA", ny_utc(10, 0), "fixture", "bars", 99, 101, 98, 100, 10)
    )
    assert (
        result.metrics["session_vwap"].metadata.observed_or_modeled
        is Provenance.APPROXIMATE
    )
