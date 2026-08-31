from __future__ import annotations

from dataclasses import FrozenInstanceError

import pandas as pd
import pytest

from backtest_engine.pipeline.discovery import run_spec
from backtest_engine.reproducibility import RunManifest, dataframe_sha256
from backtest_engine.strategy.spec import StrategySpec


def _ohlc(last_close: float = 102.0) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=3, tz="UTC", name="timestamp")
    frame = pd.DataFrame(
        {
            "open": [100.0, 101.0, last_close],
            "high": [101.0, 102.0, last_close + 1],
            "low": [99.0, 100.0, last_close - 1],
            "close": [100.5, 101.5, last_close],
            "volume": pd.Series([1000, 1100, 1200], index=index, dtype="int64"),
        },
        index=index,
    )
    frame.attrs["symbol"] = "TEST"
    return frame


def test_dataframe_hash_covers_index_columns_dtypes_and_values():
    original = _ohlc()
    assert dataframe_sha256(original) == dataframe_sha256(original.copy())

    variants = [
        _ohlc(103.0),
        original.rename_axis("date"),
        original.rename(columns={"close": "settle"}),
        original.astype({"volume": "float64"}),
    ]
    assert all(dataframe_sha256(original) != dataframe_sha256(item) for item in variants)


def test_manifest_identity_excludes_run_id_and_timestamp_but_covers_inputs(monkeypatch):
    from backtest_engine import pipeline

    class Adapter:
        def run(self, _signals, ohlc, **kwargs):
            from backtest_engine.strategy.result import BacktestResult

            equity = pd.Series([100.0] * len(ohlc), index=ohlc.index)
            return BacktestResult(
                run_id=kwargs["run_id"],
                strategy_name=kwargs["strategy_name"],
                engine="fake",
                params=kwargs["params"],
                capital=kwargs["capital"],
                cost_model=kwargs["cost_model"],
                universe_ref=kwargs["universe_ref"],
                equity=equity,
                returns=equity.pct_change().fillna(0.0),
            )

    monkeypatch.setattr(pipeline.discovery, "get_adapter", lambda _name: Adapter())
    spec = StrategySpec(
        "demo",
        lambda data, params: pd.DataFrame({"entry": False}, index=data.index),
        params={"window": 5},
    )

    first = run_spec(
        spec, _ohlc(), engine="fake", run_id="one", random_seed=7, relevant_args={"synthetic": True}
    )
    second = run_spec(
        spec, _ohlc(), engine="fake", run_id="two", random_seed=7, relevant_args={"synthetic": True}
    )
    changed = run_spec(
        spec,
        _ohlc(103.0),
        engine="fake",
        run_id="three",
        random_seed=7,
        relevant_args={"synthetic": True},
    )

    assert first.manifest is not None
    assert second.manifest is not None
    assert first.manifest.identity_hash == second.manifest.identity_hash
    assert first.manifest.run_id != second.manifest.run_id
    assert first.manifest.identity_hash != changed.manifest.identity_hash
    assert first.manifest.stable["data"]["content_sha256"] == dataframe_sha256(_ohlc())
    with pytest.raises(TypeError):
        first.manifest.stable["params"]["window"] = 10
    with pytest.raises(FrozenInstanceError):
        first.manifest.identity_hash = "changed"


def test_signal_warmup_does_not_change_execution_data_hash(monkeypatch):
    from backtest_engine import pipeline

    class Adapter:
        def run(self, _signals, ohlc, **kwargs):
            from backtest_engine.strategy.result import BacktestResult

            equity = pd.Series([100.0] * len(ohlc), index=ohlc.index)
            return BacktestResult(
                run_id=kwargs["run_id"],
                strategy_name=kwargs["strategy_name"],
                engine="fake",
                params=kwargs["params"],
                capital=kwargs["capital"],
                cost_model=kwargs["cost_model"],
                universe_ref=kwargs["universe_ref"],
                equity=equity,
                returns=equity.pct_change().fillna(0.0),
            )

    monkeypatch.setattr(pipeline.discovery, "get_adapter", lambda _name: Adapter())
    spec = StrategySpec(
        "warmup", lambda data, _params: pd.DataFrame({"entry": False}, index=data.index)
    )
    execution = _ohlc().iloc[1:]
    result = run_spec(spec, execution, engine="fake", run_id="warmup", signal_ohlc=_ohlc())

    assert result.manifest is not None
    assert result.manifest.stable["data"]["content_sha256"] == dataframe_sha256(execution)
    assert result.manifest.stable["signal_data"]["content_sha256"] == dataframe_sha256(_ohlc())


def test_signal_warmup_content_changes_manifest_identity(monkeypatch):
    from backtest_engine import pipeline

    class Adapter:
        def run(self, _signals, ohlc, **kwargs):
            from backtest_engine.strategy.result import BacktestResult

            equity = pd.Series([100.0] * len(ohlc), index=ohlc.index)
            return BacktestResult(
                run_id=kwargs["run_id"],
                strategy_name=kwargs["strategy_name"],
                engine="fake",
                params=kwargs["params"],
                capital=kwargs["capital"],
                cost_model=kwargs["cost_model"],
                universe_ref=kwargs["universe_ref"],
                equity=equity,
                returns=equity.pct_change().fillna(0.0),
            )

    monkeypatch.setattr(pipeline.discovery, "get_adapter", lambda _name: Adapter())
    spec = StrategySpec(
        "warmup", lambda data, _params: pd.DataFrame({"entry": False}, index=data.index)
    )
    first_warmup = _ohlc()
    changed_warmup = _ohlc()
    changed_warmup.iloc[0, changed_warmup.columns.get_loc("close")] = 99.0
    execution = first_warmup.iloc[1:]

    first = run_spec(spec, execution, engine="fake", run_id="first", signal_ohlc=first_warmup)
    same = run_spec(spec, execution, engine="fake", run_id="same", signal_ohlc=first_warmup.copy())
    changed = run_spec(spec, execution, engine="fake", run_id="changed", signal_ohlc=changed_warmup)

    assert first.manifest is not None
    assert same.manifest is not None
    assert changed.manifest is not None
    assert first.manifest.identity_hash == same.manifest.identity_hash
    assert first.manifest.identity_hash != changed.manifest.identity_hash


def test_run_spec_rejects_signal_history_missing_execution_timestamp():
    spec = StrategySpec(
        "warmup", lambda data, _params: pd.DataFrame({"entry": False}, index=data.index)
    )

    with pytest.raises(ValueError, match="signal_ohlc does not cover.*first missing"):
        run_spec(spec, _ohlc(), signal_ohlc=_ohlc().iloc[:-1])


def test_manifest_json_is_stable_and_reload_is_immutable(tmp_path):
    manifest = RunManifest.from_parts(
        stable={"params": {"slow": 20, "fast": 5}},
        provenance={"run_id": "r1", "created_at": "2026-01-01T00:00:00Z"},
    )
    path = tmp_path / "manifest.json"
    path.write_text(manifest.to_json(), encoding="utf-8")

    loaded = RunManifest.load(path)

    assert loaded.run_id == "r1"
    assert loaded.to_json() == loaded.to_json()
    with pytest.raises(TypeError):
        loaded.provenance["run_id"] = "r2"
