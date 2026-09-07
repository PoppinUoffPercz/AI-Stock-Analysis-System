"""Offline responsive dashboard for persisted research and simulated-paper state."""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from stock_analysis.intelligence.models import (
    CostAttribution,
    ReviewProposal,
    RiskDecision,
)
from stock_analysis.market_analytics.streaming import IngestionHealth
from stock_analysis.paper import PaperAccountSnapshot, ReconciliationReport
from stock_analysis.persistence import atomic_write_text


class DashboardState(StrEnum):
    LOADING = "loading"
    READY = "ready"
    EMPTY = "empty"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    state: DashboardState
    as_of: datetime | None = None
    intelligence_refs: dict[str, dict[str, object]] = field(default_factory=dict)
    experiment: dict[str, Any] | None = None
    attribution: CostAttribution | None = None
    review: ReviewProposal | None = None
    risk: RiskDecision | None = None
    paper: PaperAccountSnapshot | None = None
    reconciliation: ReconciliationReport | None = None
    ingestion: IngestionHealth | None = None
    errors: dict[str, str] = field(default_factory=dict)


def render_dashboard(snapshot: DashboardSnapshot, output_path: str | Path) -> Path:
    """Render a complete static dashboard atomically; no network or live APIs are used."""
    target = Path(output_path)
    body = _state_body(snapshot)
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stock Analysis Research Dashboard</title>
  <style>
    :root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
    body {{ margin: 0; padding: 1rem; max-width: 1200px; margin-inline: auto; line-height: 1.4; }}
    header {{ border: 2px solid currentColor; padding: 1rem; margin-bottom: 1rem; }}
    .banner {{ font-weight: 800; letter-spacing: .04em; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }}
    .card {{ border: 1px solid currentColor; border-radius: .5rem; padding: 1rem; overflow-wrap: anywhere; }}
    .wide {{ grid-column: 1 / -1; }}
    .status {{ font-weight: 700; text-transform: uppercase; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; vertical-align: top; padding: .35rem; border-bottom: 1px solid currentColor; }}
    code {{ white-space: normal; overflow-wrap: anywhere; }}
    ul {{ padding-left: 1.25rem; }}
    @media (max-width: 700px) {{
      body {{ padding: .6rem; }}
      .grid {{ grid-template-columns: 1fr; }}
      .card, .wide {{ grid-column: 1; }}
      table {{ font-size: .9rem; }}
    }}
  </style>
</head>
<body data-dashboard-state="{html.escape(snapshot.state.value)}">
  <header>
    <div class="banner">SIMULATED / RESEARCH ONLY — LIVE TRADING IS NOT IMPLEMENTED</div>
    <div>Review proposals are read-only and never apply configuration or place orders.</div>
  </header>
  {body}
</body>
</html>
"""
    atomic_write_text(target, document)
    return target


def _state_body(snapshot: DashboardSnapshot) -> str:
    if snapshot.state is DashboardState.LOADING:
        return '<section class="card wide" aria-live="polite"><h2>Loading</h2><p>Loading saved dashboard data…</p></section>'
    if snapshot.state is DashboardState.EMPTY:
        return '<section class="card wide"><h2>No data</h2><p>No persisted research or paper-simulation data is available.</p></section>'
    if snapshot.state is DashboardState.ERROR:
        return _error_cards(
            snapshot.errors or {"dashboard": "Dashboard data could not be loaded."}
        )

    sections = [
        _overview(snapshot),
        _intelligence(snapshot.intelligence_refs),
        _experiment(snapshot.experiment),
        _attribution(snapshot.attribution),
        _review(snapshot.review),
        _risk(snapshot.risk),
        _paper(snapshot.paper),
        _reconciliation(snapshot.reconciliation),
        _ingestion(snapshot.ingestion),
    ]
    if snapshot.errors:
        sections.append(_error_cards(snapshot.errors))
    return '<main class="grid">' + "".join(sections) + "</main>"


def _overview(snapshot: DashboardSnapshot) -> str:
    as_of = "Unavailable" if snapshot.as_of is None else snapshot.as_of.isoformat()
    return _card("Overview", f"<p><strong>As of:</strong> {_e(as_of)}</p>", wide=True)


def _intelligence(refs: dict[str, dict[str, object]]) -> str:
    if not refs:
        return _card(
            "Intelligence provenance", _missing("No saved intelligence references.")
        )
    rows = []
    for role, reference in sorted(refs.items()):
        rows.append(
            "<tr>"
            f"<td>{_e(role)}</td><td>{_e(reference.get('kind'))}</td>"
            f"<td><code>{_e(reference.get('identity'))}</code></td>"
            f"<td>{_e(reference.get('schema_version'))}</td>"
            "</tr>"
        )
    table = (
        "<table><thead><tr><th>Role</th><th>Kind</th><th>Identity</th><th>Schema</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )
    return _card("Intelligence provenance", table, wide=True)


def _experiment(record: dict[str, Any] | None) -> str:
    if record is None:
        return _card("Experiment", _missing("No indexed experiment loaded."))
    fields = ("run_id", "identity_hash", "strategy", "engine", "data_hash")
    body = "".join(
        f"<p><strong>{_e(name)}:</strong> <code>{_e(record.get(name))}</code></p>"
        for name in fields
    )
    return _card("Experiment", body)


def _attribution(value: CostAttribution | None) -> str:
    if value is None:
        return _card(
            "Gross / cost / net attribution", _missing("Attribution is unavailable.")
        )
    body = (
        _metric("Gross return", value.gross_return)
        + _metric("Gross P&L", value.gross_pnl)
        + _metric("Modeled costs", value.modeled_total_cost)
        + _metric("Net return", value.net_return)
        + _metric("Net P&L", value.net_pnl)
        + f"<p><strong>Cost basis:</strong> {_e(value.cost_basis)}</p>"
    )
    if value.unavailable_cost_components:
        body += (
            "<p><strong>Unavailable / not modeled:</strong> "
            + _e(", ".join(value.unavailable_cost_components))
            + "</p>"
        )
    return _card("Gross / cost / net attribution", body)


def _review(value: ReviewProposal | None) -> str:
    if value is None:
        return _card("Review proposal", _missing("No review proposal saved."))
    body = (
        f'<p class="status">{_e(value.execution_status)}</p>'
        f"<p><strong>Action:</strong> {_e(value.proposed_action)}</p>"
        + _list("Rationale", value.rationale)
        + _list("Sample warnings", value.sample_warnings)
    )
    return _card("Review proposal — read only", body)


def _risk(value: RiskDecision | None) -> str:
    if value is None:
        return _card(
            "Portfolio constraints", _missing("No portfolio-risk decision loaded.")
        )
    body = (
        f'<p class="status">{_e(value.status.value)}</p>'
        + _metric("Requested notional", value.requested_notional)
        + _metric("Approved notional", value.approved_notional)
        + _list("Binding constraints", value.binding_constraints)
        + _list("Reasons", value.reasons)
    )
    return _card("Portfolio constraints", body)


def _paper(value: PaperAccountSnapshot | None) -> str:
    if value is None:
        return _card(
            "Local paper execution", _missing("No local paper account state loaded.")
        )
    body = (
        '<p class="status">SIMULATED PAPER ACCOUNT</p>'
        + _metric("Cash", value.cash)
        + _metric("Equity", value.equity)
        + _metric("Fees", value.total_fees)
        + _metric("Realized P&L", value.realized_pnl)
        + _metric("Unrealized P&L", value.unrealized_pnl)
    )
    return _card("Local paper execution", body)


def _reconciliation(value: ReconciliationReport | None) -> str:
    if value is None:
        return _card("Reconciliation", _missing("No reconciliation report loaded."))
    body = f'<p class="status">{"OK" if value.ok else "DISCREPANCY"}</p>'
    if value.discrepancies:
        body += _list("Discrepancies", value.discrepancies)
    body += _metric("Expected cash", value.expected_cash) + _metric(
        "Actual cash", value.actual_cash
    )
    return _card("Reconciliation", body)


def _ingestion(value: IngestionHealth | None) -> str:
    if value is None:
        return _card(
            "Streaming ingestion health",
            _missing("No streaming-ingestion health loaded."),
        )
    body = "".join(
        _metric(name, field_value)
        for name, field_value in (
            ("Buffered", value.buffered),
            ("Accepted", value.accepted),
            ("Duplicates", value.duplicates),
            ("Late", value.late),
            ("Backpressure", value.backpressure),
            ("Recovered", value.recovered),
        )
    )
    if value.last_emitted_at is not None:
        body += f"<p><strong>Last emitted:</strong> {_e(value.last_emitted_at.isoformat())}</p>"
    return _card("Streaming ingestion health", body)


def _error_cards(errors: dict[str, str]) -> str:
    return "".join(
        _card(
            f"{section} failure",
            f'<p class="status">ERROR</p><p>{_e(message)}</p>',
            wide=True,
        )
        for section, message in sorted(errors.items())
    )


def _card(title: str, body: str, *, wide: bool = False) -> str:
    classes = "card wide" if wide else "card"
    return f'<section class="{classes}"><h2>{_e(title)}</h2>{body}</section>'


def _metric(name: str, value: object) -> str:
    rendered = "Unavailable" if value is None else str(value)
    return f"<p><strong>{_e(name)}:</strong> {_e(rendered)}</p>"


def _list(name: str, values: tuple[str, ...]) -> str:
    if not values:
        return f"<p><strong>{_e(name)}:</strong> None</p>"
    return (
        f"<p><strong>{_e(name)}:</strong></p><ul>"
        + "".join(f"<li>{_e(value)}</li>" for value in values)
        + "</ul>"
    )


def _missing(message: str) -> str:
    return f'<p class="status">UNAVAILABLE</p><p>{_e(message)}</p>'


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)
