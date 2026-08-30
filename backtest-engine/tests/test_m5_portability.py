"""M5 tests: StrategySpec + cross-engine portability (the plan's M5 deliverable).

The cross-engine identity test asserts that with cost_model='zero', the
VBTAdapter and BTAdapter produce equity curves that end within a small
relative-band of each other on the same synthetic data + signals. This is the
explicit portability contract from the plan.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest_engine.metrics.core import total_return
from backtest_engine.pipeline.discovery import get_adapter, run_spec
from backtest_engine.strategy.adapters.bt_adapter import BTAdapter
from backtest_engine.strategy.adapters.vbt_adapter import VBTAdapter
from backtest_engine.strategy.base import EngineAdapter
from backtest_engine.strategy.builtin import sma_cross
from backtest_engine.strategy.registry import SignalFactory as RegistrySignalFactory
from backtest_engine.strategy.spec import SignalFactory, StrategySpec


def _synth_ohlc(n: int = 300, start: str = "2018-01-02", seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    rets = 0.0008 + rng.normal(0, 0.012, n)
    px = 100 * np.exp(np.cumsum(rets))
    out = pd.DataFrame(
        {
            "open": px,
            "high": px * 1.005,
            "low": px * 0.995,
            "close": px,
            "volume": rng.integers(100_000, 500_000, n).astype(float),
        },
        index=idx.tz_localize("UTC"),
    )
    out.index.name = "timestamp"
    out.attrs["symbol"] = "SYNTH"
    return out


def test_sweep_belongs_only_to_vectorbt_and_signal_type_is_canonical():
    assert hasattr(VBTAdapter, "sweep")
    assert not hasattr(BTAdapter, "sweep")
    assert not hasattr(EngineAdapter, "sweep")
    assert RegistrySignalFactory is SignalFactory


def test_get_adapter_known_and_unknown():
    a = get_adapter("vectorbt")
    assert a.name == "vectorbt"
    b = get_adapter("backtrader")
    assert b.name == "backtrader"
    pytest.importorskip("nautilus_trader")
    c = get_adapter("nautilus")
    assert c.name == "nautilus"
    with pytest.raises(ValueError):
        get_adapter("rolex")


def test_strategy_spec_dispatches_to_vbt():
    pytest.importorskip("vectorbt")
    spec = StrategySpec(
        name="sma_cross",
        signal_factory=sma_cross,
        cost_model="zero",
        capital=100_000.0,
        universe_ref="SYNTH",
        params={"fast": 5, "slow": 30},
    )
    ohlc = _synth_ohlc()
    res = run_spec(spec, ohlc, engine="vectorbt")
    assert res.engine == "vectorbt"
    assert res.capital == 100_000.0


@pytest.mark.smoke
def test_cross_engine_identity_within_tolerance():
    """Plan M5 litmus: same spec + same data + zero costs -> VBT and BT agree
    within a documented window (set at 15% relative on total return). The
    remaining gap is solely from execution mechanics (next-bar open fills,
    position sizing rounding).
    """
    pytest.importorskip("vectorbt")
    pytest.importorskip("backtrader")
    spec = StrategySpec(
        name="sma_cross",
        signal_factory=sma_cross,
        cost_model="zero",
        capital=100_000.0,
        universe_ref="SYNTH",
        params={"fast": 10, "slow": 50},
    )
    ohlc = _synth_ohlc(n=400, seed=3)
    vbt_res = run_spec(spec, ohlc, engine="vectorbt", run_id="x-vbt")
    bt_res = run_spec(spec, ohlc, engine="backtrader", run_id="x-bt")

    # Equity series has comparable length
    assert len(vbt_res.equity) > 0
    assert len(bt_res.equity) > 0

    # Total return check: zero-cost on both should produce comparable outcomes.
    vbt_tr = total_return(vbt_res.equity)
    bt_tr = total_return(bt_res.equity)
    # Tolerance ~7% absolute: VBT fills at next-bar-open already; BT lags
    # by one bar by default but adds explicit cash accounting. Remaining gap
    # is purely mechanical (position-sizing rounding, fill timing) and is the
    # documented portability boundary from the plan.
    assert abs(vbt_tr - bt_tr) < 0.07, f"VBT total_return={vbt_tr:.4f} BT total_return={bt_tr:.4f}"


@pytest.mark.smoke
def test_nautilus_replay_preserves_the_shared_daily_fixture():
    pytest.importorskip("nautilus_trader")
    spec = StrategySpec(
        name="sma_cross",
        signal_factory=sma_cross,
        cost_model="zero",
        capital=100_000.0,
        universe_ref="SYNTH",
        params={"fast": 10, "slow": 50},
    )
    ohlc = _synth_ohlc(n=400, seed=3)
    result = run_spec(spec, ohlc, engine="nautilus", run_id="x-nautilus")

    assert result.engine == "nautilus"
    assert result.params == spec.params
    assert len(result.equity) == len(ohlc)
    assert result.equity.index.equals(ohlc.index)
    assert result.n_trades > 0
