from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Sequence
from pathlib import Path

from .config import AppPaths

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BOT_ROOT = PROJECT_ROOT / "scion-omaha-bots"
BOT_PACKAGE_SOURCE_ROOT = BOT_ROOT / "src"
BACKTEST_SOURCE_ROOT = PROJECT_ROOT / "backtest-engine" / "src"
NAMESPACES = {
    "scion",
    "omaha",
    "backtest",
    "portfolio",
    "tracking",
    "credit",
    "debate",
    "research",
}
GLOBAL_PATH_OPTIONS = {"--state-root", "--data-root", "--outputs-root"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock-analysis",
        description="Integrated Scion, Omaha, and backtest command line interface.",
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        help="Directory for bot state and tracking files",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        help="Directory for persisted market data",
    )
    parser.add_argument(
        "--outputs-root",
        type=Path,
        help="Directory for backtest reports and artifacts",
    )
    subparsers = parser.add_subparsers(dest="namespace")

    for name, help_text in (
        ("scion", "Run the Scion swing-trading bot"),
        ("omaha", "Run the Omaha quality-compounder bot"),
        ("backtest", "Run the backtest engine"),
        ("portfolio", "Run shared portfolio commands"),
        ("tracking", "Run shared tracking commands"),
        ("credit", "Run credit-monitor commands"),
        ("debate", "Run Bull/Bear/Judge debate commands"),
        ("research", "Run one selected research bot"),
    ):
        subparsers.add_parser(name, help=help_text)

    return parser


def _result_code(result: object) -> int:
    return result if isinstance(result, int) else 0


def _find_namespace_index(raw_args: list[str]) -> int | None:
    index = 0
    while index < len(raw_args):
        token = raw_args[index]
        if token in NAMESPACES:
            return index
        if token in GLOBAL_PATH_OPTIONS:
            index += 2
            continue
        if any(token.startswith(f"{option}=") for option in GLOBAL_PATH_OPTIONS):
            index += 1
            continue
        return None
    return None


def _apply_global_paths(raw_args: list[str], namespace_index: int) -> None:
    args = build_parser().parse_args(raw_args[: namespace_index + 1])
    AppPaths.from_args(
        project_root=PROJECT_ROOT,
        state_root=args.state_root,
        data_root=args.data_root,
        outputs_root=args.outputs_root,
    ).apply()


def _load_legacy_module(module_name: str):
    bot_root = str(BOT_ROOT)
    if bot_root not in sys.path:
        sys.path.insert(0, bot_root)
    return importlib.import_module(module_name)


def _load_bot_package():
    package_root = str(BOT_PACKAGE_SOURCE_ROOT)
    if package_root not in sys.path:
        sys.path.insert(0, package_root)
    return importlib.import_module("scion_omaha_bots")


def _run_packaged_bot(runner_name: str, label: str, domain_args: list[str]) -> int:
    try:
        package = _load_bot_package()
        runner = getattr(package, runner_name)
    except (AttributeError, ImportError, ModuleNotFoundError) as exc:
        print(f"Unable to load {label} CLI component.", file=sys.stderr)
        print(
            f"Expected installation/source location: {BOT_PACKAGE_SOURCE_ROOT}",
            file=sys.stderr,
        )
        if isinstance(exc, ModuleNotFoundError) and exc.name:
            print(f"Missing dependency: {exc.name}", file=sys.stderr)
        return 1
    return _result_code(runner(domain_args))


def _run_scion(domain_args: list[str]) -> int:
    return _run_packaged_bot("scion_main", "Scion", domain_args)


def _run_omaha(domain_args: list[str]) -> int:
    return _run_packaged_bot("omaha_main", "Omaha", domain_args)


def _run_shared(runner_name: str, domain_args: list[str]) -> int:
    try:
        module = importlib.import_module("stock_analysis.shared_cli")
        runner = getattr(module, runner_name)
    except (AttributeError, ImportError, ModuleNotFoundError) as exc:
        print("Unable to load shared CLI component.", file=sys.stderr)
        print(
            "Expected installation/source location: stock_analysis/shared_cli.py",
            file=sys.stderr,
        )
        if isinstance(exc, ModuleNotFoundError) and exc.name:
            print(f"Missing dependency: {exc.name}", file=sys.stderr)
        return 1

    return _result_code(runner(domain_args))


def _run_portfolio(domain_args: list[str]) -> int:
    return _run_shared("portfolio_main", domain_args)


def _run_tracking(domain_args: list[str]) -> int:
    return _run_shared("tracking_main", domain_args)


def _run_credit(domain_args: list[str]) -> int:
    return _run_shared("credit_main", domain_args)


def _run_debate(domain_args: list[str]) -> int:
    return _run_shared("debate_main", domain_args)


def _run_research(domain_args: list[str]) -> int:
    return _run_shared("research_main", domain_args)


def _print_backtest_help() -> None:
    print("usage: stock-analysis backtest <command> [options]")
    print()
    print(
        "Commands: settings, strats, ingest, compare, discover, validate, report, replay"
    )
    print("Use stock-analysis backtest <command> --help for command options.")


def _run_backtest(domain_args: list[str]) -> int:
    if domain_args in (["--help"], ["-h"]):
        _print_backtest_help()
        return 0

    try:
        source_root = str(BACKTEST_SOURCE_ROOT)
        if source_root not in sys.path:
            sys.path.insert(0, source_root)
        module = importlib.import_module("backtest_engine.cli")
        runner = module.main
    except (AttributeError, ImportError, ModuleNotFoundError) as exc:
        print("Unable to load Backtest Engine CLI component.", file=sys.stderr)
        print(
            f"Expected installation/source location: {BACKTEST_SOURCE_ROOT}",
            file=sys.stderr,
        )
        if isinstance(exc, ModuleNotFoundError) and exc.name:
            print(f"Missing dependency: {exc.name}", file=sys.stderr)
        return 1

    return _result_code(runner(domain_args))


def main(argv: Sequence[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    namespace_index = _find_namespace_index(raw_args)
    if namespace_index is not None:
        _apply_global_paths(raw_args, namespace_index)
        namespace = raw_args[namespace_index]
        domain_args = raw_args[namespace_index + 1 :]
        if namespace == "scion":
            return _result_code(_run_scion(domain_args))
        if namespace == "omaha":
            return _result_code(_run_omaha(domain_args))
        if namespace == "portfolio":
            return _result_code(_run_portfolio(domain_args))
        if namespace == "tracking":
            return _result_code(_run_tracking(domain_args))
        if namespace == "credit":
            return _result_code(_run_credit(domain_args))
        if namespace == "debate":
            return _result_code(_run_debate(domain_args))
        if namespace == "research":
            return _result_code(_run_research(domain_args))
        return _result_code(_run_backtest(domain_args))

    parser = build_parser()
    args = parser.parse_args(raw_args)

    if args.namespace is None:
        parser.print_help()
        return 0
