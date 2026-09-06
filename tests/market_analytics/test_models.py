from datetime import UTC, datetime

import pytest

from stock_analysis.market_analytics.models import (
    InstrumentSpec,
    MetricMetadata,
    MetricResult,
    MetricStatus,
    Provenance,
)


def test_metric_metadata_rejects_naive_as_of_and_out_of_range_quality():
    with pytest.raises(ValueError, match="timezone-aware"):
        MetricMetadata(
            as_of=datetime.fromisoformat("2026-01-01T00:00:00"),
            provider="fixture",
            dataset="trades",
            venue_scope="XNAS",
            quality_score=100,
            observed_or_modeled=Provenance.OBSERVED,
        )

    with pytest.raises(ValueError, match="quality_score"):
        MetricMetadata(
            as_of=datetime(2026, 1, 1, tzinfo=UTC),
            provider="fixture",
            dataset="trades",
            venue_scope="XNAS",
            quality_score=101,
            observed_or_modeled=Provenance.OBSERVED,
        )


def test_instrument_normalizes_prices_to_tick_grid():
    instrument = InstrumentSpec("TEST", "XNAS", tick_size=0.05, price_precision=2)

    assert instrument.price_to_ticks(100.07) == 2001
    assert instrument.ticks_to_price(2001) == 100.05


def test_unavailable_metric_has_no_value_and_explicit_provenance():
    metadata = MetricMetadata.unavailable(
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
        provider="fixture",
        dataset="depth",
        venue_scope="XNAS",
        reason="sequence gap",
    )

    result = MetricResult[float](None, metadata)
    assert result.value is None
    assert result.metadata.status is MetricStatus.UNAVAILABLE
    assert result.metadata.observed_or_modeled is Provenance.UNAVAILABLE
