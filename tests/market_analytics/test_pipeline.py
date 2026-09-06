from dataclasses import replace
from datetime import timedelta

import pytest

from stock_analysis.market_analytics.config import AnalyticsConfig
from stock_analysis.market_analytics.credit import CreditObservation, CreditStressEngine
from stock_analysis.market_analytics.fixtures import (
    build_full_fixture,
    build_no_root_fixture,
)
from stock_analysis.market_analytics.levels import LevelDirection
from stock_analysis.market_analytics.models import (
    AggressorSide,
    BarEvent,
    InstrumentSpec,
    MetricStatus,
    Provenance,
    SessionTransitionEvent,
    TradeEvent,
    VolumeInputMode,
)
from stock_analysis.market_analytics.pipeline import AnalyticsPipeline
from stock_analysis.market_analytics.profiles import VolumeProfileEngine
from stock_analysis.market_analytics.replay import ReplayEngine
from stock_analysis.market_analytics.vwap import VWAPEngine
from tests.market_analytics.support import T0


def test_full_fixture_replay_uses_one_pipeline_and_exposes_provenance():
    provider, instrument, config = build_full_fixture()
    pipeline = AnalyticsPipeline(instrument, config, provider.capabilities)
    snapshots = ReplayEngine().run(provider, pipeline, instrument.symbol)

    final = snapshots[-1]
    assert final.dom.state == "valid"
    assert final.dom.metrics["book_imbalance_l5"].value is not None
    assert final.dom.metrics["book_imbalance_l5"].metadata.provider == "fixture"
    assert final.flow.flow_delta.metadata.observed_or_modeled in {
        Provenance.OBSERVED,
        Provenance.DERIVED_FROM_OBSERVED,
    }
    assert final.positioning.net_gex.metadata.observed_or_modeled is Provenance.MODELED


def test_pipeline_normalizes_each_option_snapshot_once(monkeypatch):
    provider, instrument, config = build_full_fixture()
    pipeline = AnalyticsPipeline(instrument, config, provider.capabilities)
    option_event = next(provider.iter_option_snapshots(instrument.symbol))
    normalize = pipeline.option_normalizer.normalize
    calls = 0

    def count_normalization(snapshot, *, capabilities=None):
        nonlocal calls
        calls += 1
        return normalize(snapshot, capabilities=capabilities)

    def reject_renormalization(*args, **kwargs):
        raise AssertionError("normalized option chain was normalized again")

    monkeypatch.setattr(pipeline.option_normalizer, "normalize", count_normalization)
    monkeypatch.setattr(
        pipeline.iv_surface.normalizer, "normalize", reject_renormalization
    )
    monkeypatch.setattr(
        pipeline.volatility._surface.normalizer, "normalize", reject_renormalization
    )
    monkeypatch.setattr(
        pipeline.positioning.normalizer, "normalize", reject_renormalization
    )

    pipeline.consume(option_event)

    assert calls == 1


def test_capabilities_make_unsupported_outputs_unavailable_without_suppressing_flow():
    provider, instrument, config = build_full_fixture()
    capabilities = replace(
        provider.capabilities,
        supports_l2=False,
        supports_iv=False,
        supports_greeks=False,
        supports_open_interest=False,
    )
    pipeline = AnalyticsPipeline(instrument, config, capabilities)
    final = ReplayEngine().run(provider, pipeline, instrument.symbol)[-1]

    assert final.dom.metrics["book_imbalance_l5"].value is None
    assert (
        final.dom.metrics["book_imbalance_l5"].metadata.status
        is MetricStatus.UNAVAILABLE
    )
    assert final.options.atm_iv.value is None
    assert final.options.atm_iv.metadata.status is MetricStatus.UNAVAILABLE
    assert final.positioning.net_gex.value is None
    assert final.positioning.net_gex.metadata.status is MetricStatus.UNAVAILABLE
    assert final.flow.flow_delta.value is not None


def test_iv_capability_only_gates_iv_outputs():
    provider, instrument, config = build_full_fixture()
    capabilities = replace(provider.capabilities, supports_iv=False)
    pipeline = AnalyticsPipeline(instrument, config, capabilities)
    final = ReplayEngine().run(provider, pipeline, instrument.symbol)[-1]

    assert final.options.atm_iv.value is None
    assert final.options.atm_iv.metadata.status is MetricStatus.UNAVAILABLE
    assert final.options.quote_quality
    assert final.options.liquidity_quality is not None
    assert final.options.liquidity_quality.value is not None
    assert final.positioning.net_gex.value is not None


@pytest.mark.parametrize(
    ("disabled", "dom_available", "iv_available", "positioning_available"),
    (
        ("supports_l2", False, True, True),
        ("supports_options_chain", True, False, False),
        ("supports_greeks", True, True, False),
        ("supports_open_interest", True, True, False),
    ),
)
def test_capability_matrix_keeps_independent_outputs_available(
    disabled: str,
    dom_available: bool,
    iv_available: bool,
    positioning_available: bool,
):
    provider, instrument, config = build_full_fixture()
    capabilities = replace(provider.capabilities, **{disabled: False})
    pipeline = AnalyticsPipeline(instrument, config, capabilities)
    final = ReplayEngine().run(provider, pipeline, instrument.symbol)[-1]

    assert (final.dom.metrics["book_imbalance_l5"].value is not None) is dom_available
    assert (final.options.atm_iv.value is not None) is iv_available
    assert (final.positioning.net_gex.value is not None) is positioning_available
    assert final.flow.flow_delta.value is not None


def test_volume_input_mode_prevents_trade_and_bar_double_counting():
    instrument = InstrumentSpec("AAA", "XNAS", 1.0, 0)
    trade = TradeEvent("AAA", T0, "fixture", "trades", 100.0, 10.0, None, "t1")
    bar = BarEvent("AAA", T0, "fixture", "bars", 110.0, 110.0, 110.0, 110.0, 10.0)

    exact_config = replace(AnalyticsConfig(), volume_input_mode=VolumeInputMode.TRADES)
    exact_vwap = VWAPEngine(exact_config)
    exact_profile = VolumeProfileEngine(instrument, exact_config)
    exact_vwap.consume_trade(trade)
    exact_profile.consume_trade(trade)
    exact_vwap.consume_bar(bar)
    exact_profile.consume_bar(bar)

    assert exact_vwap.snapshot(T0).metrics["session_vwap"].value == 100.0
    assert exact_profile.snapshot(T0).total_volume == 10.0
    assert exact_profile.snapshot(T0).exact_or_approximate == "exact"

    bar_config = replace(AnalyticsConfig(), volume_input_mode=VolumeInputMode.BARS)
    bar_vwap = VWAPEngine(bar_config)
    bar_profile = VolumeProfileEngine(instrument, bar_config)
    bar_vwap.consume_trade(trade)
    bar_profile.consume_trade(trade)
    bar_vwap.consume_bar(bar)
    bar_profile.consume_bar(bar)

    assert bar_vwap.snapshot(T0).metrics["session_vwap"].value == 110.0
    assert bar_profile.snapshot(T0).total_volume == 10.0
    assert bar_profile.snapshot(T0).exact_or_approximate == "approximate"


def test_pipeline_exposes_bar_flow_exhaustion_and_flip():
    provider, instrument, config = build_full_fixture()
    pipeline = AnalyticsPipeline(instrument, config, provider.capabilities)
    bars = ((100.0, 20.0), (101.0, 18.0), (102.0, 4.0), (103.0, -8.0))

    result = None
    for index, (price, delta) in enumerate(bars):
        timestamp = T0.replace(minute=T0.minute + index)
        pipeline.consume(
            TradeEvent(
                "AAA",
                timestamp,
                "fixture",
                "trades",
                price,
                abs(delta),
                AggressorSide.BUY if delta > 0 else AggressorSide.SELL,
                f"exhaustion-{index}",
            )
        )
        result = pipeline.consume(
            BarEvent(
                "AAA",
                timestamp,
                "fixture",
                "bars",
                price,
                price,
                price,
                price,
                0.0,
            )
        )

    assert result is not None
    assert result.flow.exhaustion is not None
    assert result.flow.exhaustion.bearish_exhaustion_score.value >= 0.5
    assert result.flow.exhaustion.flow_flip is not None


def test_pipeline_resets_session_local_flow_at_local_session_boundary():
    provider, instrument, config = build_full_fixture()
    pipeline = AnalyticsPipeline(instrument, config, provider.capabilities)
    next_session = T0 + timedelta(days=1)

    first = pipeline.consume(
        TradeEvent(
            "AAA", T0, "fixture", "trades", 100.0, 10.0, AggressorSide.BUY, "day1"
        )
    )
    second = pipeline.consume(
        TradeEvent(
            "AAA",
            next_session,
            "fixture",
            "trades",
            110.0,
            5.0,
            AggressorSide.SELL,
            "day2",
        )
    )

    assert first.flow.cvd.value == 10.0
    assert second.flow.cvd.value == -5.0
    assert second.vwap.metrics["session_vwap"].value == 110.0


def test_out_of_session_trade_does_not_become_the_previous_session_close():
    provider, instrument, config = build_full_fixture()
    pipeline = AnalyticsPipeline(instrument, config, provider.capabilities)

    pipeline.consume(
        TradeEvent(
            "AAA", T0, "fixture", "trades", 100.0, 10.0, AggressorSide.BUY, "day1"
        )
    )
    pipeline.consume(
        TradeEvent(
            "AAA",
            T0 + timedelta(hours=7),
            "fixture",
            "trades",
            105.0,
            1.0,
            AggressorSide.BUY,
            "after-hours",
        )
    )
    pipeline.consume(
        TradeEvent(
            "AAA",
            T0 + timedelta(days=1),
            "fixture",
            "trades",
            110.0,
            1.0,
            AggressorSide.BUY,
            "day2",
        )
    )

    assert pipeline.volatility._closes[-1][1] == 100.0


def test_explicit_session_open_clears_prior_profile_and_flow_state():
    provider, instrument, config = build_full_fixture()
    pipeline = AnalyticsPipeline(instrument, config, provider.capabilities)
    pipeline.consume(
        SessionTransitionEvent("AAA", T0, "fixture", "sessions", "2026-01-02", True)
    )
    pipeline.consume(
        TradeEvent(
            "AAA", T0, "fixture", "trades", 100.0, 10.0, AggressorSide.BUY, "day1"
        )
    )
    pipeline.consume(BarEvent("AAA", T0, "fixture", "bars", 100, 100, 100, 100, 10))
    pipeline.consume(
        SessionTransitionEvent(
            "AAA",
            T0 + timedelta(hours=6),
            "fixture",
            "sessions",
            "2026-01-02",
            False,
        )
    )

    opened = pipeline.consume(
        SessionTransitionEvent(
            "AAA",
            T0 + timedelta(days=1),
            "fixture",
            "sessions",
            "2026-01-03",
            True,
        )
    )

    assert opened.flow.cvd.value is None
    assert opened.vwap.metrics["session_vwap"].value is None
    assert opened.profiles["volume"].total_volume == 0.0


def test_full_fixture_exercises_promised_outputs_across_multiple_sessions():
    provider, instrument, config = build_full_fixture()
    pipeline = AnalyticsPipeline(instrument, config, provider.capabilities)
    snapshots = ReplayEngine().run(provider, pipeline, instrument.symbol)
    final = snapshots[-1]

    assert len({snapshot.as_of.date() for snapshot in snapshots}) >= 3
    assert final.dom.state == "valid"
    assert final.vwap.metrics["session_vwap"].value == 101.0
    assert final.flow.cvd.value == 5.0
    assert final.flow.exhaustion is not None
    assert any(snapshot.flow.stacked_imbalances for snapshot in snapshots)
    confirmed_prints = [
        zone for zone in final.profiles["tpo"].single_prints if zone.confirmed
    ]
    assert confirmed_prints
    assert confirmed_prints[0].filled is True
    assert final.profiles["volume"].total_volume > 0
    assert final.profiles["rolling"][14].window_sessions >= 2
    assert final.profiles["rolling"][14].metadata.as_of == final.as_of
    assert final.options.heatmap
    assert final.options.iv_change
    assert final.options.liquidity_quality is not None
    assert final.options.liquidity_quality.value is not None
    assert final.positioning.gex_by_dte
    assert final.positioning.dex_by_dte
    assert final.positioning.dex_by_expiration
    assert any(
        snapshot.positioning.gamma_flip.nearest_root is None for snapshot in snapshots
    )

    no_root_provider, no_root_instrument, no_root_config = build_no_root_fixture()
    no_root_pipeline = AnalyticsPipeline(
        no_root_instrument,
        no_root_config,
        no_root_provider.capabilities,
    )
    no_root_final = ReplayEngine().run(
        no_root_provider, no_root_pipeline, no_root_instrument.symbol
    )[-1]
    assert no_root_final.positioning.gamma_flip.nearest_root is None


def test_pipeline_exposes_shared_volatility_and_system_wide_levels():
    provider, instrument, config = build_full_fixture()
    pipeline = AnalyticsPipeline(instrument, config, provider.capabilities)
    final = ReplayEngine().run(provider, pipeline, instrument.symbol)[-1]

    assert final.volatility is not None
    assert final.volatility.implied_by_horizon[14].value is not None
    assert final.levels
    assert any(level.source == "iv_band" for level in final.levels)
    assert all(level.direction in set(LevelDirection) for level in final.levels)


def test_pipeline_price_only_path_keeps_realized_state_and_marks_iv_unavailable():
    provider, instrument, config = build_full_fixture()
    capabilities = replace(
        provider.capabilities, supports_options_chain=False, supports_iv=False
    )
    pipeline = AnalyticsPipeline(instrument, config, capabilities)
    final = ReplayEngine().run(provider, pipeline, instrument.symbol)[-1]

    assert final.volatility is not None
    assert final.volatility.implied_by_horizon[14].value is None
    assert (
        final.volatility.implied_by_horizon[14].metadata.status
        is MetricStatus.UNAVAILABLE
    )
    assert final.volatility.realized_by_window
    assert final.levels


def test_pipeline_rejects_credit_context_from_the_future():
    provider, instrument, config = build_full_fixture()
    pipeline = AnalyticsPipeline(instrument, config, provider.capabilities)
    future = CreditObservation(
        as_of=T0 + timedelta(days=1),
        provider="fixture",
        two_ten_slope_pct=0.1,
        treasury_30y_pct=4.0,
        private_credit_alerts=(),
    )
    credit = CreditStressEngine(config).calculate(future)
    pipeline.consume(
        TradeEvent("AAA", T0, "fixture", "trades", 100, 1, None, "credit-time")
    )

    with pytest.raises(ValueError, match="future"):
        pipeline.set_credit_context(credit)


def test_pipeline_attaches_typed_credit_observation_at_snapshot_time():
    provider, instrument, config = build_full_fixture()
    pipeline = AnalyticsPipeline(instrument, config, provider.capabilities)
    final = ReplayEngine().run(provider, pipeline, instrument.symbol)[-1]
    context = pipeline.set_credit_observation(
        CreditObservation(
            as_of=final.as_of,
            provider="fixture",
            two_ten_slope_pct=0.1,
            treasury_30y_pct=4.0,
            treasury_30y_history=(3.5, 4.0, 4.5),
            hy_spread_bps=220.0,
            hy_spread_history=(180.0, 200.0, 230.0),
            ig_spread_bps=90.0,
            ig_spread_history=(70.0, 80.0, 100.0),
            sofr_pct=4.75,
            private_credit_alerts=(),
        )
    )

    attached = pipeline.finalize(final.as_of)

    assert attached.credit is context
    assert attached.features.values["credit_stress_score"] is not None
