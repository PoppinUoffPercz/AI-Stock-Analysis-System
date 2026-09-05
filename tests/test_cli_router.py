from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_root(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "stock_analysis", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_root_router_forwards_scion_arguments(monkeypatch) -> None:
    from stock_analysis import cli

    calls = []

    def runner(args: list[str]) -> int:
        calls.append(args)
        return 7

    monkeypatch.setattr(cli, "_run_scion", runner)

    assert cli.main(["scion", "analyze", "PFE"]) == 7
    assert calls == [["analyze", "PFE"]]


def test_root_router_forwards_omaha_arguments(monkeypatch) -> None:
    from stock_analysis import cli

    calls = []

    def runner(args: list[str]) -> None:
        calls.append(args)

    monkeypatch.setattr(cli, "_run_omaha", runner)

    assert cli.main(["omaha", "--watchlist", "KO,PG", "run"]) == 0
    assert calls == [["--watchlist", "KO,PG", "run"]]


@pytest.mark.parametrize(
    ("runner_name", "dispatch"),
    [("scion_main", "_run_scion"), ("omaha_main", "_run_omaha")],
)
def test_bot_dispatch_uses_packaged_runner(monkeypatch, runner_name, dispatch) -> None:
    from stock_analysis import cli

    calls = []

    def runner(args: list[str]) -> int:
        calls.append(args)
        return 6

    monkeypatch.setattr(
        cli,
        "_load_bot_package",
        lambda: SimpleNamespace(**{runner_name: runner}),
    )

    assert getattr(cli, dispatch)(["--probe"]) == 6
    assert calls == [["--probe"]]


def test_root_router_forwards_backtest_arguments(monkeypatch) -> None:
    from stock_analysis import cli

    calls = []

    def runner(args: list[str]) -> int:
        calls.append(args)
        return 3

    monkeypatch.setattr(cli, "_run_backtest", runner)

    assert cli.main(["backtest", "strats"]) == 3
    assert calls == [["strats"]]


def test_root_router_forwards_tracking_arguments(monkeypatch) -> None:
    from stock_analysis import cli

    calls = []

    def runner(args: list[str]) -> int:
        calls.append(args)
        return 0

    monkeypatch.setattr(cli, "_run_tracking", runner)

    assert cli.main(["tracking", "report", "--bot", "scion"]) == 0
    assert calls == [["report", "--bot", "scion"]]


def test_root_router_forwards_credit_arguments(monkeypatch) -> None:
    from stock_analysis import cli

    calls = []

    def runner(args: list[str]) -> int:
        calls.append(args)
        return 0

    monkeypatch.setattr(cli, "_run_credit", runner)

    assert cli.main(["credit", "status"]) == 0
    assert calls == [["status"]]


def test_root_router_forwards_debate_arguments(monkeypatch) -> None:
    from stock_analysis import cli

    calls = []

    def runner(args: list[str]) -> int:
        calls.append(args)
        return 0

    monkeypatch.setattr(cli, "_run_debate", runner)

    assert cli.main(["debate", "AAPL", "--compile"]) == 0
    assert calls == [["AAPL", "--compile"]]


def test_root_router_forwards_research_arguments(monkeypatch) -> None:
    from stock_analysis import cli

    calls = []

    def runner(args: list[str]) -> int:
        calls.append(args)
        return 0

    monkeypatch.setattr(cli, "_run_research", runner)

    assert cli.main(["research", "run", "--bot", "omaha"]) == 0
    assert calls == [["run", "--bot", "omaha"]]


def test_root_router_without_namespace_prints_help(capsys) -> None:
    from stock_analysis import cli

    assert cli.main([]) == 0
    assert "scion" in capsys.readouterr().out


def test_unknown_namespace_uses_argparse_error() -> None:
    from stock_analysis import cli

    with pytest.raises(SystemExit) as error:
        cli.main(["unknown"])

    assert error.value.code == 2


def test_root_import_is_lazy() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            'import sys; import stock_analysis.cli; assert "pandas" not in sys.modules; assert "yfinance" not in sys.modules; assert "backtest_engine.cli" not in sys.modules',
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "namespace",
    [
        "scion",
        "omaha",
        "backtest",
        "portfolio",
        "tracking",
        "credit",
        "debate",
        "research",
    ],
)
def test_namespace_help_is_available_offline(namespace: str) -> None:
    result = run_root(namespace, "--help")

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
