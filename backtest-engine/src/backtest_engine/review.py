"""Cost-aware, read-only review of persisted experiments."""

from __future__ import annotations

import math
from collections import defaultdict

from stock_analysis.artifacts import ArtifactRef, ArtifactStore, content_identity
from stock_analysis.intelligence.models import CostAttribution, ReviewProposal

from backtest_engine.experiment_index import ExperimentIndex
from backtest_engine.strategy.result import BacktestResult, validate_backtest_result

RECONCILIATION_TOLERANCE = 1e-9


def attribute_costs(result: BacktestResult) -> CostAttribution:
    """Describe gross, modeled-cost, and net performance without inventing data."""
    validate_backtest_result(result)
    net_pnl = result.final_equity - result.capital
    net_return = None if result.capital == 0 else result.final_equity / result.capital - 1.0
    gross_return_value = result.metadata.get("strategy_gross_return")
    gross_return = (
        float(gross_return_value)
        if isinstance(gross_return_value, (int, float)) and not isinstance(gross_return_value, bool)
        else None
    )
    gross_pnl = None if gross_return is None else result.capital * gross_return

    fidelity = result.metadata.get("cost_fidelity")
    if not isinstance(fidelity, str) or not fidelity.strip():
        return CostAttribution(
            run_id=result.run_id,
            units="account_currency",
            cost_basis="unavailable",
            gross_return=gross_return,
            gross_pnl=gross_pnl,
            modeled_commission=None,
            modeled_slippage=None,
            modeled_fees=None,
            modeled_spread=None,
            modeled_financing=None,
            modeled_total_cost=None,
            observed_total_cost=None,
            net_return=net_return,
            net_pnl=net_pnl,
            cost_addback_pnl=None,
            modeled_costs_by_symbol={},
            unavailable_cost_components=("commission", "fees", "spread", "slippage", "financing"),
            reconciliation_difference=None,
            reconciliation_tolerance=RECONCILIATION_TOLERANCE,
        )

    commission = sum(trade.commission for trade in result.trades)
    slippage = sum(trade.slippage_cost for trade in result.trades)
    total = commission + slippage
    per_symbol: dict[str, dict[str, float]] = defaultdict(
        lambda: {"commission": 0.0, "slippage": 0.0, "total": 0.0}
    )
    for trade in result.trades:
        row = per_symbol[trade.symbol]
        row["commission"] += trade.commission
        row["slippage"] += trade.slippage_cost
        row["total"] += trade.commission + trade.slippage_cost

    experiment_total = result.metadata.get("total_execution_cost")
    difference = None
    if isinstance(experiment_total, (int, float)) and not isinstance(experiment_total, bool):
        difference = total - float(experiment_total)
        if not math.isclose(
            difference,
            0.0,
            rel_tol=RECONCILIATION_TOLERANCE,
            abs_tol=RECONCILIATION_TOLERANCE,
        ):
            raise ValueError("cost attribution does not reconcile to experiment totals")

    return CostAttribution(
        run_id=result.run_id,
        units="account_currency",
        cost_basis=f"modeled:{fidelity}",
        gross_return=gross_return,
        gross_pnl=gross_pnl,
        modeled_commission=commission,
        modeled_slippage=slippage,
        modeled_fees=None,
        modeled_spread=None,
        modeled_financing=None,
        modeled_total_cost=total,
        observed_total_cost=None,
        net_return=net_return,
        net_pnl=net_pnl,
        cost_addback_pnl=net_pnl + total,
        modeled_costs_by_symbol=dict(per_symbol),
        unavailable_cost_components=("separate_fees", "spread", "financing", "observed_costs"),
        reconciliation_difference=difference,
        reconciliation_tolerance=RECONCILIATION_TOLERANCE,
    )


def save_review_proposal(
    result: BacktestResult,
    *,
    index: ExperimentIndex,
    intelligence_store: ArtifactStore,
    proposal_store: ArtifactStore,
) -> tuple[ReviewProposal, ArtifactRef]:
    """Generate and persist a deterministic proposal with no execution authority."""
    if result.manifest is None:
        raise ValueError("review proposal requires the persisted experiment manifest")
    record = index.get(result.run_id)
    if record.get("identity_hash") != result.manifest.identity_hash:
        raise ValueError("experiment index identity does not match result manifest")
    resolved = index.resolve_intelligence(result.run_id, intelligence_store)
    intelligence_refs = {name: reference.to_record() for name, reference in resolved.items()}
    artifacts = record.get("artifacts")
    if not isinstance(artifacts, dict) or any(
        not isinstance(name, str) or not isinstance(path, str) for name, path in artifacts.items()
    ):
        raise ValueError("malformed experiment artifact references")

    attribution = attribute_costs(result)
    warnings: list[str] = []
    if result.n_trades < 30:
        warnings.append("small sample: fewer than 30 recorded trades")
    if attribution.gross_return is None:
        warnings.append("gross zero-cost replay performance is unavailable")
    if attribution.observed_total_cost is None:
        warnings.append("observed execution costs are unavailable; costs are modeled only")

    proposed_action, rationale = _proposal_decision(result, attribution)
    identity_value = {
        "run_id": result.run_id,
        "experiment_identity": result.manifest.identity_hash,
        "intelligence_refs": intelligence_refs,
        "experiment_artifacts": artifacts,
        "proposed_action": proposed_action,
        "rationale": rationale,
        "attribution": attribution,
        "sample_warnings": warnings,
    }
    proposal = ReviewProposal(
        proposal_id=content_identity(identity_value),
        run_id=result.run_id,
        experiment_identity=result.manifest.identity_hash,
        intelligence_refs=intelligence_refs,
        experiment_artifacts=artifacts,
        rationale=rationale,
        attribution=attribution,
        sample_warnings=tuple(warnings),
        proposed_action=proposed_action,
    )
    return proposal, proposal_store.save("review-proposal", proposal, identity_value=identity_value)


def _proposal_decision(
    result: BacktestResult, attribution: CostAttribution
) -> tuple[str, tuple[str, ...]]:
    if result.n_trades < 10:
        return (
            "collect_more_samples_before_strategy_changes",
            (
                f"only {result.n_trades} recorded trades are available",
                "sample size is too small to justify an automated strategy/configuration change",
            ),
        )
    if (
        attribution.gross_return is not None
        and attribution.net_return is not None
        and attribution.gross_return > 0
        and attribution.net_return <= 0
    ):
        return (
            "review_execution_cost_sensitivity",
            (
                f"gross zero-cost replay return was {attribution.gross_return:.6f}",
                f"net modeled-cost return was {attribution.net_return:.6f}",
                "modeled execution effects erased the gross edge; review assumptions before changing strategy logic",
            ),
        )
    return (
        "no_change_recommended",
        (
            "saved experiment evidence does not justify an automatic strategy/configuration change",
            "proposal is advisory only and must be reviewed by a human",
        ),
    )
