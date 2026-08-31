"""M8 tests: CLI end-to-end behavior on synthetic data."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from backtest_engine import cli
from backtest_engine.data.store import write_clean
from backtest_engine.pipeline import discovery
from backtest_engine.strategy.result import BacktestResult


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
    assert "data_dir" in out
    assert "yf_retries" in out


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
    for option in (
        "--symbol",
        "--start",
        "--end",
        "--data-root",
        "--universe-root",
        "--universe-csv",
        "--synthetic",
    ):
        assert option in out


def test_cli_passes_explicit_universe_csv_to_shared_run_spec(tmp_path: Path, monkeypatch):
    universe_csv = tmp_path / "universe.csv"
    universe_csv.write_text("symbol,list_date,delist_date\nSPY,2018-01-03,\n")
    captured = {}

    def fake_run_spec(*args, **kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop after dispatch")

    monkeypatch.setattr(cli, "run_spec", fake_run_spec)

    with pytest.raises(RuntimeError, match="stop after dispatch"):
        cli.main(
            [
                "discover",
                "--strategy",
                "sma_cross",
                "--synthetic",
                "--universe-csv",
                str(universe_csv),
            ]
        )

    assert captured["universe"] == universe_csv


@pytest.mark.parametrize("command", ["discover", "replay"])
def test_cli_date_range_uses_universe_filtered_result_period(command, tmp_path: Path, monkeypatch):
    universe_csv = tmp_path / "universe.csv"
    universe_csv.write_text(
        "symbol,list_date,delist_date\nSPY,2018-01-04,2018-01-08\n", encoding="utf-8"
    )
    captured = {}

    class Adapter:
        def run(self, _signals, ohlc, **kwargs):
            equity = pd.Series(100.0, index=ohlc.index)
            return BacktestResult(
                run_id=kwargs["run_id"],
                strategy_name=kwargs["strategy_name"],
                engine="fake",
                params=kwargs["params"],
                capital=kwargs["capital"],
                cost_model=kwargs["cost_model"],
                universe_ref=kwargs["universe_ref"],
                equity=equity,
                returns=equity.pct_change().fillna(0.0),
            )

    def capture_report(result, _config):
        captured["result"] = result
        return SimpleNamespace(out_dir=tmp_path, html_path=tmp_path / "report.html")

    monkeypatch.setattr(discovery, "get_adapter", lambda _name: Adapter())
    monkeypatch.setattr(cli, "render_report", capture_report)

    assert (
        cli.main(
            [
                command,
                "--strategy",
                "sma_cross",
                "--synthetic",
                "--days",
                "10",
                "--universe-csv",
                str(universe_csv),
            ]
        )
        == 0
    )

    result = captured["result"]
    assert result.metadata["date_range"] == {
        "start": "2018-01-04T00:00:00+00:00",
        "end": "2018-01-05T00:00:00+00:00",
    }


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


def test_cli_replay_reports_missing_real_data(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["replay", "--strategy", "sma_cross", "--data-root", str(tmp_path / "data")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "No clean data for symbol SPY" in err


@pytest.mark.smoke
def test_cli_replay_runs_native_engine(capsys):
    pytest.importorskip("nautilus_trader")
    rc = cli.main(
        ["replay", "--strategy", "sma_cross", "--synthetic", "--days", "500", "--seed", "1"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Engine: nautilus" in out


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
    assert (run_dir / "result.json").exists()
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "report.html").exists()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["stable"]["random_seed"] == 1
    assert manifest["stable"]["data"]["content_sha256"]
    assert str(tmp_path) not in json.dumps(manifest["stable"])
    assert any(
        json.loads(line)["run_id"] == run_id
        for line in (tmp_path / "outputs" / "experiments.jsonl").read_text().splitlines()
    )

    rc = cli.main(["report", "--run-id", run_id])
    assert rc == 0
    assert (run_dir / "report.html").exists()


@pytest.mark.smoke
def test_cli_report_reloads_complete_result_without_backtest(tmp_path: Path, capsys, monkeypatch):
    pytest.importorskip("vectorbt")
    monkeypatch.chdir(tmp_path)

    assert cli.main(["discover", "--strategy", "sma_cross", "--synthetic", "--days", "200"]) == 0
    run_id = next(
        line.split(": ", 1)[1]
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("Run id: ")
    )
    captured: dict[str, object] = {}

    def fake_report(result, cfg):
        captured["result"] = result
        return SimpleNamespace(
            out_dir=tmp_path / "outputs" / run_id, html_path=tmp_path / "report.html"
        )

    monkeypatch.setattr(cli, "render_report", fake_report)
    monkeypatch.setattr(cli, "run_spec", lambda *args, **kwargs: pytest.fail("backtest rerun"))

    assert cli.main(["report", "--run-id", run_id]) == 0
    loaded = captured["result"]
    assert loaded.run_id == run_id
    assert loaded.equity.index.tz is not None


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
