from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from stock_analysis.market_analytics.asof import PointInTimeStore, SnapshotEnvelope
from stock_analysis.market_analytics.models import InstrumentSpec
from stock_analysis.market_analytics.providers import CapabilityRegistry
from tests.market_analytics.support import T0


def _snapshot(
    *,
    revision: str,
    available_minutes: int,
    value: float,
    received_minutes: int | None = None,
):
    observed_at = T0 + timedelta(minutes=1)
    available_at = T0 + timedelta(minutes=available_minutes)
    received_at = T0 + timedelta(
        minutes=received_minutes if received_minutes is not None else available_minutes
    )
    return SnapshotEnvelope(
        symbol="AAA",
        dataset="fundamentals",
        provider="fixture",
        effective_at=T0,
        observed_at=observed_at,
        received_at=received_at,
        available_at=available_at,
        revision_id=revision,
        payload={"value": value},
    )


def test_asof_store_selects_only_revisions_available_by_decision_time(tmp_path):
    store = PointInTimeStore(tmp_path)
    first = _snapshot(revision="r1", available_minutes=2, value=10.0)
    revised = _snapshot(revision="r2", available_minutes=4, value=12.0)
    store.ingest(first)
    store.ingest(revised)

    assert store.as_of("AAA", "fundamentals", T0 + timedelta(minutes=1)) is None
    assert store.as_of("AAA", "fundamentals", T0 + timedelta(minutes=3)) == first
    assert store.as_of("AAA", "fundamentals", T0 + timedelta(minutes=5)) == revised


def test_asof_store_reloads_from_persisted_artifacts(tmp_path):
    first = _snapshot(revision="r1", available_minutes=2, value=10.0)
    PointInTimeStore(tmp_path).ingest(first)

    reloaded = PointInTimeStore(tmp_path).as_of(
        "AAA", "fundamentals", T0 + timedelta(minutes=3)
    )

    assert reloaded == first


def test_receipt_wall_clock_does_not_change_deterministic_snapshot_identity(tmp_path):
    first = _snapshot(
        revision="r1", available_minutes=2, value=10.0, received_minutes=2
    )
    later_receipt = replace(first, received_at=T0 + timedelta(minutes=20))
    store = PointInTimeStore(tmp_path)

    first_ref = store.ingest(first)
    later_ref = store.ingest(later_receipt)

    assert first_ref.identity == later_ref.identity


def test_asof_store_does_not_select_snapshot_before_local_receipt(tmp_path):
    delayed = _snapshot(
        revision="r1", available_minutes=2, value=10.0, received_minutes=20
    )
    store = PointInTimeStore(tmp_path)
    store.ingest(delayed)

    assert store.as_of("AAA", "fundamentals", T0 + timedelta(minutes=3)) is None
    assert store.as_of("AAA", "fundamentals", T0 + timedelta(minutes=21)) == delayed


def test_asof_store_rejects_ambiguous_same_time_revisions(tmp_path):
    store = PointInTimeStore(tmp_path)
    store.ingest(_snapshot(revision="9", available_minutes=2, value=9.0))
    store.ingest(_snapshot(revision="10", available_minutes=2, value=10.0))

    with pytest.raises(ValueError, match="ambiguous"):
        store.as_of("AAA", "fundamentals", T0 + timedelta(minutes=3))


def test_snapshot_envelope_rejects_impossible_provider_timing():
    with pytest.raises(ValueError, match="received_at"):
        replace(
            _snapshot(revision="r1", available_minutes=2, value=10.0),
            received_at=T0,
        )


def test_instrument_has_stable_canonical_identity_without_breaking_symbol_api():
    instrument = InstrumentSpec("AAA", "XNAS", 0.01)

    assert instrument.symbol == "AAA"
    assert instrument.stable_id == "equity:XNAS:AAA:USD"
    assert replace(instrument, instrument_id="FIGI-123").stable_id == "FIGI-123"


def test_capability_registry_exposes_reference_and_streaming_boundaries():
    capabilities = CapabilityRegistry(
        supports_bars=True,
        supports_trades=True,
        supports_bbo=True,
        coverage_scope="consolidated",
        supports_historical=True,
        supports_streaming=False,
        supports_rates=True,
        supports_dividends=True,
    )

    assert capabilities.supports_bars
    assert capabilities.supports_trades
    assert capabilities.coverage_scope == "consolidated"
    assert capabilities.supports_streaming is False
