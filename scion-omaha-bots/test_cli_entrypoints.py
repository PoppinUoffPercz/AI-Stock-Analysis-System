from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

BOT_ROOT = Path(__file__).resolve().parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

import buffett_main as omaha_main  # noqa: E402 - import legacy wrapper after test path setup
import main as scion_main  # noqa: E402 - import legacy wrapper after test path setup


def test_scion_build_parser_accepts_existing_commands() -> None:
    parser = scion_main.build_parser()

    args = parser.parse_args(["--watchlist", "LULU,PFE", "analyze", "PFE"])

    assert args.command == "analyze"
    assert args.symbol == "PFE"
    assert args.watchlist == "LULU,PFE"


def test_omaha_build_parser_accepts_existing_commands() -> None:
    parser = omaha_main.build_parser()

    args = parser.parse_args(["--watchlist", "KO,PG", "trim", "KO", "--pct", "25"])

    assert args.command == "trim"
    assert args.symbol == "KO"
    assert args.pct == 25


def test_bot_main_accepts_an_explicit_argv(monkeypatch) -> None:
    monkeypatch.setattr(scion_main, "cmd_screener", lambda args: None)
    monkeypatch.setattr(omaha_main, "cmd_screener", lambda args: None)

    assert scion_main.main(["screener"]) == 0
    assert omaha_main.main(["screener"]) == 0


def test_scion_parser_import_does_not_load_yfinance() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            'import sys; import main; assert "yfinance" not in sys.modules',
        ],
        cwd=BOT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_omaha_parser_import_does_not_load_yfinance() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            'import sys; import buffett_main; assert "yfinance" not in sys.modules',
        ],
        cwd=BOT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_scion_add_rejection_does_not_send_success_notification(monkeypatch) -> None:
    import scion_omaha_bots.notify as notify
    import scion_omaha_bots.portfolio as portfolio
    import yfinance as yf

    class FakeManager:
        def open_position(self, **kwargs):
            return {"action": "REJECTED", "reason": "fixture rejection"}

        def get_portfolio_summary(self):
            return "fixture summary"

    monkeypatch.setattr(portfolio, "ScionPortfolioManager", FakeManager)
    monkeypatch.setattr(
        yf,
        "Ticker",
        lambda symbol: SimpleNamespace(
            history=lambda **kwargs: pd.DataFrame({"Close": [100.0]})
        ),
    )
    monkeypatch.setattr(
        notify,
        "ScionNotifier",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("notification should not send")),
    )

    scion_main.cmd_add(
        SimpleNamespace(
            symbol="TEST",
            score=0,
            reasons="",
            notify=True,
            recipient=None,
        )
    )


def test_omaha_add_rejection_does_not_send_success_notification(monkeypatch) -> None:
    import scion_omaha_bots.buffett_portfolio as portfolio
    import scion_omaha_bots.notify as notify
    import yfinance as yf

    class FakeManager:
        def open_position(self, **kwargs):
            return {"action": "REJECTED", "reason": "fixture rejection"}

        def get_portfolio_summary(self):
            return "fixture summary"

    monkeypatch.setattr(portfolio, "BuffettPortfolioManager", FakeManager)
    monkeypatch.setattr(
        yf,
        "Ticker",
        lambda symbol: SimpleNamespace(
            history=lambda **kwargs: pd.DataFrame({"Close": [100.0]}),
            info={},
        ),
    )
    monkeypatch.setattr(
        notify,
        "ScionNotifier",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("notification should not send")),
    )

    omaha_main.cmd_add(
        SimpleNamespace(
            symbol="TEST",
            score=0,
            reasons="",
            notify=True,
            recipient=None,
        )
    )


def test_omaha_trim_skip_does_not_send_success_notification(monkeypatch) -> None:
    import scion_omaha_bots.buffett_portfolio as portfolio
    import scion_omaha_bots.notify as notify

    class FakeManager:
        positions = {"TEST": {"shares": 1}}

        def get_current_price(self, symbol):
            return 100.0

        def trim_position(self, *args, **kwargs):
            return {"action": "SKIP", "reason": "No shares to trim"}

        def get_portfolio_summary(self):
            return "fixture summary"

    monkeypatch.setattr(portfolio, "BuffettPortfolioManager", FakeManager)
    monkeypatch.setattr(
        notify,
        "ScionNotifier",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("notification should not send")),
    )

    omaha_main.cmd_trim(
        SimpleNamespace(
            symbol="TEST",
            pct=25.0,
            reason="",
            notify=True,
            recipient=None,
        )
    )
