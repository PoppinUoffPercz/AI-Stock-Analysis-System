from __future__ import annotations

import argparse
from collections.abc import Sequence

from .cli import _load_legacy_module


def _result_code(result: object) -> int:
    return result if isinstance(result, int) else 0


def _legacy_call(
    module_name: str, label: str, function_name: str, *args, **kwargs
) -> int:
    try:
        module = _load_legacy_module(module_name)
        result = getattr(module, function_name)(*args, **kwargs)
    except (AttributeError, ImportError, ModuleNotFoundError) as exc:
        print(f"Unable to load {label} CLI component.", file=__import__("sys").stderr)
        if isinstance(exc, ModuleNotFoundError) and exc.name:
            print(f"Missing dependency: {exc.name}", file=__import__("sys").stderr)
        return 1
    return _result_code(result)


def _run_tracking_report(bot: str | None) -> int:
    return _legacy_call("report_card", "tracking report", "cmd_report", bot=bot)


def _run_tracking_feedback(interactive: bool) -> int:
    return _legacy_call(
        "feedback", "tracking feedback", "cmd_feedback", interactive=interactive
    )


def _run_tracking_daily_check() -> int:
    return _legacy_call("daily_check", "daily position check", "cmd_check")


def _run_tracking_show() -> int:
    return _legacy_call("main", "tracking", "main", ["tracker"])


def tracking_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stock-analysis tracking",
        description="Shared trade tracking commands.",
    )
    subparsers = parser.add_subparsers(dest="command")

    report = subparsers.add_parser("report", help="Generate a performance report")
    report.add_argument("--bot", choices=("scion", "omaha"), help="Filter by bot")

    feedback = subparsers.add_parser("feedback", help="Generate strategy feedback")
    feedback.add_argument("--no-interactive", action="store_true", help="Skip prompts")

    subparsers.add_parser("daily-check", help="Run the daily position monitor")
    subparsers.add_parser("show", help="Show open positions")

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "report":
        return _run_tracking_report(args.bot)
    if args.command == "feedback":
        return _run_tracking_feedback(not args.no_interactive)
    if args.command == "daily-check":
        return _run_tracking_daily_check()
    return _run_tracking_show()


def _run_credit_status() -> int:
    try:
        module = _load_legacy_module("credit_monitor")
        pulse, _score, _label, _components = module.CreditMonitor().quick_pulse()
    except (AttributeError, ImportError, ModuleNotFoundError) as exc:
        print("Unable to load credit-monitor component.", file=__import__("sys").stderr)
        if isinstance(exc, ModuleNotFoundError) and exc.name:
            print(f"Missing dependency: {exc.name}", file=__import__("sys").stderr)
        return 1
    print(pulse)
    return 0


def credit_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stock-analysis credit",
        description="Credit market status commands.",
    )
    parser.add_argument("command", choices=("status",), nargs="?")
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return _run_credit_status()


def portfolio_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stock-analysis portfolio",
        description="Shared portfolio commands.",
    )
    parser.add_argument("command", choices=("combined",), nargs="?")
    parser.add_argument("--notify", action="store_true", help="Send a WhatsApp alert")
    parser.add_argument("--recipient", help="WhatsApp chat ID")
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    legacy_args = []
    if args.notify:
        legacy_args.append("--notify")
    if args.recipient:
        legacy_args.extend(["--recipient", args.recipient])
    legacy_args.append("combined")
    return _legacy_call("buffett_main", "combined portfolio", "main", legacy_args)


def _run_debate(symbol: str, compile_only: bool) -> int:
    function_name = "cmd_compile" if compile_only else "cmd_debate"
    return _legacy_call("debate", "debate", function_name, symbol)


def debate_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stock-analysis debate",
        description="Bull/Bear/Judge debate commands.",
    )
    parser.add_argument("symbol", nargs="?")
    parser.add_argument(
        "--compile", action="store_true", help="Compile existing agent files"
    )
    args = parser.parse_args(argv)
    if args.symbol is None:
        parser.print_help()
        return 0
    return _run_debate(args.symbol, args.compile)
