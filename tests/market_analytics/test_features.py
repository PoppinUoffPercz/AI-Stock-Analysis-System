from dataclasses import replace
from datetime import timedelta

import pytest

from stock_analysis.market_analytics.config import AnalyticsConfig
from stock_analysis.market_analytics.credit import (
    CreditObservation,
    CreditRegimeEngine,
    CreditStressEngine,
)
from stock_analysis.market_analytics.features import FeatureRecord, build_feature_record
from stock_analysis.market_analytics.fixtures import build_full_fixture
from stock_analysis.market_analytics.pipeline import AnalyticsPipeline
from stock_analysis.market_analytics.replay import ReplayEngine


def _full_snapshot():
    provider, instrument, config = build_full_fixture()
    return ReplayEngine().run(
        provider,
        AnalyticsPipeline(instrument, config, provider.capabilities),
        instrument.symbol,
    )[-1]


def test_feature_record_is_flat_deterministic_and_traceable():
    snapshot = _full_snapshot()
    record = build_feature_record(snapshot)

    assert isinstance(record, FeatureRecord)
    assert record.symbol == snapshot.symbol
    assert record.as_of == snapshot.as_of
    assert set(record.values) == set(record.metadata)
    assert record.values["atm_iv_30d"] is not None
    assert record.values["term_7_30"] is not None
    assert record.values["distance_to_iv_upper_1sigma"] is not None
    assert record.values["distance_to_rnd_p16"] is None
    assert record.metadata["atm_iv_30d"].as_of <= snapshot.as_of
    assert build_feature_record(snapshot) == record


def test_price_only_feature_record_keeps_implied_fields_unavailable():
    provider, instrument, config = build_full_fixture()
    capabilities = replace(
        provider.capabilities,
        supports_options_chain=False,
        supports_iv=False,
    )
    snapshot = ReplayEngine().run(
        provider,
        AnalyticsPipeline(instrument, config, capabilities),
        instrument.symbol,
    )[-1]

    record = snapshot.features
    assert isinstance(record, FeatureRecord)
    assert record.values["atm_iv_30d"] is None
    assert record.metadata["atm_iv_30d"].reason == "IV capability is unsupported"
    assert record.values["event_volatility"] is None


def test_feature_record_rejects_future_credit_metadata():
    snapshot = _full_snapshot()
    future = CreditStressEngine(AnalyticsConfig()).calculate(
        CreditObservation(
            as_of=snapshot.as_of + timedelta(days=1),
            provider="fixture",
            two_ten_slope_pct=0.1,
            treasury_30y_pct=4.0,
            private_credit_alerts=(),
        )
    )

    with pytest.raises(ValueError, match="future"):
        build_feature_record(
            replace(
                snapshot,
                credit=CreditRegimeEngine(AnalyticsConfig()).classify(future, None),
            )
        )
