"""M8 tests: CLI end-to-end behavior on synthetic data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backtest_engine import cli


def test_cli_settings(capsys):
    rc = cli.main(["settings"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "default_capital" in out


def test_cli_lists_strategies(capsys):
    rc = cli.main(["strats"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "sma_cross" in out
    assert "rsi_reversion" in out


def test_cli_replay_returns_stub_message(capsys):
    rc = cli.main(["replay"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "not implemented" in err


@pytest.mark.smoke
def test_cli_discover_runs_full_pipeline(capsys):
    pytest.importorskip("vectorbt")
    rc = cli.main(["discover", "--strategy", "sma_cross", "--days", "200", "--seed", "1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Run id:" in out
    assert "Engine: vectorbt" in out
    assert '"sharpe"' in out


@pytest.mark.smoke
def test_cli_validate_runs_backtrader(capsys):
    pytest.importorskip("backtrader")
    rc = cli.main(["validate", "--strategy", "rsi_reversion", "--days", "200", "--seed", "5"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Engine: backtrader" in out


def test_cli_report_requires_existing_run(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outputs").mkdir(parents=True, exist_ok=True)
    rc = cli.main(["report", "--run-id", "nonexistent"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "No metrics.json" in err


def test_cli_report_writes_html_when_metrics_exist(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "outputs" / "r-test"
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {"total_return": 0.10, "sharpe": 0.5}
    (run_dir / "metrics.json").write_text(json.dumps(payload))
    rc = cli.main(["report", "--run-id", "r-test"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Report written to" in out
    html_body = (run_dir / "report.html").read_text()
    assert "0.1" in html_body or "0.10" in html_body
