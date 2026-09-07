from __future__ import annotations

import json

import pytest

from stock_analysis.intelligence.artifacts import ArtifactStore
from stock_analysis.intelligence.workflow import run_offline_checkpoint
from stock_analysis.market_analytics.fixtures import build_full_fixture
from stock_analysis.market_analytics.pipeline import AnalyticsPipeline
from stock_analysis.market_analytics.replay import ReplayEngine


def _snapshot():
    provider, instrument, config = build_full_fixture()
    pipeline = AnalyticsPipeline(instrument, config, provider.capabilities)
    return ReplayEngine().run(provider, pipeline, instrument.symbol)[-1]


def test_artifact_store_round_trips_and_detects_corruption(tmp_path):
    store = ArtifactStore(tmp_path, mode="research")
    reference = store.save("analytics", _snapshot())

    loaded = store.load(reference)
    assert loaded == _snapshot()

    envelope = json.loads(reference.path.read_text(encoding="utf-8"))
    envelope["identity"] = "0" * 64
    reference.path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ValueError, match="identity"):
        store.load(reference)


def test_artifact_store_load_path_rejects_filename_identity_mismatch(tmp_path):
    store = ArtifactStore(tmp_path, mode="research")
    reference = store.save("analytics", _snapshot())
    mismatched_path = reference.path.with_name(f"{'0' * 64}.json")
    mismatched_path.write_bytes(reference.path.read_bytes())

    with pytest.raises(ValueError, match="identity"):
        store.load_path(mismatched_path)


def test_offline_checkpoint_is_repeatable_and_reloadable(tmp_path):
    first = run_offline_checkpoint(tmp_path)
    second = run_offline_checkpoint(tmp_path)

    assert first.artifacts == second.artifacts
    assert first.screen.candidates == second.screen.candidates
    assert first.risk == second.risk

    store = ArtifactStore(tmp_path, mode="research")
    assert store.load(first.artifacts["screen"]) == first.screen
    if first.risk is None:
        assert "risk" not in first.artifacts
    else:
        assert store.load(first.artifacts["risk"]) == first.risk


def test_degraded_checkpoint_marks_missing_data_and_blocks_risk(tmp_path):
    result = run_offline_checkpoint(tmp_path, degraded=True)

    assert result.analytics.dom.metrics["book_imbalance_l5"].metadata.status is not None
    assert result.analytics.dom.metrics["book_imbalance_l5"].value is None
    assert result.risk is None or result.risk.approved_quantity == 0
    assert result.degraded_reasons
