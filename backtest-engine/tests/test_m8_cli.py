"""M8 tests: CLI end-to-end behavior on synthetic data."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from backtest_engine import cli
from backtest_engine.data.store import write_clean


def _write_cli_fixture(root: Path, symbol: str = "TEST") -> None:
    index = pd.bdate_range("2020-01-01", periods=200).tz_localize("UTC")
    close = pd.Series(100.0 + pd.RangeIndex(len(index)).to_numpy(), index=index, dtype="float64")
    frame = pd.DataFrame(
        {
            "timestamp": index,
            "open": close.to_numpy(),
            "high": close.to_numpy() + 1.0,
            "low": close.to_numpy() - 1.0,
            "close": close.to_numpy(),
            "volume": 1_000_000.0,
        }
    )
    write_clean(frame, root / "clean", symbol=symbol, source="fixture")


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


def test_cli_backtest_help_documents_real_data_options(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["discover", "--help"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    for option in ("--symbol", "--start", "--end", "--data-root", "--universe-root", "--synthetic"):
        assert option in out


@pytest.mark.smoke
def test_cli_discover_reads_persisted_clean_data(tmp_path: Path, capsys, monkeypatch):
    pytest.importorskip("vectorbt")
    monkeypatch.chdir(tmp_path)
    _write_cli_fixture(tmp_path / "data")

    rc = cli.main(
        [
            "discover",
            "--strategy",
            "sma_cross",
            "--symbol",
            "TEST",
            "--data-root",
            str(tmp_path / "data"),
            "--universe-root",
            str(tmp_path / "universe"),
            "--start",
            "2020-01-01",
            "--end",
            "2020-10-01",
        ]
    )

    assert rc == 0
    assert "Data: TEST" in capsys.readouterr().out


def test_cli_real_backtest_reports_missing_clean_data(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)

    rc = cli.main(
        [
            "discover",
            "--strategy",
            "sma_cross",
            "--symbol",
            "MISSING",
            "--data-root",
            str(tmp_path / "data"),
        ]
    )

    assert rc == 1
    assert "No clean data for symbol MISSING" in capsys.readouterr().err


def test_cli_replay_returns_stub_message(capsys):
    rc = cli.main(["replay"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "not implemented" in err


@pytest.mark.smoke
def test_cli_discover_runs_full_pipeline(capsys):
    pytest.importorskip("vectorbt")
    rc = cli.main(
        ["discover", "--strategy", "sma_cross", "--synthetic", "--days", "200", "--seed", "1"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Run id:" in out
    assert "Engine: vectorbt" in out
    assert '"sharpe"' in out


@pytest.mark.smoke
def test_cli_run_then_report_persists_artifacts(tmp_path: Path, capsys, monkeypatch):
    pytest.importorskip("vectorbt")
    monkeypatch.chdir(tmp_path)

    rc = cli.main(
        ["discover", "--strategy", "sma_cross", "--synthetic", "--days", "200", "--seed", "1"]
    )
    assert rc == 0
    run_output = capsys.readouterr().out
    run_id = next(
        line.split(": ", 1)[1] for line in run_output.splitlines() if line.startswith("Run id: ")
    )
    run_dir = tmp_path / "outputs" / run_id

    assert (run_dir / "metrics.json").exists()
    assert (run_dir / "report.html").exists()

    rc = cli.main(["report", "--run-id", run_id])
    assert rc == 0
    assert (run_dir / "report.html").exists()


@pytest.mark.smoke
def test_cli_validate_runs_backtrader(capsys):
    pytest.importorskip("backtrader")
    rc = cli.main(
        ["validate", "--strategy", "rsi_reversion", "--synthetic", "--days", "200", "--seed", "5"]
    )
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
