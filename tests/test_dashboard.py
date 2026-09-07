from __future__ import annotations

from datetime import timedelta

from stock_analysis.dashboard import DashboardSnapshot, DashboardState, render_dashboard
from stock_analysis.intelligence.models import (
    CostAttribution,
    ReviewProposal,
    RiskDecision,
    RiskDecisionStatus,
)
from stock_analysis.market_analytics.streaming import IngestionHealth
from stock_analysis.paper import PaperAccountSnapshot, ReconciliationReport
from tests.market_analytics.support import T0


def _attribution() -> CostAttribution:
    return CostAttribution(
        "run-1",
        "account_currency",
        "modeled:exact",
        0.05,
        5.0,
        0.5,
        0.25,
        None,
        None,
        None,
        0.75,
        None,
        0.04,
        4.0,
        4.75,
        {"AAA": {"commission": 0.5, "slippage": 0.25, "total": 0.75}},
        ("spread", "financing", "observed_costs"),
        0.0,
        1e-9,
    )


def _ready_snapshot() -> DashboardSnapshot:
    attribution = _attribution()
    review = ReviewProposal(
        "proposal-1",
        "run-1",
        "experiment-1",
        {"screen": {"kind": "screen", "identity": "abc", "schema_version": 2}},
        {"result": "run-1/result.json"},
        ("Evidence says <script>alert(1)</script> remain unchanged",),
        attribution,
        ("small sample",),
        "no_change_recommended",
    )
    risk = RiskDecision(
        "risk-1",
        RiskDecisionStatus.RESIZED,
        "AAA",
        100.0,
        50.0,
        10_000.0,
        5_000.0,
        ("sector_concentration_cap",),
        {"gross_fraction": 0.1},
        {"gross_fraction": 0.15},
        T0,
        T0,
        "risk-v1",
        ("resized",),
        T0 + timedelta(minutes=5),
    )
    return DashboardSnapshot(
        DashboardState.READY,
        T0,
        intelligence_refs=review.intelligence_refs,
        experiment={
            "run_id": "run-1",
            "identity_hash": "experiment-1",
            "strategy": "demo",
            "engine": "vectorbt",
            "data_hash": "data-1",
        },
        attribution=attribution,
        review=review,
        risk=risk,
        paper=PaperAccountSnapshot(95.0, 105.0, 0.5, 2.0, 8.0, ()),
        reconciliation=ReconciliationReport(True, (), 95.0, 95.0),
        ingestion=IngestionHealth(1, 10, 1, 2, 3, 1, False, T0),
    )


def test_dashboard_ready_view_is_responsive_read_only_and_escapes_untrusted_text(
    tmp_path,
):
    path = render_dashboard(_ready_snapshot(), tmp_path / "dashboard.html")
    body = path.read_text(encoding="utf-8")

    assert "SIMULATED / RESEARCH ONLY" in body
    assert "LIVE TRADING IS NOT IMPLEMENTED" in body
    assert "read_only_non_executing" in body
    assert "Gross / cost / net attribution" in body
    assert "sector_concentration_cap" in body
    assert "Streaming ingestion health" in body
    assert "viewport" in body
    assert "@media (max-width: 700px)" in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "<script>alert(1)</script>" not in body
    assert "<form" not in body


def test_dashboard_explicit_loading_empty_and_failure_states(tmp_path):
    cases = (
        (DashboardState.LOADING, {}, "Loading saved dashboard data"),
        (DashboardState.EMPTY, {}, "No persisted research or paper-simulation data"),
        (
            DashboardState.ERROR,
            {"ingestion": "provider <offline>"},
            "provider &lt;offline&gt;",
        ),
    )
    for state, errors, expected in cases:
        path = render_dashboard(
            DashboardSnapshot(state, errors=errors), tmp_path / f"{state.value}.html"
        )
        assert expected in path.read_text(encoding="utf-8")
