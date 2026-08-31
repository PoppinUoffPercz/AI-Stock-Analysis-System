"""Tearsheet generator (plan section 7).

We compose the QuantStats report when available, then wrap it with a bias-audit
panel + a Plotly equity/drawdown dashboard. The output is saved to
`outputs/<run_id>/report.html`.

Decisions:
  - QuantStats is the primary tearsheet renderer. Its `reports.html()` writes a
    fully-formed HTML with equity curve, drawdown underwater plot, monthly
    returns heatmap, distribution, and ratio panel.
  - The bias-audit panel is rendered as a small Plotly figure appended in an
    extra HTML block called from the tearsheet.
  - All outputs land under `outputs/<run_id>/` per plan section 3.1.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_engine.metrics.core import attach_metric_panel, bias_audit
from backtest_engine.strategy.persistence import persist_result


@dataclass
class ReportConfig:
    run_id: str
    outputs_dir: Path
    write_quantstats: bool = True  # set False in tests to avoid network/matplotlib
    write_plotly: bool = True
    extra_fields: dict = field(default_factory=dict)


@dataclass
class ReportResult:
    run_id: str
    out_dir: Path
    html_path: Path | None
    metrics: dict
    bias_flags: dict


def render_report(
    result,  # BacktestResult
    cfg: ReportConfig,
) -> ReportResult:
    """Generate the canonical HTML report for one backtest run.

    Args:
      result: BacktestResult
      cfg: ReportConfig (run_id + outputs_dir + flags)

    Returns:
      ReportResult with paths + the bias-audit panel + metrics dict.
    """
    metrics = {
        key: value if np.isfinite(value) else 0.0
        for key, value in attach_metric_panel(result).items()
    }
    flags = bias_audit(metrics)
    result.metrics = metrics

    out_dir = Path(cfg.outputs_dir) / cfg.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    persist_result(result, out_dir, metrics=metrics)

    html_path: Path | None = None

    # --- QuantStats core tearsheet -------------------------------------------
    if cfg.write_quantstats:
        try:
            import quantstats as qs  # noqa: PLC0415 - lazy

            # QuantStats expects a returns Series with a tz-naive DatetimeIndex.
            rets = result.returns.copy()
            if rets.index.tz is not None:
                rets.index = rets.index.tz_convert("UTC").tz_localize(None)
            qs_path = out_dir / "tearsheet.html"
            qs.reports.html(
                rets, title=f"{result.strategy_name} ({result.engine})", output=str(qs_path)
            )
        except Exception:  # noqa: BLE001 - tearsheet is best-effort in CI
            qs_path = None
    else:
        qs_path = None

    # --- Plotly extra panels --------------------------------------------------
    panels_html = ""
    if cfg.write_plotly:
        try:
            eq = result.equity
            equity_fig = _equity_figure(eq)
            bias_fig = _bias_flags_figure(flags)
            panels_html = (
                f"<h2>Equity Curve</h2>{equity_fig.to_html(full_html=False, include_plotlyjs='cdn')}"
                f"<h2>Bias Audit</h2>{bias_fig.to_html(full_html=False, include_plotlyjs=False)}"
            )
        except Exception:  # noqa: BLE001 - plotly optional in tests
            panels_html = ""

    # --- Compose final HTML ---------------------------------------------------
    html_path = out_dir / "report.html"
    body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Backtest Report - {cfg.run_id}</title></head>
<body>
<h1>Backtest Report - {cfg.run_id}</h1>
<h2>Metrics</h2>
<pre>{json.dumps({k: float(v) if isinstance(v, (int, float, np.floating)) else str(v) for k, v in metrics.items()}, indent=2)}</pre>
<h2>Bias audit flags</h2>
<pre>{json.dumps({k: str(v) for k, v in flags.items()}, indent=2)}</pre>
{panels_html}
"""
    if qs_path is not None and qs_path.exists():
        body += f'<p><a href="{qs_path.name}">Full QuantStats tearsheet</a></p>\n'
    body += "</body></html>\n"
    html_path.write_text(body, encoding="utf-8")

    # Also dump the raw metrics as JSON for downstream / validation layer.
    (out_dir / "metrics.json").write_text(
        json.dumps(
            {
                k: float(v) if isinstance(v, (int, float, np.floating)) else str(v)
                for k, v in metrics.items()
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return ReportResult(
        run_id=cfg.run_id,
        out_dir=out_dir,
        html_path=html_path,
        metrics=metrics,
        bias_flags={k: str(v) for k, v in flags.items()},
    )


def _equity_figure(eq: pd.Series):
    import plotly.graph_objects as go  # noqa: PLC0415

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=eq.index, y=eq.values, mode="lines", name="Equity"))
    fig.update_layout(margin={"l": 40, "r": 20, "t": 30, "b": 30})
    return fig


def _bias_flags_figure(flags: dict):
    import plotly.graph_objects as go  # noqa: PLC0415

    keys = [k for k in flags if k != "any_flag"]
    vals = [1 if str(flags[k]).startswith("True") else 0 for k in keys]
    fig = go.Figure(
        data=[go.Bar(x=keys, y=vals, marker_color=["red" if v else "green" for v in vals])]
    )
    fig.update_layout(title="Bias audit flags (red = triggered)", height=300)
    return fig


def make_report_config(*, run_id: str, outputs_dir: Path | str, **extra) -> ReportConfig:
    return ReportConfig(
        run_id=run_id,
        outputs_dir=Path(outputs_dir),
        extra_fields=extra,
    )
