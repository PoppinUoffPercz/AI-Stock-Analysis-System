from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backtest_engine.data.universe import Universe
from backtest_engine.pipeline import discovery
from backtest_engine.strategy.spec import StrategySpec


class _Adapter:
    def __init__(self) -> None:
        self.ohlc: pd.DataFrame | None = None

    def run(self, signals, ohlc, **kwargs):
        self.ohlc = ohlc
        return object()


def _ohlc() -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=5, tz="UTC")
    frame = pd.DataFrame(
        {"open": range(5), "high": range(5), "low": range(5), "close": range(5)},
        index=index,
    )
    frame.index.name = "timestamp"
    frame.attrs["symbol"] = "AAA"
    return frame


def _spec(seen: list[pd.DataFrame]) -> StrategySpec:
    def signals(frame: pd.DataFrame, _params):
        seen.append(frame.copy())
        return pd.DataFrame({"entry": False, "exit": False}, index=frame.index)

    return StrategySpec(name="test", signal_factory=signals, universe_ref="arbitrary-label")


def test_run_spec_filters_before_signal_factory_and_adapter(monkeypatch):
    seen: list[pd.DataFrame] = []
    adapter = _Adapter()
    monkeypatch.setattr(discovery, "get_adapter", lambda _engine: adapter)
    universe = Universe(
        pd.DataFrame(
            [{"symbol": "AAA", "list_date": "2020-01-03", "delist_date": "2020-01-05"}]
        )
    )

    discovery.run_spec(_spec(seen), _ohlc(), universe=universe)

    expected = pd.date_range("2020-01-03", periods=2, tz="UTC")
    assert seen[0].index.equals(expected)
    assert adapter.ohlc is not None
    assert adapter.ohlc.index.equals(expected)


def test_run_spec_without_universe_leaves_frame_unchanged(monkeypatch):
    seen: list[pd.DataFrame] = []
    adapter = _Adapter()
    original = _ohlc()
    monkeypatch.setattr(discovery, "get_adapter", lambda _engine: adapter)

    discovery.run_spec(_spec(seen), original)

    pd.testing.assert_frame_equal(seen[0], original)
    assert adapter.ohlc is original


def test_run_spec_loads_explicit_universe_csv(monkeypatch, tmp_path: Path):
    seen: list[pd.DataFrame] = []
    monkeypatch.setattr(discovery, "get_adapter", lambda _engine: _Adapter())
    path = tmp_path / "universe.csv"
    path.write_text("symbol,list_date,delist_date\nAAA,2020-01-04,\n")

    discovery.run_spec(_spec(seen), _ohlc(), universe=path)

    assert seen[0].index.equals(pd.date_range("2020-01-04", periods=2, tz="UTC"))


def test_run_spec_rejects_configured_missing_universe(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        discovery.run_spec(_spec([]), _ohlc(), universe=tmp_path / "missing.csv")


def test_run_spec_rejects_universe_that_excludes_all_bars(monkeypatch):
    monkeypatch.setattr(discovery, "get_adapter", lambda _engine: _Adapter())
    universe = Universe(pd.DataFrame([{"symbol": "BBB"}]))

    with pytest.raises(ValueError, match="excludes every input bar"):
        discovery.run_spec(_spec([]), _ohlc(), universe=universe)
