from datetime import timedelta

import pytest

from stock_analysis.market_analytics.models import TradeEvent
from stock_analysis.market_analytics.providers import CapabilityRegistry
from stock_analysis.market_analytics.replay import ReplayEngine, ReplayProvider
from tests.market_analytics.support import T0


def test_replay_preserves_equal_timestamp_input_order_and_filters_symbol():
    events = [
        TradeEvent("AAA", T0, "fixture", "trades", 100.0, 1.0, None, "first"),
        TradeEvent("BBB", T0, "fixture", "trades", 200.0, 1.0, None, "other"),
        TradeEvent(
            "AAA",
            T0 + timedelta(seconds=1),
            "fixture",
            "trades",
            101.0,
            2.0,
            None,
            "second",
        ),
    ]
    provider = ReplayProvider(
        events, CapabilityRegistry(supports_historical_ticks=True)
    )

    assert [event.trade_id for event in provider.events("AAA")] == ["first", "second"]


def test_replay_engine_rejects_missing_snapshot_consumer_contract():
    provider = ReplayProvider([], CapabilityRegistry())

    with pytest.raises(TypeError, match="consume"):
        ReplayEngine().run(provider, object(), "AAA")
