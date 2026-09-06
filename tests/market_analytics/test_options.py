from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from stock_analysis.market_analytics.config import AnalyticsConfig, VolatilityConfig
from stock_analysis.market_analytics.models import CallPut, OptionChainEvent, Provenance
from stock_analysis.market_analytics.options import (
    EuropeanBlackScholes,
    IVSurfaceAnalyzer,
    OptionChainNormalizer,
    OptionQualityStatus,
)
from stock_analysis.market_analytics.providers import CapabilityRegistry
from tests.market_analytics.support import T0, raw_option


def option_snapshot_with(*, spot=100.0, contracts=None, invalid_contracts=()):
    from stock_analysis.market_analytics.models import OptionChainEvent

    accepted = tuple(contracts) if contracts is not None else (raw_option(),)
    return OptionChainEvent(
        "AAA",
        T0,
        "fixture",
        "options",
        spot,
        accepted + tuple(invalid_contracts),
    )


def test_option_normalization_rejects_invalid_oi_spread_and_multiplier():
    chain = OptionChainNormalizer().normalize(
        option_snapshot_with(
            invalid_contracts=(
                raw_option(open_interest=-1),
                raw_option(bid=2.0, ask=1.0),
                raw_option(contract_multiplier=0),
            )
        )
    )

    assert len(chain.accepted) == 1
    assert {item.reason for item in chain.rejected} == {
        "negative open interest",
        "bid above ask",
        "invalid multiplier",
    }


def test_iv_surface_selects_nearest_atm_and_marks_provider_values_observed():
    snapshot = option_snapshot_with(
        spot=100.0,
        contracts=(raw_option(strike=99, iv=0.21), raw_option(strike=101, iv=0.25)),
    )
    result = IVSurfaceAnalyzer(AnalyticsConfig()).analyze(snapshot, 100.0, T0)

    assert result.atm_iv.value == 0.21
    assert result.atm_iv.metadata.observed_or_modeled is Provenance.OBSERVED


def test_black_scholes_iv_round_trip_is_stable():
    normalizer = OptionChainNormalizer()
    base = normalizer.normalize(
        option_snapshot_with(contracts=(raw_option(iv=None),))
    ).accepted[0]
    model = EuropeanBlackScholes(AnalyticsConfig())
    theoretical = model.greeks(100.0, base, 0.20, T0).price
    contract = normalizer.normalize(
        option_snapshot_with(
            contracts=(
                raw_option(
                    iv=None,
                    bid=theoretical,
                    ask=theoretical,
                    last=theoretical,
                ),
            )
        )
    ).accepted[0]

    solved = model.implied_volatility(100.0, contract, T0)

    assert solved == pytest.approx(0.20, abs=1e-6)


def test_missing_open_interest_is_preserved_for_downstream_unavailability():
    chain = OptionChainNormalizer().normalize(
        option_snapshot_with(contracts=(raw_option(open_interest=None),))
    )

    assert chain.accepted[0].open_interest is None


def test_empty_chain_returns_unavailable_surface_without_indexing_median():
    result = IVSurfaceAnalyzer(AnalyticsConfig()).analyze(
        option_snapshot_with(contracts=()), 100.0, T0
    )

    assert result.atm_iv.value is None


def test_call_and_put_iv_cells_coexist_independent_of_input_order():
    call = raw_option(call_put=CallPut.CALL, strike=100.0, iv=0.20)
    put = raw_option(call_put=CallPut.PUT, strike=100.0, iv=0.40)
    first = IVSurfaceAnalyzer(AnalyticsConfig()).analyze(
        option_snapshot_with(contracts=(call, put)), 100.0, T0
    )
    second = IVSurfaceAnalyzer(AnalyticsConfig()).analyze(
        option_snapshot_with(contracts=(put, call)), 100.0, T0
    )
    expiration = call.expiration
    call_key = (100.0, CallPut.CALL)
    put_key = (100.0, CallPut.PUT)

    assert set(first.by_expiration[expiration]) == {call_key, put_key}
    assert first.by_expiration[expiration][call_key].value == 0.20
    assert first.by_expiration[expiration][put_key].value == 0.40
    assert first.heatmap == second.heatmap


def test_expiration_day_black_scholes_lasts_until_configured_market_close():
    normalizer = OptionChainNormalizer()
    contract = normalizer.normalize(
        option_snapshot_with(
            contracts=(raw_option(expiration=date(2026, 1, 2), iv=0.20),)
        )
    ).accepted[0]
    model = EuropeanBlackScholes(AnalyticsConfig())
    market_open = datetime(
        2026, 1, 2, 9, 30, tzinfo=ZoneInfo("America/New_York")
    ).astimezone(ZoneInfo("UTC"))
    just_before_close = datetime(
        2026, 1, 2, 15, 59, 59, tzinfo=ZoneInfo("America/New_York")
    ).astimezone(ZoneInfo("UTC"))
    after_close = datetime(
        2026, 1, 2, 16, 0, 1, tzinfo=ZoneInfo("America/New_York")
    ).astimezone(ZoneInfo("UTC"))

    assert model.greeks(100.0, contract, 0.20, market_open).price > 0
    assert model.greeks(100.0, contract, 0.20, just_before_close).price > 0
    with pytest.raises(ValueError, match="expired"):
        model.greeks(100.0, contract, 0.20, after_close)


def test_iv_change_is_keyed_by_expiration_strike_and_side():
    analyzer = IVSurfaceAnalyzer(AnalyticsConfig())
    first = analyzer.analyze(
        option_snapshot_with(
            contracts=(
                raw_option(call_put=CallPut.CALL, strike=100.0, iv=0.20),
                raw_option(call_put=CallPut.PUT, strike=100.0, iv=0.40),
            )
        ),
        100.0,
        T0,
    )
    second = analyzer.analyze(
        option_snapshot_with(
            contracts=(
                raw_option(call_put=CallPut.PUT, strike=100.0, iv=0.35),
                raw_option(call_put=CallPut.CALL, strike=100.0, iv=0.25),
            )
        ),
        100.0,
        T0,
    )
    call_key = (date(2026, 1, 16), 100.0, CallPut.CALL)
    put_key = (date(2026, 1, 16), 100.0, CallPut.PUT)

    assert first.iv_change[call_key].value is None
    assert second.iv_change[call_key].value == pytest.approx(0.05)
    assert second.iv_change[put_key].value == pytest.approx(-0.05)


def test_quote_and_liquidity_quality_reward_tight_liquid_quotes():
    tight = raw_option(
        bid=1.00,
        ask=1.01,
        volume=100.0,
        bid_size=20.0,
        ask_size=20.0,
    )
    wide = raw_option(
        strike=101.0,
        bid=0.50,
        ask=1.50,
        volume=1.0,
        bid_size=1.0,
        ask_size=1.0,
    )
    analyzer = IVSurfaceAnalyzer(AnalyticsConfig())
    result = analyzer.analyze(option_snapshot_with(contracts=(tight, wide)), 100.0, T0)
    tight_key = (date(2026, 1, 16), 100.0, CallPut.CALL)
    # The second contract uses the same identity and is intentionally tested
    # separately below so the comparison does not rely on input ordering.
    wide_result = IVSurfaceAnalyzer(AnalyticsConfig()).analyze(
        option_snapshot_with(contracts=(wide,)), 100.0, T0
    )

    assert result.quote_quality[tight_key].value > 0
    assert result.liquidity_quality is not None
    assert result.liquidity_quality.value is not None
    assert result.liquidity_quality.value > wide_result.liquidity_quality.value
    assert result.liquidity_components[tight_key]["spread_bps"] < 101


def test_zero_quote_sizes_degrade_quality_without_invalidating_iv():
    result = IVSurfaceAnalyzer(AnalyticsConfig()).analyze(
        option_snapshot_with(contracts=(raw_option(bid_size=0.0, ask_size=0.0),)),
        100.0,
        T0,
    )
    key = (date(2026, 1, 16), 100.0, CallPut.CALL)

    assert result.by_expiration[date(2026, 1, 16)][(100.0, CallPut.CALL)].value == 0.20
    assert result.quote_quality[key].metadata.status.value == "degraded"


def test_illiquid_quote_is_retained_with_explicit_low_confidence_flags():
    contract = raw_option(
        bid=0.0,
        ask=0.5,
        volume=0.0,
        open_interest=0.0,
        bid_size=0.0,
        ask_size=0.0,
        quote_timestamp=T0 - timedelta(minutes=10),
    )

    normalized = OptionChainNormalizer(AnalyticsConfig()).normalize(
        option_snapshot_with(contracts=(contract,))
    )

    quality = normalized.accepted[0].quality
    assert quality.valid is True
    assert quality.status is OptionQualityStatus.LOW_CONFIDENCE
    assert {"zero_bid", "zero_volume", "low_open_interest", "timestamp_skew"} <= set(
        quality.flags
    )
    assert 0.0 < quality.confidence < 0.75


def test_impossible_option_timestamps_are_rejected():
    future = raw_option(quote_timestamp=T0 + timedelta(seconds=1))

    normalized = OptionChainNormalizer().normalize(
        option_snapshot_with(contracts=(future,))
    )

    assert len(normalized.accepted) == 0
    assert normalized.rejected[0].reason == "future option quote"


@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("trade_timestamp", "future option trade"),
        ("oi_as_of", "future open interest"),
    ),
)
def test_future_option_trade_and_open_interest_timestamps_are_rejected(
    field: str, reason: str
):
    normalized = OptionChainNormalizer().normalize(
        option_snapshot_with(
            contracts=(raw_option(**{field: T0 + timedelta(seconds=1)}),)
        )
    )

    assert len(normalized.accepted) == 0
    assert normalized.rejected[0].reason == reason


def test_configured_low_volume_is_a_quality_flag_not_a_rejection():
    normalized = OptionChainNormalizer(
        AnalyticsConfig(volatility=VolatilityConfig(min_volume=5.0))
    ).normalize(option_snapshot_with(contracts=(raw_option(volume=2.0),)))

    assert len(normalized.accepted) == 1
    assert "low_volume" in normalized.accepted[0].quality.flags


def test_nonpositive_ask_and_expired_same_day_contracts_are_rejected():
    after_close = datetime(
        2026, 1, 2, 16, 0, 1, tzinfo=ZoneInfo("America/New_York")
    ).astimezone(UTC)
    snapshot = OptionChainEvent(
        "AAA",
        after_close,
        "fixture",
        "options",
        100.0,
        (
            raw_option(expiration=date(2026, 1, 2)),
            raw_option(ask=0.0),
        ),
    )
    normalized = OptionChainNormalizer().normalize(snapshot)

    assert {item.reason for item in normalized.rejected} == {
        "expired contract",
        "nonpositive ask",
    }


def test_capabilities_hide_unsupported_option_quote_and_volume_fields():
    snapshot = option_snapshot_with(contracts=(raw_option(),))
    capabilities = CapabilityRegistry(
        supports_options_chain=True,
        supports_iv=True,
        supports_option_volume=False,
        supports_option_bid_ask=False,
    )

    normalized = OptionChainNormalizer().normalize(
        snapshot,
        capabilities=capabilities,
    )

    contract = normalized.accepted[0]
    assert contract.bid is None
    assert contract.ask is None
    assert contract.volume is None
    assert "missing_bid_ask" in contract.quality.flags
