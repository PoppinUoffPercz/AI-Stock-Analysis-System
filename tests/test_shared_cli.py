from __future__ import annotations

from types import SimpleNamespace


def test_tracking_report_forwards_bot_filter(monkeypatch) -> None:
    from stock_analysis import shared_cli

    calls = []

    def runner(bot: str | None) -> int:
        calls.append(bot)
        return 0

    monkeypatch.setattr(shared_cli, "_run_tracking_report", runner)

    assert shared_cli.tracking_main(["report", "--bot", "omaha"]) == 0
    assert calls == ["omaha"]


def test_tracking_feedback_forwards_non_interactive_flag(monkeypatch) -> None:
    from stock_analysis import shared_cli

    calls = []

    def runner(interactive: bool) -> int:
        calls.append(interactive)
        return 0

    monkeypatch.setattr(shared_cli, "_run_tracking_feedback", runner)

    assert shared_cli.tracking_main(["feedback", "--no-interactive"]) == 0
    assert calls == [False]


def test_debate_forwards_ticker_and_compile_flag(monkeypatch) -> None:
    from stock_analysis import shared_cli

    calls = []

    def runner(symbol: str, compile_only: bool) -> int:
        calls.append((symbol, compile_only))
        return 0

    monkeypatch.setattr(shared_cli, "_run_debate", runner)

    assert shared_cli.debate_main(["AAPL", "--compile"]) == 0
    assert calls == [("AAPL", True)]


def test_research_requires_and_forwards_explicit_bot(monkeypatch) -> None:
    from stock_analysis import shared_cli

    calls = []

    def runner(bot: str) -> int:
        calls.append(bot)
        return 0

    monkeypatch.setattr(shared_cli, "_run_research", runner)

    assert shared_cli.research_main(["run", "--bot", "scion"]) == 0
    assert calls == ["scion"]


def test_research_delegates_to_selected_package_runner(monkeypatch) -> None:
    from stock_analysis import shared_cli

    calls = []

    def runner(args: list[str]) -> int:
        calls.append(args)
        return 4

    monkeypatch.setattr(
        shared_cli,
        "_load_bot_package",
        lambda: SimpleNamespace(omaha_main=runner),
    )

    assert shared_cli._run_research("omaha") == 4
    assert calls == [["run"]]
