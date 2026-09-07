from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from stock_analysis.market_analytics.asof import PointInTimeStore, SnapshotEnvelope
from stock_analysis.market_analytics.fixtures import build_full_fixture
from stock_analysis.market_analytics.pipeline import AnalyticsPipeline
from stock_analysis.market_analytics.replay import ReplayEngine

from .artifacts import ArtifactStore
from .engine import (
    CandidateInput,
    RegimeEngine,
    RiskEngine,
    ScreeningEngine,
    ThesisBuilder,
)
from .models import CheckpointResult, PortfolioState


def run_offline_checkpoint(
    root: str | Path, *, degraded: bool = False
) -> CheckpointResult:
    """Run the first integrated checkpoint with deterministic, labeled fixtures only."""
    provider, instrument, config = build_full_fixture()
    capabilities = provider.capabilities
    if degraded:
        capabilities = replace(
            capabilities,
            supports_l2=False,
            supports_options_chain=False,
            supports_iv=False,
            supports_greeks=False,
            supports_open_interest=False,
        )
    analytics = ReplayEngine().run(
        provider,
        AnalyticsPipeline(instrument, config, capabilities),
        instrument.symbol,
    )[-1]

    store = ArtifactStore(root, mode="research")
    analytics_ref = PointInTimeStore(root).ingest(
        SnapshotEnvelope(
            symbol=analytics.symbol,
            dataset="analytics",
            provider="fixture",
            effective_at=analytics.as_of,
            observed_at=analytics.as_of,
            received_at=analytics.as_of,
            available_at=analytics.as_of,
            revision_id="fixture-v1",
            payload=analytics,
        )
    )
    regime = RegimeEngine().assess(analytics.features)
    regime_ref = store.save("regime", regime)
    screen = ScreeningEngine().run(
        (CandidateInput(analytics.features),),
        regime,
        input_snapshot_refs={
            "analytics": analytics_ref.identity,
            "regime": regime_ref.identity,
        },
    )
    screen_ref = store.save("screen", screen)

    thesis = None
    risk = None
    artifacts = {
        "analytics": analytics_ref,
        "regime": regime_ref,
        "screen": screen_ref,
    }
    if screen.candidates:
        candidate = screen.candidates[0]
        try:
            thesis = ThesisBuilder().build(candidate, screen)
        except ValueError:
            thesis = None
        if thesis is not None:
            thesis_ref = store.save("thesis", thesis)
            artifacts["thesis"] = thesis_ref
            portfolio = PortfolioState(
                as_of=(
                    analytics.as_of - timedelta(minutes=10)
                    if degraded
                    else analytics.as_of
                ),
                equity=100_000.0,
                cash=100_000.0,
                positions=(),
                pending_orders=(),
            )
            risk = RiskEngine().decide(thesis.suggested_position, portfolio)
            risk_ref = store.save("risk", risk)
            artifacts["risk"] = risk_ref

    degraded_reasons: list[str] = []
    if analytics.dom.metrics["book_imbalance_l5"].value is None:
        degraded_reasons.append("depth analytics unavailable")
    if analytics.options.atm_iv.value is None:
        degraded_reasons.append("implied-volatility analytics unavailable")
    if not screen.candidates:
        degraded_reasons.append("no candidate met deterministic screening requirements")
    if risk is not None and risk.approved_quantity == 0:
        degraded_reasons.append("risk approval unavailable or rejected")

    return CheckpointResult(
        analytics,
        regime,
        screen,
        thesis,
        risk,
        artifacts,
        tuple(degraded_reasons),
    )
