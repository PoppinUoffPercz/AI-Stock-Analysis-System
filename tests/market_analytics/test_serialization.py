import json

import pytest

from stock_analysis.market_analytics.fixtures import build_full_fixture
from stock_analysis.market_analytics.models import (
    AnalyticsSnapshot,
    MetricStatus,
    Provenance,
)
from stock_analysis.market_analytics.pipeline import AnalyticsPipeline
from stock_analysis.market_analytics.replay import ReplayEngine
from stock_analysis.market_analytics.serialization import from_jsonable, to_jsonable


def run_fixture_to_final_snapshot():
    provider, instrument, config = build_full_fixture()
    pipeline = AnalyticsPipeline(instrument, config, provider.capabilities)
    return ReplayEngine().run(provider, pipeline, instrument.symbol)[-1]


def test_snapshot_json_round_trip_preserves_unavailable_values():
    snapshot = run_fixture_to_final_snapshot()
    restored = from_jsonable(to_jsonable(snapshot), AnalyticsSnapshot)

    assert restored.positioning.net_gex.value == snapshot.positioning.net_gex.value
    assert (
        restored.dom.metrics["book_imbalance_l10"].value
        == snapshot.dom.metrics["book_imbalance_l10"].value
    )
    assert (
        restored.volatility.implied_by_horizon[30].value
        == snapshot.volatility.implied_by_horizon[30].value
    )
    assert restored.features.values == snapshot.features.values
    assert restored.levels == snapshot.levels


def test_snapshot_json_wire_round_trip_preserves_status_and_provenance_types():
    snapshot = run_fixture_to_final_snapshot()

    encoded = json.dumps(to_jsonable(snapshot))
    decoded = json.loads(encoded)
    restored = from_jsonable(decoded, AnalyticsSnapshot)

    assert restored == snapshot

    metadata = restored.dom.metrics["book_imbalance_l10"].metadata
    assert metadata.status is MetricStatus.OK
    assert metadata.observed_or_modeled is Provenance.DERIVED_FROM_OBSERVED
    assert restored.features.metadata["atm_iv_30d"].status is MetricStatus.OK


def test_json_cannot_resolve_classes_outside_analytics():
    with pytest.raises(ValueError, match="unsupported serialized type"):
        from_jsonable(
            {"__type__": "subprocess:Popen", "fields": {"args": ["never-run"]}}
        )
