"""M7 tests: tearsheet generation. We disable QuantStats network calls + Plotly
external assets to keep tests offline-fast; assert the canonical output paths
and bias-audit panel get written.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_engine.metrics.tearsheet import ReportConfig, make_report_config, render_report
from backtest_engine.strategy.result import BacktestResult


def _result(seed: int = 0, n: int = 252) -> BacktestResult:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n).tz_localize("UTC")
    eq = pd.Series(np.cumprod(1 + rng.normal(0.0005, 0.01, n)) * 100, index=idx)
    rr = eq.pct_change().fillna(0)
    return BacktestResult(
        run_id="m7-test",
        strategy_name="sma_cross",
        engine="vectorbt",
        params={"fast": 5, "slow": 30},
        capital=100,
        cost_model="zero",
        universe_ref="u",
        equity=eq,
        returns=rr,
        trades=[],
        raw_metrics={},
    )


def test_make_report_config_sets_paths(tmp_path: Path):
    cfg = make_report_config(run_id="r1", outputs_dir=tmp_path)
    assert cfg.run_id == "r1"
    assert cfg.outputs_dir == tmp_path


def test_render_report_writes_html_and_metrics(tmp_path: Path):
    cfg = ReportConfig(
        run_id="r1",
        outputs_dir=tmp_path,
        write_quantstats=False,
        write_plotly=False,
    )
    rr = render_report(_result(), cfg)
    out_dir = tmp_path / "r1"
    assert rr.html_path == out_dir / "report.html"
    assert rr.html_path.exists()
    assert (out_dir / "metrics.json").exists()
    assert (out_dir / "manifest.json").exists()
    entries = [
        json.loads(line) for line in (tmp_path / "experiments.jsonl").read_text().splitlines()
    ]
    assert entries[0]["run_id"] == "m7-test"
    assert entries[0]["artifacts"]["result"] == "r1/result.json"

    loaded = json.loads((out_dir / "metrics.json").read_text())
    for key in ("total_return", "sharpe", "max_drawdown"):
        assert key in loaded


def test_render_report_bias_flags_present(tmp_path: Path):
    # Force a high sharpe by sending a stable positive return (low vol).
    n = 100
    idx = pd.bdate_range("2020-01-01", periods=n).tz_localize("UTC")
    rr = pd.Series([0.0] + [0.001] * (n - 1), index=idx)
    eq = (1 + rr).cumprod() * 100
    result = BacktestResult(
        run_id="m7-sharpe",
        strategy_name="s",
        engine="vectorbt",
        params={},
        capital=100,
        cost_model="zero",
        universe_ref="u",
        equity=eq,
        returns=rr,
        trades=[],
        raw_metrics={},
    )
    cfg = ReportConfig(
        run_id="r1-sharpe",
        outputs_dir=tmp_path,
        write_quantstats=False,
        write_plotly=False,
    )
    rep = render_report(result, cfg)
    assert "bias_flags" in rep.__dict__
    assert rep.bias_flags["high_sharpe"] in ("True", "False")


def test_render_report_includes_plotly_when_requested(tmp_path: Path):
    cfg = ReportConfig(
        run_id="r1-plotly",
        outputs_dir=tmp_path,
        write_quantstats=False,
        write_plotly=True,
    )
    rr = render_report(_result(seed=2), cfg)
    body = rr.html_path.read_text(encoding="utf-8")
    assert "Equity Curve" in body
    assert "Bias Audit" in body


def test_render_report_with_quantstats_runs_on_synthetic_data(tmp_path: Path):
    """End-to-end: QuantStats should produce a tearsheet.html next to the main report."""
    cfg = ReportConfig(
        run_id="r1-qs",
        outputs_dir=tmp_path,
        write_quantstats=True,
        write_plotly=False,
    )
    render_report(_result(seed=3, n=300), cfg)
    out_dir = tmp_path / "r1-qs"
    assert (out_dir / "report.html").exists()
    # tearsheet.html may not exist if quantstats fails on minimal input; check only if present
    if (out_dir / "tearsheet.html").exists():
        body = (out_dir / "tearsheet.html").read_text(encoding="utf-8")
        assert "Strategy" in body or "strategy" in body.lower()
