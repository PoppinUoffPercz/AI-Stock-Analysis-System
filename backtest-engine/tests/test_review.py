from __future__ import annotations

import copy
import json

import pandas as pd
import pytest
from stock_analysis.artifacts import SCHEMA_VERSION, ArtifactStore

from backtest_engine.experiment_index import ExperimentIndex
from backtest_engine.reproducibility import RunManifest
from backtest_engine.review import attribute_costs, save_review_proposal
from backtest_engine.strategy.result import BacktestResult, TradeRecord


def _result(intelligence: dict[str, object]) -> BacktestResult:
    index = pd.date_range("2026-01-01", periods=3, tz="UTC")
    manifest = RunManifest.from_parts(
        stable={
            "strategy": {"name": "demo"},
            "engine": "vectorbt",
            "params": {},
            "capital": 100.0,
            "cost": {"name": "us_equity_proportional"},
            "data": {"content_sha256": "fixture"},
            "universe": {"reference": "fixture"},
            "intelligence": intelligence,
        },
        provenance={"run_id": "review-run", "created_at": "2026-01-01T00:00:00Z"},
    )
    return BacktestResult(
        run_id="review-run",
        strategy_name="demo",
        engine="vectorbt",
        params={},
        capital=100.0,
        cost_model="us_equity_proportional",
        universe_ref="fixture",
        equity=pd.Series([100.0, 101.0, 102.0], index=index),
        returns=pd.Series([0.0, 0.01, 102 / 101 - 1], index=index),
        trades=[
            TradeRecord(index[0], "AAA", "LONG", 1.0, 10.0, 0.25, 0.15),
            TradeRecord(index[1], "BBB", "LONG", 1.0, 20.0, 0.50, 0.10),
        ],
        metadata={
            "cost_fidelity": "exact",
            "total_commission": 0.75,
            "total_slippage": 0.25,
            "total_execution_cost": 1.0,
            "net_final_equity": 102.0,
            "cost_addback_final_equity": 103.0,
            "strategy_gross_return": 0.04,
        },
        manifest=manifest,
    )


def _indexed_result(tmp_path):
    intelligence_store = ArtifactStore(tmp_path / "intelligence", mode="research")
    screen_ref = intelligence_store.save("screen", {"version": "screen-v1"})
    risk_ref = intelligence_store.save("risk", {"version": "risk-v1"})
    intelligence = {"screen": screen_ref.to_record(), "risk": risk_ref.to_record()}
    result = _result(intelligence)
    index = ExperimentIndex(tmp_path / "outputs" / "experiments.jsonl")
    index.append(
        result.manifest,
        artifacts={
            "manifest": "review-run/manifest.json",
            "result": "review-run/result.json",
        },
    )
    return result, index, intelligence_store


def test_cost_attribution_reconciles_supported_components_without_fabricating_unknowns(tmp_path):
    result, _, _ = _indexed_result(tmp_path)

    attribution = attribute_costs(result)

    assert attribution.gross_return == pytest.approx(0.04)
    assert attribution.gross_pnl == pytest.approx(4.0)
    assert attribution.net_return == pytest.approx(0.02)
    assert attribution.net_pnl == pytest.approx(2.0)
    assert attribution.modeled_commission == pytest.approx(0.75)
    assert attribution.modeled_slippage == pytest.approx(0.25)
    assert attribution.modeled_total_cost == pytest.approx(1.0)
    assert attribution.cost_addback_pnl == pytest.approx(3.0)
    assert attribution.reconciliation_difference == pytest.approx(0.0)
    assert attribution.modeled_fees is None
    assert attribution.modeled_spread is None
    assert attribution.modeled_financing is None
    assert attribution.observed_total_cost is None
    assert attribution.modeled_costs_by_symbol["AAA"]["total"] == pytest.approx(0.40)
    assert attribution.modeled_costs_by_symbol["BBB"]["total"] == pytest.approx(0.60)


def test_unknown_cost_fidelity_is_unavailable_not_zero(tmp_path):
    result, _, _ = _indexed_result(tmp_path)
    result.metadata.pop("cost_fidelity")

    attribution = attribute_costs(result)

    assert attribution.cost_basis == "unavailable"
    assert attribution.modeled_total_cost is None
    assert attribution.modeled_commission is None
    assert attribution.modeled_slippage is None


def test_review_proposal_round_trips_with_exact_provenance_and_no_experiment_mutation(tmp_path):
    result, index, intelligence_store = _indexed_result(tmp_path)
    proposal_store = ArtifactStore(tmp_path / "reviews", mode="research")
    metadata_before = copy.deepcopy(result.metadata)
    index_before = index.path.read_text(encoding="utf-8")

    proposal, reference = save_review_proposal(
        result,
        index=index,
        intelligence_store=intelligence_store,
        proposal_store=proposal_store,
    )

    assert proposal.execution_status == "read_only_non_executing"
    assert proposal.run_id == result.run_id
    assert proposal.experiment_identity == result.manifest.identity_hash
    assert proposal.intelligence_refs == result.manifest.stable["intelligence"]
    assert proposal.experiment_artifacts["result"] == "review-run/result.json"
    assert proposal.proposed_action == "collect_more_samples_before_strategy_changes"
    assert proposal.sample_warnings
    assert proposal_store.load(reference) == proposal
    assert result.metadata == metadata_before
    assert index.path.read_text(encoding="utf-8") == index_before


def test_experiment_index_resolves_historical_refs_and_rejects_missing_stale_malformed_duplicates(
    tmp_path,
):
    result, index, store = _indexed_result(tmp_path)
    resolved = index.resolve_intelligence(result.run_id, store)
    assert (
        resolved["screen"].identity == result.manifest.stable["intelligence"]["screen"]["identity"]
    )

    legacy = tmp_path / "legacy.jsonl"
    legacy.write_text(json.dumps({"run_id": "legacy", "identity_hash": "old"}) + "\n")
    with pytest.raises(ValueError, match="no recorded intelligence provenance"):
        ExperimentIndex(legacy).resolve_intelligence("legacy", store)

    record = json.loads(index.path.read_text().splitlines()[0])
    record["run_id"] = "stale"
    record["intelligence"]["screen"]["schema_version"] = SCHEMA_VERSION - 1
    stale = tmp_path / "stale.jsonl"
    stale.write_text(json.dumps(record) + "\n")
    with pytest.raises(ValueError, match="stale intelligence reference"):
        ExperimentIndex(stale).resolve_intelligence("stale", store)

    record["run_id"] = "malformed"
    record["intelligence"] = {"screen": "opaque-legacy-id"}
    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text(json.dumps(record) + "\n")
    with pytest.raises(ValueError, match="malformed intelligence reference"):
        ExperimentIndex(malformed).resolve_intelligence("malformed", store)

    good = json.loads(index.path.read_text().splitlines()[0])
    good["run_id"] = "duplicate"
    good["intelligence"]["risk"] = good["intelligence"]["screen"]
    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(json.dumps(good) + "\n")
    with pytest.raises(ValueError, match="duplicate intelligence reference"):
        ExperimentIndex(duplicate).resolve_intelligence("duplicate", store)


def test_experiment_index_missing_artifact_fails_instead_of_selecting_latest(tmp_path):
    result, index, store = _indexed_result(tmp_path)
    screen = result.manifest.stable["intelligence"]["screen"]
    screen_path = store.root / store.mode / screen["kind"] / f"{screen['identity']}.json"
    screen_path.unlink()

    with pytest.raises(FileNotFoundError, match="missing artifact reference"):
        index.resolve_intelligence(result.run_id, store)
