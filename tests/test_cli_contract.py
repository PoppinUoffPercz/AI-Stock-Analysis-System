from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "stock_analysis", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_root_help_lists_initial_namespaces() -> None:
    result = run_cli("--help")

    assert result.returncode == 0, result.stderr
    assert "scion" in result.stdout
    assert "omaha" in result.stdout
    assert "backtest" in result.stdout


def test_synthetic_backtest_is_available_through_root_cli() -> None:
    result = run_cli(
        "backtest",
        "discover",
        "--strategy",
        "sma_cross",
        "--synthetic",
        "--days",
        "200",
        "--seed",
        "42",
        "--cost",
        "zero",
    )

    assert result.returncode == 0, result.stderr
    assert "Run id:" in result.stdout
    assert "Data: SPY (synthetic)" in result.stdout
