from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from stock_analysis.intelligence.engine import (
    CandidateInput,
    RegimeEngine,
    RiskEngine,
    ScreeningEngine,
    ThesisBuilder,
)
from stock_analysis.intelligence.models import (
    PendingOrderState,
    PortfolioRiskContext,
    PortfolioState,
    PositionRequest,
    PositionState,
    RegimePolicyConfig,
    ReturnObservation,
    RiskDecisionStatus,
    RiskPolicy,
    ScreenConfig,
)
from stock_analysis.market_analytics.features import FeatureRecord
from stock_analysis.market_analytics.fixtures import build_full_fixture
from stock_analysis.market_analytics.models import (
    MetricMetadata,
    MetricStatus,
    Provenance,
)
from stock_analysis.market_analytics.pipeline import AnalyticsPipeline
from stock_analysis.market_analytics.replay import ReplayEngine


def _snapshot():
    provider, instrument, config = build_full_fixture()
    pipeline = AnalyticsPipeline(instrument, config, provider.capabilities)
    return ReplayEngine().run(provider, pipeline, instrument.symbol)[-1]


def _strong_record() -> FeatureRecord:
    record = _snapshot().features
    values = dict(record.values)
    metadata = dict(record.metadata)
    values.update(
        {
            "vwap_zscore": 1.5,
            "vwap_slope": 0.05,
            "book_imbalance_l5": 0.8,
            "distance_weighted_imbalance": 0.7,
            "spread_bps": 2.0,
        }
    )
    for name in (
        "vwap_zscore",
        "vwap_slope",
        "book_imbalance_l5",
        "distance_weighted_imbalance",
        "spread_bps",
    ):
        metadata[name] = replace(
            metadata[name],
            status=MetricStatus.OK,
            reason=None,
            quality_score=100.0,
        )
    return FeatureRecord(
        record.symbol, record.as_of, values, metadata, record.categories
    )


def test_feature_record_exports_existing_market_structure_metrics():
    record = _snapshot().features

    assert record.values["spread_bps"] is not None
    assert record.values["book_imbalance_l5"] is not None
    assert record.values["distance_weighted_imbalance"] is not None
    assert record.values["distance_from_vwap_bps"] is not None
    assert "vwap_zscore" in record.values
    assert record.metadata["vwap_zscore"].status in set(MetricStatus)
    assert record.values["flow_delta"] is not None
    assert record.values["cvd"] is not None
    assert record.values["volume_poc"] is not None
    assert record.metadata["spread_bps"].as_of <= record.as_of


def test_regime_rejects_future_metadata_and_is_deterministic():
    record = _snapshot().features
    engine = RegimeEngine()

    assert engine.assess(record) == engine.assess(record)

    metadata = dict(record.metadata)
    metadata["spread_bps"] = replace(
        metadata["spread_bps"], as_of=record.as_of + timedelta(seconds=1)
    )
    future = FeatureRecord(
        record.symbol, record.as_of, record.values, metadata, record.categories
    )

    try:
        engine.assess(future)
    except ValueError as exc:
        assert "future" in str(exc)
    else:
        raise AssertionError("future feature metadata must be rejected")


def test_invalid_and_unsupported_feature_statuses_are_not_consumed():
    record = _strong_record()
    metadata = dict(record.metadata)
    metadata["vwap_zscore"] = replace(
        metadata["vwap_zscore"], status=MetricStatus.INVALID, quality_score=0.0
    )
    metadata["vwap_slope"] = replace(
        metadata["vwap_slope"], status=MetricStatus.UNSUPPORTED, quality_score=0.0
    )
    metadata["book_imbalance_l5"] = replace(
        metadata["book_imbalance_l5"], status=MetricStatus.INVALID, quality_score=0.0
    )
    metadata["distance_weighted_imbalance"] = replace(
        metadata["distance_weighted_imbalance"],
        status=MetricStatus.UNSUPPORTED,
        quality_score=0.0,
    )
    unusable = FeatureRecord(
        record.symbol, record.as_of, record.values, metadata, record.categories
    )

    assessment = RegimeEngine().assess(unusable)
    assert assessment.trend.value == "unknown"

    regime = RegimeEngine().assess(record)
    result = ScreeningEngine().run((CandidateInput(unusable),), regime)
    assert not result.candidates
    assert result.exclusions[record.symbol]


def test_screening_rejects_candidate_metadata_from_the_future():
    record = _strong_record()
    regime = RegimeEngine().assess(record)
    metadata = dict(record.metadata)
    metadata["book_imbalance_l5"] = replace(
        metadata["book_imbalance_l5"], as_of=record.as_of + timedelta(seconds=1)
    )
    future = FeatureRecord(
        record.symbol, record.as_of, record.values, metadata, record.categories
    )

    with pytest.raises(ValueError, match="future"):
        ScreeningEngine().run((CandidateInput(future),), regime)


def test_screening_is_deterministic_and_sparse_evidence_is_excluded():
    record = _strong_record()
    regime = RegimeEngine().assess(record)
    engine = ScreeningEngine()
    candidate = CandidateInput(record, {"scion": 72.0, "omaha": 64.0})

    first = engine.run((candidate,), regime)
    second = engine.run((candidate,), regime)
    assert first == second
    assert first.candidates
    assert first.candidates[0].score_components
    assert first.candidates[0].ranking_score <= 100.0

    values = {name: None for name in record.values}
    metadata = {
        name: MetricMetadata.unavailable(
            as_of=record.as_of,
            provider="fixture",
            dataset="sparse",
            venue_scope="XNAS",
            reason="test sparse input",
        )
        for name in record.values
    }
    values["spread_bps"] = 1.0
    metadata["spread_bps"] = MetricMetadata(
        as_of=record.as_of,
        provider="fixture",
        dataset="sparse",
        venue_scope="XNAS",
        observed_or_modeled=Provenance.OBSERVED,
    )
    sparse = FeatureRecord(record.symbol, record.as_of, values, metadata, {})

    sparse_result = engine.run((CandidateInput(sparse),), RegimeEngine().assess(sparse))
    assert not sparse_result.candidates
    assert sparse_result.exclusions[record.symbol]


def test_thesis_is_not_risk_approval_and_risk_resizes_to_policy_cap():
    snapshot = _snapshot()
    record = _strong_record()
    regime = RegimeEngine().assess(record)
    screen = ScreeningEngine().run((CandidateInput(record),), regime)
    candidate = screen.candidates[0]
    thesis = ThesisBuilder().build(candidate, screen, suggested_notional=50_000.0)

    assert thesis.suggested_position.requested_notional == 50_000.0
    assert thesis.risk_approval_id is None

    portfolio = PortfolioState(
        as_of=snapshot.as_of,
        equity=100_000.0,
        cash=100_000.0,
        positions=(),
        pending_orders=(),
    )
    decision = RiskEngine().decide(thesis.suggested_position, portfolio)

    assert decision.status is RiskDecisionStatus.RESIZED
    assert 0 < decision.approved_notional <= 10_000.0
    assert decision.approved_quantity > 0
    assert "single_name_cap" in decision.binding_constraints


def test_risk_fails_closed_for_stale_portfolio_state():
    snapshot = _snapshot()
    request = PositionRequest(
        symbol=snapshot.symbol,
        direction="long",
        price=100.0,
        requested_notional=1_000.0,
        lot_size=1.0,
        as_of=snapshot.as_of,
    )
    portfolio = PortfolioState(
        as_of=snapshot.as_of - timedelta(minutes=10),
        equity=100_000.0,
        cash=100_000.0,
        positions=(),
        pending_orders=(),
    )

    decision = RiskEngine().decide(request, portfolio)

    assert decision.status is RiskDecisionStatus.UNAVAILABLE
    assert decision.approved_quantity == 0
    assert any("stale" in reason for reason in decision.reasons)


def test_risk_closed_decision_counts_pending_same_symbol_exposure():
    snapshot = _snapshot()
    request = PositionRequest(
        symbol=snapshot.symbol,
        direction="long",
        price=100.0,
        requested_notional=1_000.0,
        lot_size=1.0,
        as_of=snapshot.as_of,
    )
    portfolio = PortfolioState(
        as_of=snapshot.as_of - timedelta(minutes=10),
        equity=100_000.0,
        cash=100_000.0,
        positions=(),
        pending_orders=(PendingOrderState(snapshot.symbol, 8_000.0),),
    )

    decision = RiskEngine().decide(request, portfolio)

    assert decision.status is RiskDecisionStatus.UNAVAILABLE
    assert decision.before_exposure["gross_fraction"] == pytest.approx(0.08)
    assert decision.before_exposure["single_name_fraction"] == pytest.approx(0.08)


def test_risk_reserves_cash_for_pending_buy_orders():
    snapshot = _snapshot()
    request = PositionRequest(
        symbol="NEW",
        direction="long",
        price=100.0,
        requested_notional=10_000.0,
        lot_size=1.0,
        as_of=snapshot.as_of,
    )
    portfolio = PortfolioState(
        as_of=snapshot.as_of,
        equity=100_000.0,
        cash=20_000.0,
        positions=(),
        pending_orders=(PendingOrderState("OTHER", 14_000.0),),
    )

    decision = RiskEngine().decide(request, portfolio)

    assert decision.status is RiskDecisionStatus.RESIZED
    assert decision.approved_notional == pytest.approx(1_000.0)
    assert "cash_reserve" in decision.binding_constraints


def _risk_returns(as_of, values):
    return tuple(
        ReturnObservation(as_of - timedelta(days=len(values) - index - 1), value)
        for index, value in enumerate(values)
    )


def test_risk_resizes_for_sector_concentration_and_fails_closed_without_mapping():
    snapshot = _snapshot()
    request = PositionRequest("NEW", "long", 100.0, 10_000.0, 1.0, snapshot.as_of)
    portfolio = PortfolioState(
        snapshot.as_of,
        100_000.0,
        80_000.0,
        (PositionState("OLD", 150.0, 100.0),),
        (),
    )
    policy = RiskPolicy(max_sector_fraction=0.20)
    context = PortfolioRiskContext(
        snapshot.as_of,
        returns_by_symbol={},
        sector_by_symbol={"NEW": "TECH", "OLD": "TECH"},
    )

    decision = RiskEngine(policy).decide(request, portfolio, context)

    assert decision.status is RiskDecisionStatus.RESIZED
    assert decision.approved_notional == pytest.approx(5_000.0)
    assert "sector_concentration_cap" in decision.binding_constraints

    missing = replace(context, sector_by_symbol={"NEW": "TECH"})
    unavailable = RiskEngine(policy).decide(request, portfolio, missing)
    assert unavailable.status is RiskDecisionStatus.UNAVAILABLE
    assert "sector mapping" in unavailable.reasons[0]


def test_risk_resizes_correlated_cluster_and_rejects_undefined_correlation():
    snapshot = _snapshot()
    request = PositionRequest("NEW", "long", 100.0, 10_000.0, 1.0, snapshot.as_of)
    portfolio = PortfolioState(
        snapshot.as_of,
        100_000.0,
        80_000.0,
        (PositionState("OLD", 150.0, 100.0),),
        (),
    )
    policy = RiskPolicy(
        max_correlated_fraction=0.20,
        max_pair_correlation=0.80,
        risk_lookback=5,
        min_risk_observations=5,
    )
    values = (-0.02, 0.01, -0.01, 0.02, 0.01)
    context = PortfolioRiskContext(
        snapshot.as_of,
        returns_by_symbol={
            "NEW": _risk_returns(snapshot.as_of, values),
            "OLD": _risk_returns(snapshot.as_of, values),
        },
        sector_by_symbol={},
    )

    decision = RiskEngine(policy).decide(request, portfolio, context)

    assert decision.status is RiskDecisionStatus.RESIZED
    assert decision.approved_notional == pytest.approx(5_000.0)
    assert "correlated_cluster_cap" in decision.binding_constraints

    constant = replace(
        context,
        returns_by_symbol={
            "NEW": _risk_returns(snapshot.as_of, (0.01,) * 5),
            "OLD": _risk_returns(snapshot.as_of, values),
        },
    )
    unavailable = RiskEngine(policy).decide(request, portfolio, constant)
    assert unavailable.status is RiskDecisionStatus.UNAVAILABLE
    assert "undefined trailing correlation" in unavailable.reasons[0]


def test_risk_volatility_cap_uses_only_trailing_point_in_time_returns():
    snapshot = _snapshot()
    request = PositionRequest("NEW", "long", 100.0, 50_000.0, 1.0, snapshot.as_of)
    portfolio = PortfolioState(snapshot.as_of, 100_000.0, 100_000.0, (), ())
    policy = RiskPolicy(
        max_single_name_fraction=1.0,
        max_gross_fraction=1.0,
        max_net_fraction=1.0,
        min_cash_fraction=0.0,
        max_annualized_volatility=0.10,
        risk_lookback=6,
        min_risk_observations=6,
    )
    history = _risk_returns(snapshot.as_of, (-0.02, 0.02, -0.02, 0.02, -0.02, 0.02))
    context = PortfolioRiskContext(
        snapshot.as_of,
        returns_by_symbol={"NEW": history},
        sector_by_symbol={},
    )
    with_future = replace(
        context,
        returns_by_symbol={
            "NEW": (
                *history,
                ReturnObservation(snapshot.as_of + timedelta(days=1), 10.0),
            )
        },
    )

    decision = RiskEngine(policy).decide(request, portfolio, context)
    future_decision = RiskEngine(policy).decide(request, portfolio, with_future)

    assert decision.status is RiskDecisionStatus.RESIZED
    assert "portfolio_volatility_cap" in decision.binding_constraints
    assert 0 < decision.approved_notional < request.requested_notional
    assert future_decision.approved_notional == decision.approved_notional


def test_advanced_risk_constraints_fail_closed_on_missing_or_stale_history():
    snapshot = _snapshot()
    request = PositionRequest("NEW", "long", 100.0, 10_000.0, 1.0, snapshot.as_of)
    portfolio = PortfolioState(snapshot.as_of, 100_000.0, 100_000.0, (), ())
    policy = RiskPolicy(
        max_annualized_volatility=0.20,
        risk_lookback=3,
        min_risk_observations=3,
        max_risk_data_age=timedelta(days=1),
    )

    missing = RiskEngine(policy).decide(request, portfolio)
    assert missing.status is RiskDecisionStatus.UNAVAILABLE

    stale_as_of = snapshot.as_of - timedelta(days=2)
    stale = PortfolioRiskContext(
        stale_as_of,
        returns_by_symbol={"NEW": _risk_returns(stale_as_of, (-0.01, 0.01, -0.01))},
        sector_by_symbol={},
    )
    decision = RiskEngine(policy).decide(request, portfolio, stale)
    assert decision.status is RiskDecisionStatus.UNAVAILABLE
    assert "stale" in decision.reasons[0]


def test_position_request_rejects_non_tradeable_identity_and_direction():
    snapshot = _snapshot()

    with pytest.raises(ValueError, match="symbol"):
        PositionRequest("", "long", 100.0, 1_000.0, 1.0, snapshot.as_of)
    with pytest.raises(ValueError, match="long or short"):
        PositionRequest("TEST", "neutral", 100.0, 1_000.0, 1.0, snapshot.as_of)


def test_risk_state_rejects_non_finite_exposure_inputs():
    snapshot = _snapshot()

    with pytest.raises(ValueError, match="portfolio cash"):
        PortfolioState(snapshot.as_of, 100_000.0, float("nan"), (), ())
    with pytest.raises(ValueError, match="position quantity"):
        PositionState("TEST", float("nan"), 100.0)
    with pytest.raises(ValueError, match="pending order signed_notional"):
        PendingOrderState("TEST", float("inf"))


@pytest.mark.parametrize(
    "factory",
    [
        lambda: RegimePolicyConfig(trend_z_threshold=float("nan")),
        lambda: RegimePolicyConfig(low_iv_rank=80.0, high_iv_rank=20.0),
        lambda: RegimePolicyConfig(tight_spread_bps=20.0, stressed_spread_bps=10.0),
        lambda: ScreenConfig(min_feature_coverage=1.1),
        lambda: ScreenConfig(legacy_weight=float("nan")),
        lambda: ScreenConfig(legacy_weight=1.1),
        lambda: RiskPolicy(max_single_name_fraction=float("nan")),
        lambda: RiskPolicy(max_gross_fraction=-0.1),
        lambda: RiskPolicy(min_cash_fraction=1.1),
        lambda: RiskPolicy(max_state_age=timedelta(seconds=-1)),
    ],
)
def test_intelligence_configs_reject_invalid_numeric_contracts(factory):
    with pytest.raises(ValueError):
        factory()
