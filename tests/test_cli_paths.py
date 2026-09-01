from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from stock_analysis.config import AppPaths

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def test_app_paths_resolve_relative_cli_values_from_cwd(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    paths = AppPaths.from_args(
        project_root=ROOT,
        state_root=Path("state"),
        data_root=Path("market-data"),
        outputs_root=Path("reports"),
    )

    assert paths.state_root == tmp_path / "state"
    assert paths.data_root == tmp_path / "market-data"
    assert paths.outputs_root == tmp_path / "reports"


def test_app_paths_apply_exports_legacy_path_defaults(tmp_path, monkeypatch) -> None:
    paths = AppPaths.from_args(
        project_root=ROOT,
        state_root=tmp_path / "state",
        data_root=tmp_path / "data",
        outputs_root=tmp_path / "outputs",
    )

    environment: dict[str, str] = {}
    paths.apply(environment)

    assert environment["STOCK_ANALYSIS_STATE_ROOT"] == str(tmp_path / "state")
    assert environment["STOCK_ANALYSIS_DATA_ROOT"] == str(tmp_path / "data")
    assert environment["STOCK_ANALYSIS_OUTPUTS_ROOT"] == str(tmp_path / "outputs")


def test_integrated_backtest_writes_to_configured_output_root(tmp_path) -> None:
    data_root = tmp_path / "market-data"
    outputs_root = tmp_path / "reports"
    result = subprocess.run(
        [
            PYTHON,
            "-m",
            "stock_analysis",
            "--state-root",
            str(tmp_path / "state"),
            "--data-root",
            str(data_root),
            "--outputs-root",
            str(outputs_root),
            "backtest",
            "discover",
            "--strategy",
            "sma_cross",
            "--synthetic",
            "--days",
            "20",
            "--seed",
            "42",
            "--cost",
            "zero",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    run_line = next(
        line for line in result.stdout.splitlines() if line.startswith("Run id: ")
    )
    run_id = run_line.removeprefix("Run id: ")
    result_path = outputs_root / run_id / "result.json"
    assert result_path.is_file()
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["data_root"] == str(data_root)


def test_legacy_state_modules_read_configured_state_root(tmp_path) -> None:
    probe = """
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ[\"STOCK_ANALYSIS_BOT_ROOT\"])

import buffett_news_engine
import buffett_portfolio
import credit_monitor
import news_engine
import performance_tracker
import portfolio
import reflection
import tracker

state_root = Path(os.environ[\"STOCK_ANALYSIS_STATE_ROOT\"])
assert Path(portfolio.PORTFOLIO_FILE) == state_root / \"portfolio.json\"
assert Path(buffett_portfolio.PORTFOLIO_FILE) == state_root / \"buffett_portfolio.json\"
assert Path(tracker.TRADES_FILE) == state_root / \"trades.csv\"
assert Path(performance_tracker.PERF_FILE) == state_root / \"performance_log.csv\"
assert Path(reflection.REFLECTION_FILE) == state_root / \"reflection_log.json\"
assert news_engine.NewsEngine()._state_file == str(state_root / \"news_state.json\")
assert buffett_news_engine.BuffettNewsEngine()._state_file == str(state_root / \"buffett_news_state.json\")
assert credit_monitor.CreditMonitor().state_file == str(state_root / \"credit_state.json\")
"""
    env = os.environ.copy()
    env["STOCK_ANALYSIS_BOT_ROOT"] = str(ROOT / "scion-omaha-bots")
    env["STOCK_ANALYSIS_STATE_ROOT"] = str(tmp_path / "state")
    result = subprocess.run(
        [PYTHON, "-c", probe],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
