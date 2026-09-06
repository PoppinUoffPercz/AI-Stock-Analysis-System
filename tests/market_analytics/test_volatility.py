from dataclasses import replace
from datetime import date, timedelta
from math import log, sqrt
from statistics import stdev

import pytest

from stock_analysis.market_analytics.config import (
    AnalyticsConfig,
    OptionsConfig,
    VolatilityConfig,
)
from stock_analysis.market_analytics.models import CallPut
from stock_analysis.market_analytics.volatility import (
    IVRVClassification,
    SkewClassification,
    TermStructureClassification,
    VolatilityEngine,
)
from tests.market_analytics.support import T0, raw_option
from tests.market_analytics.test_options import option_snapshot_with


def _config() -> AnalyticsConfig:
    return AnalyticsConfig(
        volatility=VolatilityConfig(
            implied_horizons_days=(7, 14, 30, 60, 90),
            realized_windows_sessions=(3, 5),
            iv_history_windows=(2, 5),
            max_iv_history=5,
            term_steep_threshold=0.05,
        ),
        options=OptionsConfig(max_quote_age=timedelta(days=10)),
    )


def _two_expiration_chain(*, iv_near=0.20, iv_far=0.40):
    near = date(2026, 1, 9)
    far = date(2026, 3, 6)
    contracts = []
    for expiration, iv in ((near, iv_near), (far, iv_far)):
        contracts.extend(
            (
                raw_option(
                    expiration=expiration,
                    strike=99.0,
                    call_put=CallPut.CALL,
                    iv=iv,
                    delta=0.30,
                ),
                raw_option(
                    expiration=expiration,
                    strike=101.0,
                    call_put=CallPut.CALL,
                    iv=iv + 0.04,
                    delta=0.20,
                ),
                raw_option(
                    expiration=expiration,
                    strike=99.0,
                    call_put=CallPut.PUT,
                    iv=iv + 0.02,
                    delta=-0.70,
                ),
                raw_option(
                    expiration=expiration,
                    strike=101.0,
                    call_put=CallPut.PUT,
                    iv=iv + 0.06,
                    delta=-0.25,
                ),
            )
        )
    return option_snapshot_with(contracts=tuple(contracts))


def test_atm_iv_interpolates_each_side_and_target_horizon_in_total_variance():
    config = _config()
    engine = VolatilityEngine(config)
    state = engine.analyze(_two_expiration_chain(), 100.0, T0)

    near = state.atm_by_expiration[date(2026, 1, 9)]
    assert near.call_iv.value == pytest.approx(0.22)
    assert near.put_iv.value == pytest.approx(0.24)
    assert near.atm_iv.value == pytest.approx(0.23)

    near_t, far_t = (
        state.atm_by_expiration[expiration].time_to_expiry_years
        for expiration in (date(2026, 1, 9), date(2026, 3, 6))
    )
    target_t = 14 / 365
    weight = (target_t - near_t) / (far_t - near_t)
    expected = sqrt(
        ((1 - weight) * 0.23**2 * near_t + weight * 0.43**2 * far_t) / target_t
    )
    assert state.implied_by_horizon[14].value == pytest.approx(expected)
    assert state.implied_by_horizon[90].value is None


def test_realized_volatility_uses_completed_session_returns_and_252_annualization():
    config = _config()
    engine = VolatilityEngine(config)
    closes = (100.0, 101.0, 100.0, 102.0)
    for index, close in enumerate(closes):
        engine.finalize_session(f"s{index}", close, T0 + timedelta(days=index))

    state = engine.analyze(None, closes[-1], T0 + timedelta(days=4))
    returns = [log(closes[index] / closes[index - 1]) for index in range(1, 4)]

    assert state.realized_by_window[3].value == pytest.approx(
        stdev(returns) * sqrt(252)
    )


def test_iv_history_keeps_percentile_rank_and_z_score_point_in_time():
    config = _config()
    engine = VolatilityEngine(config)
    for index, iv in enumerate((0.20, 0.30, 0.40)):
        chain = _two_expiration_chain(iv_near=iv, iv_far=iv)
        state = engine.analyze(chain, 100.0, T0 + timedelta(days=index))
        engine.finalize_session(f"s{index}", 100.0, T0 + timedelta(days=index))

    context = state.iv_history[14][2]
    assert context.current.value == pytest.approx(state.implied_by_horizon[14].value)
    assert context.percentile.value == pytest.approx(100.0)
    assert context.rank.value == pytest.approx(100.0)
    assert context.z_score.value is not None


def test_term_structure_event_premium_and_iv_rv_are_classified_without_direction():
    config = _config()
    engine = VolatilityEngine(config)
    original = _two_expiration_chain(iv_near=0.60, iv_far=0.30)
    chain = option_snapshot_with(
        contracts=tuple(
            replace(
                contract,
                expiration=(
                    date(2026, 1, 13)
                    if contract.expiration == date(2026, 1, 9)
                    else date(2026, 2, 7)
                ),
            )
            for contract in original.contracts
        )
    )
    for index, close in enumerate((100.0, 101.0, 99.0, 100.0, 102.0)):
        engine.finalize_session(f"r{index}", close, T0 + timedelta(days=index))
    state = engine.analyze(chain, 100.0, T0 + timedelta(days=5))

    assert (
        state.term_structure.classification
        is TermStructureClassification.STEEP_BACKWARDATION
    )
    assert state.term_structure.spreads[(7, 30)].value > 0
    assert state.term_structure.spreads[(14, 30)].value > 0
    assert state.event.detected is True
    assert state.event.premium_by_pair[(7, 30)].value is not None
    assert state.event.premium_by_pair[(14, 30)].value is not None
    comparison = state.iv_rv[14]
    assert comparison.classification is IVRVClassification.IV_ABOVE_RV


def test_delta_skew_reports_put_call_skew_risk_reversal_and_butterfly():
    expiration = date(2026, 1, 23)
    chain = option_snapshot_with(
        contracts=(
            raw_option(
                expiration=expiration,
                strike=100,
                call_put=CallPut.CALL,
                iv=0.30,
                delta=0.50,
            ),
            raw_option(
                expiration=expiration,
                strike=100,
                call_put=CallPut.PUT,
                iv=0.30,
                delta=-0.50,
            ),
            raw_option(
                expiration=expiration,
                strike=95,
                call_put=CallPut.PUT,
                iv=0.50,
                delta=-0.25,
            ),
            raw_option(
                expiration=expiration,
                strike=105,
                call_put=CallPut.CALL,
                iv=0.25,
                delta=0.25,
            ),
        )
    )

    state = VolatilityEngine(_config()).analyze(chain, 100.0, T0)
    skew = state.skew_by_expiration[expiration]

    assert skew.put_skew.value == pytest.approx(0.20)
    assert skew.call_skew.value == pytest.approx(-0.05)
    assert skew.risk_reversal.value == pytest.approx(-0.25)
    assert skew.butterfly.value == pytest.approx(0.075)
    assert skew.classification is SkewClassification.STRONG_PUT_SKEW
