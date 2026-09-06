from dataclasses import fields

from stock_analysis.market_analytics.config import AnalyticsConfig
from stock_analysis.market_analytics.models import AnalyticsSnapshot
from stock_analysis.market_analytics.providers import CapabilityRegistry


def test_analytics_config_has_explicit_shared_volatility_level_and_credit_sections():
    config = AnalyticsConfig()

    assert config.volatility.implied_horizons_days == (1, 3, 7, 14, 30, 60, 90)
    assert config.levels.expected_move_sigmas == (0.5, 1.0, 1.5, 2.0)
    assert config.credit.min_weight_coverage == 0.6


def test_option_capabilities_are_explicit_and_do_not_claim_unrelated_support():
    capabilities = CapabilityRegistry(
        supports_options_chain=True,
        supports_iv=True,
        supports_option_volume=True,
        supports_option_bid_ask=True,
        supports_intraday_options=True,
    )

    assert capabilities.supports_option_volume is True
    assert capabilities.supports_option_bid_ask is True
    assert capabilities.supports_intraday_options is True
    assert capabilities.supports_l2 is False
    assert capabilities.supports_trade_side is False


def test_analytics_snapshot_adds_optional_system_outputs_without_requiring_them():
    names = {field.name for field in fields(AnalyticsSnapshot)}

    assert {"volatility", "levels", "confluence_zones", "credit", "features"} <= names
