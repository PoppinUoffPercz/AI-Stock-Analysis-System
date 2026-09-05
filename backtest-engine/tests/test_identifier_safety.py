"""Regression tests for identifiers that become filesystem path components."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from backtest_engine import cli
from backtest_engine.data.store import read_clean, write_clean
from backtest_engine.identifiers import validate_identifier
from backtest_engine.metrics.tearsheet import ReportConfig, render_report
from backtest_engine.strategy.result import BacktestResult


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.DatetimeIndex(["2024-01-02T00:00:00Z"]),
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1_000.0],
        }
    )


def _result(run_id: str = "run-20260904-abc123") -> BacktestResult:
    index = pd.DatetimeIndex(["2024-01-02T00:00:00Z"])
    equity = pd.Series([100.0], index=index)
    return BacktestResult(
        run_id=run_id,
        strategy_name="strategy_01",
        engine="vectorbt",
        params={},
        capital=100.0,
        cost_model="zero",
        universe_ref="fixture",
        equity=equity,
        returns=equity.pct_change().fillna(0.0),
    )


@pytest.mark.parametrize(
    "value",
    [
        "../escape",
        "..\\escape",
        "foo/bar",
        "foo\\bar",
        ".",
        "..",
        "",
        "/absolute",
        r"C:\absolute",
        "C:relative",
        "bad\x00name",
    ],
)
def test_validate_identifier_rejects_unsafe_path_components(value: str):
    with pytest.raises(ValueError, match="identifier"):
        validate_identifier(value)


@pytest.mark.parametrize(
    "value",
    ["AAPL", "BRK.B", "SPY", "run-20260904-abc123", "strategy_01"],
)
def test_validate_identifier_accepts_expected_identifiers(value: str):
    assert validate_identifier(value) == value


@pytest.mark.parametrize("symbol", ["../escape", "..\\escape"])
def test_market_data_symbol_cannot_escape_clean_root(tmp_path: Path, symbol: str):
    clean_root = tmp_path / "clean"

    with pytest.raises(ValueError, match="symbol"):
        write_clean(_frame(), clean_root, symbol=symbol, source="fixture")

    assert not (tmp_path / "escape").exists()


def test_valid_symbol_still_round_trips_under_clean_root(tmp_path: Path):
    clean_root = tmp_path / "clean"

    paths = write_clean(_frame(), clean_root, symbol="BRK.B", source="fixture")
    loaded = read_clean(clean_root, "BRK.B")

    assert paths == [clean_root / "BRK.B" / "2024.parquet"]
    assert loaded["close"].tolist() == [100.5]


def test_report_run_id_cannot_escape_outputs_root(tmp_path: Path):
    outputs_root = tmp_path / "outputs"
    cfg = ReportConfig(
        run_id="../escape",
        outputs_dir=outputs_root,
        write_quantstats=False,
        write_plotly=False,
    )

    with pytest.raises(ValueError, match="run_id"):
        render_report(_result(), cfg)

    assert not (tmp_path / "escape").exists()


def test_cli_report_rejects_path_traversal_before_read_or_write(
    tmp_path: Path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    escaped = tmp_path / "escape"
    escaped.mkdir()
    (escaped / "metrics.json").write_text(json.dumps({"total_return": 0.1}), encoding="utf-8")

    rc = cli.main(["report", "--run-id", "../escape"])

    assert rc == 1
    assert "run_id" in capsys.readouterr().err
    assert not (escaped / "report.html").exists()


def test_valid_report_run_id_stays_under_outputs_root(tmp_path: Path):
    outputs_root = tmp_path / "outputs"
    run_id = "run-20260904-abc123"
    cfg = ReportConfig(
        run_id=run_id,
        outputs_dir=outputs_root,
        write_quantstats=False,
        write_plotly=False,
    )

    report = render_report(_result(run_id), cfg)

    assert report.out_dir == outputs_root / run_id
    assert report.html_path == outputs_root / run_id / "report.html"
    assert report.html_path.exists()
