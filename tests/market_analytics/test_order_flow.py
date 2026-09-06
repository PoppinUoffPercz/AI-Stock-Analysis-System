from datetime import timedelta

from stock_analysis.market_analytics.config import AnalyticsConfig
from stock_analysis.market_analytics.models import (
    AggressorSide,
    InstrumentSpec,
    QuoteEvent,
    TradeEvent,
)
from stock_analysis.market_analytics.order_flow import (
    BarSummary,
    FlowDeltaExhaustionDetector,
    FootprintEngine,
)
from tests.market_analytics.support import T0


def test_footprint_uses_explicit_side_and_detects_three_level_diagonal_stack():
    engine = FootprintEngine(InstrumentSpec("AAA", "XNAS", 0.05, 2), AnalyticsConfig())
    for price in (100.00, 100.05, 100.10):
        engine.consume(
            TradeEvent(
                "AAA",
                T0,
                "fixture",
                "trades",
                price,
                30.0,
                AggressorSide.BUY,
                str(price),
            )
        )
        engine.consume(
            TradeEvent(
                "AAA",
                T0,
                "fixture",
                "trades",
                price - 0.05,
                5.0,
                AggressorSide.SELL,
                f"s{price}",
            )
        )

    result = engine.snapshot(T0)
    assert result.flow_delta.value == 75.0
    assert result.cvd.value == 75.0
    assert len(result.stacked_imbalances) == 1
    assert result.stacked_imbalances[0].number_of_levels == 3


def test_quote_fallback_is_derived_and_unknown_trade_does_not_change_delta():
    engine = FootprintEngine(InstrumentSpec("AAA", "XNAS", 0.05, 2), AnalyticsConfig())
    engine.consume(
        TradeEvent("AAA", T0, "fixture", "trades", 100.05, 10.0, None, "buy"),
        QuoteEvent("AAA", T0, "fixture", "quotes", 100.0, 100.05, 20.0, 20.0),
    )
    result = engine.consume(
        TradeEvent("AAA", T0, "fixture", "trades", 100.025, 10.0, None, "unknown"),
        None,
    )

    assert result.flow_delta.value == 10.0
    assert result.quality.value < 100


def test_unclassified_volume_remains_in_total_cell_volume():
    engine = FootprintEngine(InstrumentSpec("AAA", "XNAS", 0.05, 2), AnalyticsConfig())
    engine.consume(
        TradeEvent("AAA", T0, "fixture", "trades", 100.0, 7.0, None, "unknown")
    )

    result = engine.snapshot(T0)

    cell = result.cells[(T0, 100.0)]
    assert cell.total_volume == 7.0
    assert cell.delta == 0.0
    assert result.quality.metadata.status.value == "degraded"


def test_unsupported_trade_side_is_not_claimed_as_observed():
    engine = FootprintEngine(
        InstrumentSpec("AAA", "XNAS", 0.05, 2),
        AnalyticsConfig(),
        supports_trade_side=False,
    )
    result = engine.consume(
        TradeEvent("AAA", T0, "fixture", "trades", 100.0, 7.0, AggressorSide.BUY, "buy")
    )

    cell = result.cells[(T0, 100.0)]
    assert cell.ask_aggressor_volume == 0.0
    assert cell.bid_aggressor_volume == 0.0
    assert cell.total_volume == 7.0
    assert result.flow_delta.value == 0.0
    assert result.quality.metadata.status.value == "degraded"


def test_buying_move_with_stalling_cvd_emits_bearish_exhaustion_then_flip():
    detector = FlowDeltaExhaustionDetector(AnalyticsConfig().flow)
    for index, (price, delta) in enumerate(((100, 20), (101, 18), (102, 4), (103, -8))):
        result = detector.update(
            BarSummary(T0 + timedelta(minutes=index), price, delta)
        )

    assert result.bearish_exhaustion_score.value >= 0.5
    assert result.flow_flip is not None
    assert result.flow_flip.direction == "bearish"
