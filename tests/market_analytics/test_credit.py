from datetime import timedelta
from types import SimpleNamespace

import pytest

from stock_analysis.market_analytics.config import AnalyticsConfig, CreditConfig
from stock_analysis.market_analytics.credit import (
    CreditAlert,
    CreditAlertSeverity,
    CreditObservation,
    CreditRegime,
    CreditRegimeEngine,
    CreditStressEngine,
    CreditStressLabel,
    CreditVolatilityEngine,
)
from stock_analysis.market_analytics.volatility import VolatilityEngine
from tests.market_analytics.support import T0
from tests.market_analytics.test_volatility import _two_expiration_chain


def _observation(**overrides):
    from stock_analysis.market_analytics.credit import CreditObservation

    values = {
        "as_of": T0,
        "provider": "fixture",
        "two_ten_slope_pct": 0.20,
        "treasury_30y_pct": 4.50,
        "treasury_30y_history": (3.50, 4.00, 4.20, 4.40),
        "hy_spread_bps": 220.0,
        "hy_spread_history": (180.0, 200.0, 210.0, 230.0),
        "ig_spread_bps": 90.0,
        "ig_spread_history": (70.0, 80.0, 90.0, 100.0),
        "sofr_pct": 4.75,
        "private_credit_alerts": (),
        "hy_spread_methodology": "HYG distribution yield minus IEF yield proxy",
        "ig_spread_methodology": "LQD distribution yield minus IEF yield proxy",
    }
    return CreditObservation(**(values | overrides))


def test_missing_credit_inputs_are_unavailable_and_do_not_become_fallback_scores():
    state = CreditStressEngine(AnalyticsConfig()).calculate(
        _observation(
            two_ten_slope_pct=None,
            treasury_30y_pct=None,
            hy_spread_bps=None,
            ig_spread_bps=None,
            sofr_pct=None,
            private_credit_alerts=None,
        )
    )

    assert state.composite.value is None
    assert state.label is CreditStressLabel.UNAVAILABLE
    assert state.components["yield_curve"].value is None
    assert state.components["yield_curve"].metadata.status.value == "unavailable"


def test_credit_composite_renormalizes_available_weights_and_preserves_proxy_labels():
    observation = _observation(
        two_ten_slope_pct=None,
        treasury_30y_pct=None,
        hy_spread_history=(),
        ig_spread_history=(),
    )
    state = CreditStressEngine(
        AnalyticsConfig(credit=CreditConfig(min_weight_coverage=0.30))
    ).calculate(observation)

    assert state.composite.value is not None
    assert state.composite.metadata.status.value == "degraded"
    assert state.components["hy_spread"].metadata.methodology.startswith(
        "HYG distribution"
    )
    assert state.components["ig_spread"].metadata.methodology.startswith(
        "LQD distribution"
    )


def test_private_credit_news_uses_as_of_window_not_seen_news_state():
    active = CreditAlert(
        ticker="ARCC",
        title="Private credit default warning",
        severity=CreditAlertSeverity.WARNING,
        published_at=T0 - timedelta(days=2),
    )
    old = CreditAlert(
        ticker="ARCC",
        title="Old private credit warning",
        severity=CreditAlertSeverity.CRITICAL,
        published_at=T0 - timedelta(days=30),
    )
    engine = CreditStressEngine(AnalyticsConfig())

    first = engine.calculate(_observation(private_credit_alerts=(active, old)))
    second = engine.calculate(_observation(private_credit_alerts=(active, old)))

    assert (
        first.components["private_credit"].value
        == second.components["private_credit"].value
    )
    assert first.components["private_credit"].value > 5


def test_credit_etf_volatility_summary_and_regime_keep_stress_separate():
    config = AnalyticsConfig(
        credit=CreditConfig(
            complacency_iv_rank_threshold=40.0,
            repricing_iv_rank_threshold=70.0,
        )
    )
    volatility_engine = VolatilityEngine(config)
    for index, iv in enumerate((0.20, 0.30, 0.40)):
        volatility_engine.analyze(
            _two_expiration_chain(iv_near=iv, iv_far=iv),
            100.0,
            T0 + timedelta(days=index),
        )
        volatility_engine.finalize_session(
            f"s{index}", 100.0, T0 + timedelta(days=index)
        )
    latest = volatility_engine.current()
    assert latest is not None

    volatility = CreditVolatilityEngine().summarize({"HYG": latest})
    stress = CreditStressEngine(config).calculate(_observation(as_of=latest.as_of))
    regime = CreditRegimeEngine(config).classify(stress, volatility)

    assert volatility.iv_rank.value == pytest.approx(100.0)
    assert regime.regime is CreditRegime.REPRICING
    assert regime.stress is stress


def test_legacy_monitor_adapter_preserves_proxy_methodology_and_missing_news_time():
    monitor = SimpleNamespace(
        yields={
            "2Y": {"value": 4.0},
            "10Y": {"value": 4.4},
            "30Y": {"value": 4.8},
        },
        yield_history={"30Y": {"low": 4.0, "high": 5.0}},
        spreads={
            "HYG": {"spread_bps": 250.0},
            "LQD": {"spread_bps": 90.0},
        },
        spread_history={},
        sofr=4.5,
        private_credit_alerts=(
            {"ticker": "ARCC", "title": "alert", "severity": "WARNING"},
        ),
    )

    observation = CreditObservation.from_legacy_monitor(monitor, T0)

    assert observation.two_ten_slope_pct == pytest.approx(0.4)
    assert observation.hy_spread_methodology.startswith("legacy HYG")
    assert observation.private_credit_alerts is None


def test_credit_volatility_cutoff_excludes_future_symbol_states():
    config = AnalyticsConfig()
    engine = VolatilityEngine(config)
    old = engine.analyze(_two_expiration_chain(), 100.0, T0)
    engine.finalize_session("old", 100.0, T0)
    future = engine.analyze(_two_expiration_chain(), 100.0, T0 + timedelta(days=1))

    summary = CreditVolatilityEngine().summarize(
        {"old": old, "future": future},
        as_of=T0,
    )

    assert set(summary.symbol_states) == {"old"}
