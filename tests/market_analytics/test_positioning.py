from datetime import date, timedelta

from stock_analysis.market_analytics.config import AnalyticsConfig
from stock_analysis.market_analytics.models import Provenance
from stock_analysis.market_analytics.positioning import PositioningEngine
from tests.market_analytics.support import T0, raw_option


def option_snapshot_with(*, spot=100.0, contracts=None):
    from stock_analysis.market_analytics.models import OptionChainEvent

    return OptionChainEvent(
        "AAA",
        T0,
        "fixture",
        "options",
        spot,
        tuple(contracts) if contracts is not None else (raw_option(),),
    )


def gamma_crossing_chain():
    from stock_analysis.market_analytics.models import CallPut

    return option_snapshot_with(
        contracts=(
            raw_option(call_put=CallPut.CALL, strike=95.0, gamma=0.01, delta=0.75),
            raw_option(call_put=CallPut.PUT, strike=105.0, gamma=0.04, delta=-0.25),
        )
    )


def all_positive_gamma_chain():
    from stock_analysis.market_analytics.models import CallPut

    return option_snapshot_with(
        contracts=(
            raw_option(call_put=CallPut.CALL, strike=95.0, gamma=0.01),
            raw_option(call_put=CallPut.CALL, strike=105.0, gamma=0.04),
        )
    )


def test_gex_scales_with_open_interest_and_multiplier_and_missing_oi_is_unavailable():
    chain = option_snapshot_with(
        contracts=(raw_option(gamma=0.02, open_interest=10, contract_multiplier=100),)
    )
    engine = PositioningEngine(AnalyticsConfig())
    first = engine.analyze(chain, spot=100.0, as_of=T0)

    doubled = option_snapshot_with(
        contracts=(raw_option(gamma=0.02, open_interest=20, contract_multiplier=100),)
    )
    second = engine.analyze(doubled, spot=100.0, as_of=T0)
    missing = option_snapshot_with(
        contracts=(raw_option(gamma=0.02, open_interest=None, contract_multiplier=100),)
    )
    unavailable = engine.analyze(missing, spot=100.0, as_of=T0)

    assert second.net_gex.value == 2 * first.net_gex.value
    assert unavailable.net_gex.value is None


def test_gamma_flip_returns_zero_residual_and_no_root_returns_none():
    engine = PositioningEngine(AnalyticsConfig())
    crossing = engine.analyze(gamma_crossing_chain(), spot=100.0, as_of=T0)
    no_root = engine.analyze(all_positive_gamma_chain(), spot=100.0, as_of=T0)

    assert crossing.gamma_flip.nearest_root is not None
    assert (
        abs(crossing.gamma_flip.nearest_root.residual)
        <= AnalyticsConfig().options.root_residual_tolerance
    )
    assert no_root.gamma_flip.nearest_root is None
    assert crossing.net_gex.metadata.observed_or_modeled is Provenance.MODELED


def test_positioning_exposes_gex_dex_by_dte_and_dex_by_expiration():
    chain = option_snapshot_with(
        contracts=(
            raw_option(strike=95.0, expiration=date(2026, 1, 2), gamma=0.01),
            raw_option(strike=100.0, expiration=date(2026, 1, 9), gamma=0.02),
            raw_option(strike=105.0, expiration=date(2026, 1, 31), gamma=0.03),
        )
    )

    result = PositioningEngine(AnalyticsConfig()).analyze(chain, 100.0, T0)

    assert set(result.gex_by_dte) == {"0DTE", "1-7", "8-30"}
    assert set(result.dex_by_dte) == {"0DTE", "1-7", "8-30"}
    assert set(result.dex_by_expiration) == {
        date(2026, 1, 2),
        date(2026, 1, 9),
        date(2026, 1, 31),
    }
    assert sum(result.gex_by_dte.values()) == result.net_gex.value
    assert sum(result.dex_by_dte.values()) == result.net_dex.value
    assert sum(result.dex_by_expiration.values()) == result.net_dex.value


def test_positioning_requires_current_open_interest_timestamp():
    engine = PositioningEngine(AnalyticsConfig())
    missing = engine.analyze(
        option_snapshot_with(contracts=(raw_option(oi_as_of=None),)), 100.0, T0
    )
    stale = engine.analyze(
        option_snapshot_with(contracts=(raw_option(oi_as_of=T0 - timedelta(days=3)),)),
        100.0,
        T0,
    )
    current = engine.analyze(
        option_snapshot_with(contracts=(raw_option(oi_as_of=T0),)), 100.0, T0
    )

    assert missing.net_gex.value is None
    assert stale.net_gex.value is None
    assert current.net_gex.value is not None
