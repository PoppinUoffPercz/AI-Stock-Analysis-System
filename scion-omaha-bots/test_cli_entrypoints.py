from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BOT_ROOT = Path(__file__).resolve().parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

import buffett_main as omaha_main
import main as scion_main


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
