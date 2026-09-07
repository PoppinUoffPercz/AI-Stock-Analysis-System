"""Shared CLI mechanics used by both bot entrypoints."""

from __future__ import annotations


def cmd_log_entry(args, *, bot: str) -> None:
    from scion_omaha_bots.tracker import Tracker

    Tracker().log_entry(
        ticker=args.symbol,
        bot=bot,
        entry_price=args.entry,
        stop_loss=args.stop,
        target1=args.t1,
        target2=args.t2,
        score=args.score,
        thesis=args.thesis,
    )


def cmd_log_exit(args) -> None:
    from scion_omaha_bots.tracker import Tracker

    Tracker().log_exit(
        ticker=args.symbol,
        exit_price=args.exit,
        exit_reason=args.reason,
    )


def cmd_report(args) -> None:
    from scion_omaha_bots.report_card import cmd_report as report

    report(bot=args.bot)


def cmd_feedback(args) -> None:
    from scion_omaha_bots.feedback import cmd_feedback as feedback

    feedback(interactive=not args.no_interactive)


def cmd_daily_check(args) -> None:
    from scion_omaha_bots.daily_check import cmd_check

    cmd_check()


def cmd_tracker(args) -> None:
    from scion_omaha_bots.tracker import Tracker

    open_positions = Tracker().get_open_positions_summary()
    if not open_positions:
        print("  No open positions.")
        return
    print(
        f"\n  {'Ticker':<8} {'Bot':<8} {'Entry':>8} {'Current':>9} {'P&L%':>7} "
        f"{'Days':>5} {'StopDist%':>10} {'T1Dist%':>9} {'Score':>5}"
    )
    print("  " + "-" * 75)
    for position in open_positions:
        stop_distance = (
            f"{position['distance_to_stop_pct']:+.1f}%"
            if position["distance_to_stop_pct"] is not None
            else "N/A"
        )
        target_distance = (
            f"{position['distance_to_target1_pct']:+.1f}%"
            if position["distance_to_target1_pct"] is not None
            else "N/A"
        )
        print(
            f"  {position['ticker']:<8} {position['bot']:<8} "
            f"${position['entry_price']:<6.2f} ${position['current_price']:<7.2f} "
            f"{position['pnl_pct']:+.2f}% {position['days_held']:>4}d "
            f"{stop_distance:>9} {target_distance:>8} {position['score']:>5}"
        )
