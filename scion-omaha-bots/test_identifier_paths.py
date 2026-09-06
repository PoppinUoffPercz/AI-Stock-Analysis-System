"""Identifiers must not become paths, including during debate cleanup."""

from datetime import UTC, datetime
from types import SimpleNamespace

import analyzer
import buffett_analyzer
import debate
import pytest


@pytest.mark.parametrize("symbol", ["X/../../ESCAPE", r"X\..\..\ESCAPE"])
@pytest.mark.parametrize("analyzer_type", [analyzer.ScionAnalyzer, buffett_analyzer.BuffettAnalyzer])
def test_analysis_report_rejects_unsafe_symbol_before_fetch(analyzer_type, symbol, monkeypatch):
    instance = analyzer_type.__new__(analyzer_type)
    instance.symbol = symbol
    monkeypatch.setattr(
        instance, "fetch_all_data", lambda: pytest.fail("unsafe symbol reached market-data fetch")
    )

    with pytest.raises(ValueError, match="invalid identifier"):
        instance.generate_full_report()


@pytest.mark.parametrize("ticker", ["X/../../ESCAPE", r"X\..\..\ESCAPE"])
def test_debate_prepare_rejects_unsafe_ticker_before_fetch(ticker, monkeypatch):
    monkeypatch.setattr(
        debate, "fetch_debate_data", lambda _: pytest.fail("unsafe ticker reached market-data fetch")
    )

    with pytest.raises(ValueError, match="invalid identifier"):
        debate.cmd_prepare(ticker)


@pytest.mark.parametrize("ticker", ["X/../../ESCAPE", r"X\..\..\ESCAPE"])
def test_debate_report_rejects_traversal_before_read_or_write(ticker, tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    (reports / "debate_bull_X").mkdir(parents=True)
    (reports / "2026-09-04 X").mkdir()
    outside = tmp_path / "ESCAPE.md"
    outside.write_text("outside sentinel", encoding="utf-8")
    monkeypatch.setattr(debate, "DEBATE_DIR", str(reports))
    monkeypatch.setattr(
        debate, "datetime", SimpleNamespace(datetime=SimpleNamespace(now=lambda: datetime(2026, 9, 4, tzinfo=UTC)))
    )
    monkeypatch.setattr(debate, "_ensure_vault_dir", lambda: str(reports))
    monkeypatch.setattr(debate, "get_data_summary", lambda _: "")

    with pytest.raises(ValueError, match="invalid identifier"):
        debate.compile_report(ticker)

    assert outside.read_text(encoding="utf-8") == "outside sentinel"
    assert not (tmp_path / "ESCAPE Debate.md").exists()


@pytest.mark.parametrize("ticker", ["X/../../ESCAPE", r"X\..\..\ESCAPE"])
def test_debate_cleanup_rejects_traversal_before_deletion(ticker, tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    for prefix in ("data", "bull", "bear", "judge"):
        (reports / f"debate_{prefix}_X").mkdir(parents=True)
    outside = tmp_path / "ESCAPE.json"
    outside.write_text("outside sentinel", encoding="utf-8")
    monkeypatch.setattr(debate, "DEBATE_DIR", str(reports))
    monkeypatch.setattr(debate, "compile_report", lambda _: None)
    monkeypatch.setattr(debate, "get_debate_score", lambda _: None)

    with pytest.raises(ValueError, match="invalid identifier"):
        debate.cmd_compile(ticker)

    assert outside.read_text(encoding="utf-8") == "outside sentinel"


def test_valid_debate_identifier_round_trip(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setattr(debate, "DEBATE_DIR", str(tmp_path))
    monkeypatch.setattr(debate, "_ensure_vault_dir", lambda: str(reports))
    monkeypatch.setattr(debate, "fetch_debate_data", lambda ticker: {"ticker": ticker})
    monkeypatch.setattr(debate, "get_debate_score", lambda _: None)

    debate.cmd_prepare("BRK.B")
    assert (tmp_path / "debate_data_BRK.B.json").is_file()
    (tmp_path / "debate_bull_BRK.B.md").write_text("fixture bull case", encoding="utf-8")
    debate.cmd_compile("BRK.B")

    report = next(reports.glob("* BRK.B Debate.md"))
    assert "fixture bull case" in report.read_text(encoding="utf-8")
    assert not (tmp_path / "debate_data_BRK.B.json").exists()
    assert not (tmp_path / "debate_bull_BRK.B.md").exists()
