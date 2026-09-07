from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from stock_analysis.config import configured_outputs_root

from .artifacts import ArtifactStore
from .workflow import run_offline_checkpoint


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock-analysis intelligence",
        description="Deterministic intelligence checkpoint and artifact inspection.",
    )
    subparsers = parser.add_subparsers(dest="command")
    checkpoint = subparsers.add_parser(
        "checkpoint", help="Run the network-free frozen-data intelligence checkpoint"
    )
    checkpoint.add_argument(
        "--degraded", action="store_true", help="Disable depth/options capabilities"
    )
    checkpoint.add_argument(
        "--json", action="store_true", help="Emit a machine-readable summary"
    )
    show = subparsers.add_parser("show", help="Reload one saved intelligence artifact")
    show.add_argument("path", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "show":
        value = ArtifactStore(args.path.parent, mode="research").load_path(args.path)
        print(repr(value))
        return 0

    root = configured_outputs_root("outputs") / "intelligence-checkpoint"
    result = run_offline_checkpoint(root, degraded=args.degraded)
    summary = {
        "mode": "research_fixture_degraded" if args.degraded else "research_fixture",
        "as_of": result.analytics.as_of.isoformat(),
        "symbol": result.analytics.symbol,
        "regime": result.regime.label.value,
        "candidate_count": len(result.screen.candidates),
        "top_candidate": (
            None
            if not result.screen.candidates
            else {
                "symbol": result.screen.candidates[0].symbol,
                "family": result.screen.candidates[0].family.value,
                "direction": result.screen.candidates[0].direction.value,
                "ranking_score": result.screen.candidates[0].ranking_score,
            }
        ),
        "risk_status": None if result.risk is None else result.risk.status.value,
        "degraded_reasons": list(result.degraded_reasons),
        "artifacts": {
            name: str(reference.path) for name, reference in result.artifacts.items()
        },
    }
    if args.json:
        print(json.dumps(summary, sort_keys=True, allow_nan=False))
    else:
        print(f"Fixture checkpoint: {summary['symbol']} at {summary['as_of']}")
        print(f"Regime: {summary['regime']}; candidates: {summary['candidate_count']}")
        print(f"Risk: {summary['risk_status'] or 'not evaluated'}")
        for reason in summary["degraded_reasons"]:
            print(f"Unavailable/degraded: {reason}")
        print(f"Artifacts: {root}")
    return 0
