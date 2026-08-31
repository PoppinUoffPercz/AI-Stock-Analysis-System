"""Tests for the canonical signal-frame contract used by both adapters."""

from __future__ import annotations

import pandas as pd
import pytest

from backtest_engine.strategy.adapters.bt_adapter import BTAdapter
from backtest_engine.strategy.adapters.vbt_adapter import VBTAdapter
from backtest_engine.strategy.validation import SignalValidationError, validate_signal_frame


def _ohlc(index: pd.Index) -> pd.DataFrame:
    n = len(index)
    return pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1_000.0] * n,
        },
        index=index,
    )


def _signals(index: pd.Index, **columns: object) -> pd.DataFrame:
    values = columns or {"entry": [False] * len(index)}
    return pd.DataFrame(values, index=index)


def _run(adapter: object, signals: pd.DataFrame, ohlc: pd.DataFrame):
    return adapter.run(  # type: ignore[attr-defined]
        signals,
        ohlc,
        capital=1_000.0,
        cost_model="zero",
        strategy_name="contract",
        universe_ref="TEST",
        params={},
        run_id="contract",
    )


@pytest.mark.parametrize("adapter_type", [BTAdapter, VBTAdapter])
@pytest.mark.parametrize(
    ("case", "make_frames"),
    [
        (
            "missing timestamp",
            lambda idx: (_signals(idx[:-1]), _ohlc(idx)),
        ),
        (
            "extra timestamp",
            lambda idx: (
                _signals(idx.append(pd.DatetimeIndex([idx[-1] + pd.Timedelta(days=1)]))),
                _ohlc(idx),
            ),
        ),
        (
            "duplicate signal index",
            lambda idx: (_signals(idx.insert(1, idx[0])), _ohlc(idx)),
        ),
        (
            "out of order signal index",
            lambda idx: (_signals(idx[[1, 0, 2]]), _ohlc(idx)),
        ),
        (
            "invalid index",
            lambda idx: (_signals(pd.Index(["a", "b", "c"])), _ohlc(idx)),
        ),
        (
            "extra column",
            lambda idx: (
                _signals(idx, entry=[False] * 3, exit=[False] * 3, extra=[1] * 3),
                _ohlc(idx),
            ),
        ),
        (
            "missing entry column",
            lambda idx: (_signals(idx, exit=[False] * 3), _ohlc(idx)),
        ),
        (
            "non boolean values",
            lambda idx: (_signals(idx, entry=[0, 1, 0]), _ohlc(idx)),
        ),
        (
            "missing values",
            lambda idx: (
                _signals(
                    idx,
                    entry=pd.Series([False, pd.NA, False], index=idx, dtype="boolean"),
                ),
                _ohlc(idx),
            ),
        ),
    ],
)
def test_adapters_reject_invalid_signal_frames(adapter_type, case, make_frames):
    idx = pd.date_range("2024-01-02", periods=3, freq="D", tz="UTC")
    signals, ohlc = make_frames(idx)

    with pytest.raises(SignalValidationError) as caught:
        _run(adapter_type(), signals, ohlc)

    assert str(caught.value), f"{case}: missing actionable message"


def test_vbt_validates_before_importing_engine(monkeypatch):
    import backtest_engine.strategy.adapters.vbt_adapter as vbt_adapter

    monkeypatch.setattr(vbt_adapter, "_import_vbt", lambda: pytest.fail("engine imported first"))
    idx = pd.date_range("2024-01-02", periods=3, freq="D", tz="UTC")
    signals, ohlc = _signals(idx, entry=[False] * 3, extra=[False] * 3), _ohlc(idx)

    with pytest.raises(SignalValidationError):
        _run(VBTAdapter(), signals, ohlc)


def test_validate_signal_frame_normalizes_utc_and_returns_defensive_canonical_copy():
    utc_index = pd.date_range("2024-01-02 14:30", periods=3, freq="h", tz="UTC")
    local_index = utc_index.tz_convert("America/New_York")
    signals = pd.DataFrame(
        {"exit": [False, True, False], "entry": [True, False, False]},
        index=local_index,
    )
    original = signals.copy(deep=True)

    canonical = validate_signal_frame(signals, _ohlc(utc_index))

    assert list(canonical.columns) == ["entry", "exit"]
    assert canonical.index.equals(utc_index)
    canonical.iloc[0, 0] = False
    assert signals.equals(original)
