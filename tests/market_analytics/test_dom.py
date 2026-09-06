from dataclasses import replace
from datetime import UTC, datetime, timedelta

from stock_analysis.market_analytics.config import AnalyticsConfig
from stock_analysis.market_analytics.dom import OrderBookState
from stock_analysis.market_analytics.models import (
    AggressorSide,
    BookLevel,
    BookSnapshotEvent,
    InstrumentSpec,
    MetricStatus,
    QuoteEvent,
    Side,
    TradeEvent,
)
from tests.market_analytics.support import T0


def test_dom_snapshot_calculates_obi_and_microprice():
    as_of = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
    levels = tuple(
        [BookLevel(Side.BID, 100.00 - i * 0.05, 10.0 + i) for i in range(5)]
        + [BookLevel(Side.ASK, 100.05 + i * 0.05, 5.0 + i) for i in range(5)]
    )
    state = OrderBookState(InstrumentSpec("AAA", "XNAS", 0.05, 2), AnalyticsConfig())

    snapshot = state.apply(
        BookSnapshotEvent("AAA", as_of, "fixture", "depth", 7, levels)
    )

    assert snapshot.state == "valid"
    assert snapshot.metrics["book_imbalance_l1"].value == (10 - 5) / (10 + 5)
    assert snapshot.metrics["book_imbalance_l5"].value == (60 - 35) / (60 + 35)
    assert snapshot.metrics["midprice"].value == 100.025
    assert snapshot.metrics["microprice"].value == (100.05 * 10 + 100.00 * 5) / 15


def test_dom_sequence_gap_invalidates_until_resnapshot():
    as_of = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
    state = OrderBookState(InstrumentSpec("AAA", "XNAS", 0.05, 2), AnalyticsConfig())
    levels = (BookLevel(Side.BID, 100.0, 10.0), BookLevel(Side.ASK, 100.05, 10.0))
    state.apply(BookSnapshotEvent("AAA", as_of, "fixture", "depth", 7, levels))

    gap = state.apply_modify(as_of, sequence=9, side=Side.BID, price=100.0, size=12.0)
    assert gap.state == "needs_snapshot"
    assert gap.metrics["book_imbalance_l1"].value is None

    recovered = state.apply(
        BookSnapshotEvent("AAA", as_of, "fixture", "depth", 20, levels)
    )
    assert recovered.state == "valid"
    assert recovered.metrics["book_imbalance_l1"].value == 0.0


def make_state(*, wall_min_persistence_ms: int, heatmap_max_observations: int):
    config = replace(
        AnalyticsConfig(),
        dom=replace(
            AnalyticsConfig().dom,
            wall_min_persistence_ms=wall_min_persistence_ms,
            heatmap_max_observations=heatmap_max_observations,
        ),
    )
    return OrderBookState(InstrumentSpec("AAA", "XNAS", 0.05, 2), config)


def snapshot_with_bid_size(price: float, size: float, timestamp=T0):
    return BookSnapshotEvent(
        "AAA",
        timestamp,
        "fixture",
        "depth",
        1,
        (
            BookLevel(Side.BID, price, size),
            BookLevel(Side.ASK, price + 0.05, 10.0),
        ),
    )


def test_wall_requires_persistence_and_heatmap_is_bounded():
    state = make_state(wall_min_persistence_ms=1_000, heatmap_max_observations=2)
    first = state.apply(snapshot_with_bid_size(100.0, 100.0))
    assert first.walls == ()

    state.apply(
        snapshot_with_bid_size(100.0, 100.0),
        as_of=first.as_of + timedelta(seconds=1),
    )
    state.apply(
        snapshot_with_bid_size(100.0, 100.0),
        as_of=first.as_of + timedelta(seconds=2),
    )
    result = state.snapshot(first.as_of + timedelta(seconds=2))

    assert result.walls[0].reliability_score > 0
    assert len(result.heatmap.observations) == 2


def test_quotes_and_trades_do_not_refresh_depth_freshness():
    state = OrderBookState(InstrumentSpec("AAA", "XNAS", 0.05, 2), AnalyticsConfig())
    first = state.apply(snapshot_with_bid_size(100.0, 10.0))
    later = first.as_of + timedelta(seconds=4)

    state.apply(
        QuoteEvent("AAA", later, "fixture", "quotes", 100.0, 100.05, 10.0, 10.0)
    )
    state.apply(
        TradeEvent(
            "AAA",
            later,
            "fixture",
            "trades",
            100.05,
            1.0,
            AggressorSide.BUY,
            "t1",
        )
    )
    at_limit = state.snapshot(first.as_of + timedelta(seconds=5))
    stale = state.snapshot(first.as_of + timedelta(seconds=5.1))

    assert at_limit.state == "valid"
    assert stale.state == "stale"
    assert stale.metrics["book_imbalance_l1"].value is not None
    assert stale.metrics["book_imbalance_l1"].metadata.status is MetricStatus.STALE
