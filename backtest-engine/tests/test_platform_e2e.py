from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
from stock_analysis.artifacts import ArtifactStore
from stock_analysis.dashboard import DashboardSnapshot, DashboardState, render_dashboard
from stock_analysis.intelligence.engine import RiskEngine
from stock_analysis.intelligence.models import (
    PortfolioRiskContext,
    PortfolioState,
    PositionRequest,
    PositionState,
    RiskDecisionStatus,
    RiskPolicy,
)
from stock_analysis.intelligence.workflow import run_offline_checkpoint
from stock_analysis.llm import LLMEvidenceBundle, LLMResultStatus, ReadOnlyLLMOrchestrator
from stock_analysis.market_analytics.models import TradeEvent
from stock_analysis.market_analytics.providers import CapabilityRegistry
from stock_analysis.market_analytics.replay import ReplayEngine, ReplayProvider
from stock_analysis.market_analytics.streaming import StreamingIngestor, StreamJournal
from stock_analysis.paper import PaperBroker

from backtest_engine.experiment_index import ExperimentIndex
from backtest_engine.metrics.tearsheet import ReportConfig, render_report
from backtest_engine.pipeline.discovery import run_spec
from backtest_engine.review import save_review_proposal
from backtest_engine.strategy.spec import StrategySpec

T0 = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)


def _ohlc() -> pd.DataFrame:
    index = pd.date_range(T0, periods=6, freq="D")
    prices = [100.0, 101.0, 103.0, 104.0, 105.0, 106.0]
    frame = pd.DataFrame(
        {
            "open": prices,
            "high": [price + 1 for price in prices],
            "low": [price - 1 for price in prices],
            "close": prices,
            "volume": [100_000.0] * len(prices),
        },
        index=index,
    )
    frame.attrs["symbol"] = "AAA"
    return frame


def _signals(frame: pd.DataFrame, _params: dict) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "entry": [True, False, False, False, False, False],
            "exit": [False, False, False, True, False, False],
        },
        index=frame.index,
    )


def test_offline_platform_path_is_integrated_replayable_read_only_and_non_live(tmp_path):
    intelligence_root = tmp_path / "intelligence"
    checkpoint = run_offline_checkpoint(intelligence_root)
    intelligence_refs = {
        name: reference.to_record() for name, reference in checkpoint.artifacts.items()
    }

    result = run_spec(
        StrategySpec("platform_e2e", _signals),
        _ohlc(),
        cost_model="us_equity_proportional",
        capital=10_000.0,
        run_id="platform-e2e",
        intelligence_refs=intelligence_refs,
        execution_assumptions={"mode": "simulation", "fill_model": "next_bar_open"},
    )
    outputs = tmp_path / "backtests"
    report = render_report(
        result,
        ReportConfig(
            result.run_id,
            outputs,
            write_quantstats=False,
            write_plotly=False,
        ),
    )
    index = ExperimentIndex(outputs / "experiments.jsonl")
    resolved = index.resolve_intelligence(
        result.run_id, ArtifactStore(intelligence_root, mode="research")
    )
    assert set(resolved) == set(intelligence_refs)

    proposal, proposal_ref = save_review_proposal(
        result,
        index=index,
        intelligence_store=ArtifactStore(intelligence_root, mode="research"),
        proposal_store=ArtifactStore(tmp_path / "reviews", mode="research"),
    )
    assert proposal.execution_status == "read_only_non_executing"
    assert proposal_ref.path.exists()

    request = PositionRequest("NEW", "long", 100.0, 10_000.0, 1.0, T0)
    portfolio = PortfolioState(
        T0,
        100_000.0,
        80_000.0,
        (PositionState("OLD", 150.0, 100.0),),
        (),
    )
    risk = RiskEngine(RiskPolicy(max_sector_fraction=0.20)).decide(
        request,
        portfolio,
        PortfolioRiskContext(
            T0,
            returns_by_symbol={},
            sector_by_symbol={"NEW": "TECH", "OLD": "TECH"},
        ),
    )
    assert risk.status is RiskDecisionStatus.RESIZED
    assert risk.approved_notional == 5_000.0

    paper = PaperBroker(20_000.0, fee_per_share=0.01)
    paper.submit_order("paper-buy", "AAA", "buy", 5.0, T0)
    trades = (
        TradeEvent(
            "AAA",
            T0 + timedelta(seconds=2),
            "fixture",
            "trades",
            102.0,
            3.0,
            None,
            "second",
        ),
        TradeEvent(
            "AAA",
            T0 + timedelta(seconds=1),
            "fixture",
            "trades",
            101.0,
            2.0,
            None,
            "first",
        ),
    )
    replay = ReplayProvider(trades, CapabilityRegistry(supports_historical_ticks=True))
    ReplayEngine().run(replay, paper, "AAA")
    account = paper.account({"AAA": 102.0})
    reconciliation = paper.reconcile()
    assert reconciliation.ok
    assert paper.execution_mode == "paper_local_only"

    journal = StreamJournal(tmp_path / "stream.jsonl")
    stream = StreamingIngestor(2, journal=journal)
    for event in trades:
        stream.ingest(event, event.timestamp + timedelta(milliseconds=1))
    stream.drain_until(T0 + timedelta(seconds=2))
    ingestion_health = stream.health
    assert len(journal.replay()) == 2

    experiment = index.get(result.run_id)
    evidence = LLMEvidenceBundle.from_results(
        experiment=experiment,
        attribution=proposal.attribution,
        review=proposal,
        risk=risk,
        paper=account,
        reconciliation=reconciliation,
        ingestion=ingestion_health,
    )
    assert ReadOnlyLLMOrchestrator().summarize(evidence).status is LLMResultStatus.DISABLED

    dashboard = render_dashboard(
        DashboardSnapshot(
            DashboardState.READY,
            T0,
            intelligence_refs=proposal.intelligence_refs,
            experiment=experiment,
            attribution=proposal.attribution,
            review=proposal,
            risk=risk,
            paper=account,
            reconciliation=reconciliation,
            ingestion=ingestion_health,
        ),
        tmp_path / "dashboard.html",
    )
    dashboard_text = dashboard.read_text(encoding="utf-8")
    assert report.html_path is not None and report.html_path.exists()
    assert "platform-e2e" in dashboard_text
    assert "read_only_non_executing" in dashboard_text
    assert "SIMULATED / RESEARCH ONLY" in dashboard_text
    assert "LIVE TRADING IS NOT IMPLEMENTED" in dashboard_text
