"""M3 tests: cost model + slippage invariants. Property tests via hypothesis
guard against negative fills / negative costs / splitting NaN inputs across
commissions and slippage.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from backtest_engine.execution.costs import (
    PRESETS,
    build_cost_funcs,
    get_preset,
)

# --- Pure units -----------------------------------------------------------


def test_preset_keys_match_plan():
    assert set(PRESETS.keys()) == {
        "us_equity_pershare",
        "us_equity_flat",
        "us_equity_proportional",
        "zero",
    }


def test_zero_preset():
    cm = get_preset("zero")
    assert cm.commission(100, 50.0) == 0.0
    assert cm.slippage_bps(100, 1_000_000) == 0.0
    assert cm.slippage_cost(100, 50.0, 1_000_000) == 0.0


def test_pershare_min_commission():
    cm = get_preset("us_equity_pershare")
    # 1 share @ $0.005 = $0.005 -> floored to $1 min
    assert cm.commission(1.0, 50.0) == 1.0
    # 1000 shares @ $0.005 = $5.00 -> above min
    assert cm.commission(1000.0, 50.0) == 5.0


def test_flat_preset():
    cm = get_preset("us_equity_flat")
    # flat $1 per order regardless of shares
    assert cm.commission(1.0, 50.0) == 1.0
    assert cm.commission(10_000.0, 50.0) == 1.0


def test_max_commission_capped():
    # None cap should be unlimited; demonstrate via patching absent
    cm = get_preset("us_equity_pershare")
    assert cm.max_commission is None
    big = cm.commission(100_000.0, 100.0)
    assert big == 100_000.0 * 0.005


def test_slippage_models():
    cm_lin = PRESETS["us_equity_pershare"]
    bps = cm_lin.slippage_bps(1000, 1_000_000)  # size_ratio=0.001
    assert bps == cm_lin.base_bps + cm_lin.impact_k * 0.001

    cm_sqrt = PRESETS["us_equity_pershare"].__class__(
        preset="us_equity_pershare",
        slippage_model="sqrt_impact",
        per_share=0.0,
        flat_fee=1.0,
        min_commission=0.0,
        max_commission=None,
        base_bps=1.0,
        impact_k=50.0,
        fees_fraction=0.0,
    )
    bps_sq = cm_sqrt.slippage_bps(1000, 1_000_000)
    assert math.isclose(bps_sq, 1.0 + 50.0 * math.sqrt(0.001), rel_tol=1e-9)


def test_slippage_handles_zero_volume():
    cm = get_preset("us_equity_pershare")
    # Zero volume must never divide by zero: returns base_bps fallback.
    assert cm.slippage_bps(100, 0) == cm.base_bps


# --- Round-trip: build_cost_funcs / vbt integration shape -----------------


def test_build_cost_funcs_returns_nonnegative():
    fees, slip = build_cost_funcs("us_equity_proportional")
    assert fees >= 0
    assert slip >= 0


def test_build_cost_funcs_zero_preset():
    fees, slip = build_cost_funcs("zero")
    assert fees == 0.0
    assert slip == 0.0


def test_build_cost_funcs_rejects_unknown():
    with pytest.raises(ValueError):
        build_cost_funcs("rolex")


@pytest.mark.parametrize("name", ["us_equity_flat", "us_equity_pershare"])
def test_build_cost_funcs_rejects_unrepresentable_presets(name):
    with pytest.raises(ValueError, match="cannot represent.*exactly"):
        build_cost_funcs(name)


# --- Hypothesis property tests --------------------------------------------


@given(
    shares=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    price=st.floats(min_value=1.0, max_value=10_000.0, allow_nan=False, allow_infinity=False),
    volume=st.floats(min_value=0.0, max_value=1e12, allow_nan=False, allow_infinity=False),
)
def test_commission_and_slippage_never_negative(shares, price, volume):
    for name in PRESETS:
        cm = get_preset(name)
        assert cm.commission(shares, price) >= 0.0
        assert cm.slippage_bps(shares, volume) >= 0.0
        assert cm.slippage_cost(shares, price, volume) >= 0.0


@given(
    shares=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    volume=st.floats(min_value=1.0, max_value=1e12, allow_nan=False, allow_infinity=False),
)
def test_slippage_monotone_in_size(shares, volume):
    # Volume-impact should be weakly increasing in order size when linear or sqrt.
    cm_lin = get_preset("us_equity_pershare")
    bps_small = cm_lin.slippage_bps(shares * 0.5, volume)
    bps_big = cm_lin.slippage_bps(shares, volume)
    assert bps_big >= bps_small - 1e-9  # equal ok; smaller ok; never far less
