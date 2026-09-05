"""
Performance Dashboard Generator

Reads trades.csv and daily_pnl.csv from tracker.py,
computes win rates, R:R, score bucketing, sector breakdown,
and writes a markdown report to the Obsidian vault.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tracker import Tracker

VAULT_DIR = os.path.join(os.path.expanduser("~"),
    "OneDrive", "Documents", "Obsidian Vault",
    "Stock Research", "Performance")


def _ensure_vault_dir():
    os.makedirs(VAULT_DIR, exist_ok=True)
    return VAULT_DIR


def _fmt_pct(val):
    if val is None:
        return "N/A"
    return f"{val:+.2f}%"


def _fetch_benchmark_return(benchmark, entry_date, exit_date):
    """Fetch buy-and-hold return for a benchmark index over a date range."""
    if not entry_date or not exit_date:
        return None
    try:
        import yfinance as yf
        b = yf.Ticker(benchmark)
        start = datetime.datetime.strptime(entry_date, "%Y-%m-%d")
        end = datetime.datetime.strptime(exit_date, "%Y-%m-%d") + datetime.timedelta(days=5)
        hist = b.history(start=entry_date, end=end.strftime("%Y-%m-%d"))
        if len(hist) < 2:
            return None
        return float((hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0])
    except Exception:
        return None


def compute_alpha_for_trade(entry_price, exit_price, entry_date, exit_date):
    """Compute alpha = trade return - benchmark return over the same period."""
    trade_return = (exit_price - entry_price) / entry_price
    bench_return = _fetch_benchmark_return("SPY", entry_date, exit_date)
    if bench_return is None:
        return trade_return, None
    return trade_return, trade_return - bench_return


def compute_metrics(tracker, bot=None):
    """Compute all performance metrics from closed trades."""
    closed = tracker.get_closed_trades(bot=bot)
    open_pos = tracker.get_open_positions_summary()

    total_closed = len(closed)
    if total_closed == 0:
        return {
            "total_closed": 0,
            "total_open": len(open_pos),
            "wins": 0, "losses": 0, "win_rate": None,
            "avg_rr": None, "avg_hold_wins": None, "avg_hold_losses": None,
            "total_pnl_pct": None,
            "score_buckets": {},
            "sector_perf": {},
            "open_positions": open_pos,
            "closed_trades": [],
        }

    wins = [r for r in closed if float(r.get("pnl_pct", 0)) > 0]
    losses = [r for r in closed if float(r.get("pnl_pct", 0)) <= 0]

    win_rate = len(wins) / total_closed * 100 if total_closed > 0 else 0

    # Alpha calculation per trade
    alpha_trades = []
    total_alpha = 0.0
    alpha_count = 0
    for r in closed:
        entry = float(r.get("entry_price", 0))
        exit_p = float(r.get("exit_price", 0))
        ed = r.get("entry_date", "")
        xd = r.get("exit_date", "")
        trade_ret, alpha = compute_alpha_for_trade(entry, exit_p, ed, xd)
        r["_alpha"] = round(alpha * 100, 2) if alpha is not None else None
        r["_trade_return"] = round(trade_ret * 100, 2)
        if alpha is not None:
            total_alpha += alpha
            alpha_count += 1

    cumulative_alpha = round(total_alpha * 100, 2) if alpha_count > 0 else None

    avg_rr = None
    if wins and losses:
        avg_win = sum(float(r["pnl_pct"]) for r in wins) / len(wins)
        avg_loss = abs(sum(float(r["pnl_pct"]) for r in losses)) / len(losses)
        avg_rr = round(avg_win / avg_loss, 2) if avg_loss > 0 else None

    days_wins = [int(r.get("days_held", 0)) for r in wins if r.get("days_held")]
    days_losses = [int(r.get("days_held", 0)) for r in losses if r.get("days_held")]

    total_pnl = sum(float(r.get("pnl_pct", 0)) for r in closed)
    total_pnl = round(total_pnl, 2)

    # Score buckets
    score_buckets = {}
    for r in closed:
        s = r.get("score", "0")
        try:
            s = int(s)
        except (ValueError, TypeError):
            s = 0
        if s >= 80:
            bucket = "80-100"
        elif s >= 50:
            bucket = "50-79"
        elif s >= 25:
            bucket = "25-49"
        else:
            bucket = "0-24"
        score_buckets.setdefault(bucket, {"trades": 0, "wins": 0, "total_pnl": 0.0})
        score_buckets[bucket]["trades"] += 1
        score_buckets[bucket]["total_pnl"] += float(r.get("pnl_pct", 0))
        if float(r.get("pnl_pct", 0)) > 0:
            score_buckets[bucket]["wins"] += 1

    for bucket, data in score_buckets.items():
        data["win_rate"] = round(data["wins"] / data["trades"] * 100, 1) if data["trades"] > 0 else 0
        data["total_pnl"] = round(data["total_pnl"], 2)

    # Sector performance
    sector_perf = {}
    for r in closed:
        sec = r.get("sector", "Unknown")
        sector_perf.setdefault(sec, {"trades": 0, "wins": 0, "total_pnl": 0.0})
        sector_perf[sec]["trades"] += 1
        sector_perf[sec]["total_pnl"] += float(r.get("pnl_pct", 0))
        if float(r.get("pnl_pct", 0)) > 0:
            sector_perf[sec]["wins"] += 1

    for sec, data in sector_perf.items():
        data["win_rate"] = round(data["wins"] / data["trades"] * 100, 1) if data["trades"] > 0 else 0
        data["total_pnl"] = round(data["total_pnl"], 2)

    # Also include open positions in sector perf
    for p in open_pos:
        sec = p.get("sector", "Unknown")
        sector_perf.setdefault(sec, {"trades": 0, "wins": 0, "total_pnl": 0.0, "open": 0})
        sector_perf[sec]["open"] = sector_perf[sec].get("open", 0) + 1

    return {
        "total_closed": total_closed,
        "total_open": len(open_pos),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "avg_rr": avg_rr,
        "avg_hold_wins": round(sum(days_wins) / len(days_wins), 1) if days_wins else None,
        "avg_hold_losses": round(sum(days_losses) / len(days_losses), 1) if days_losses else None,
        "total_pnl_pct": total_pnl,
        "score_buckets": dict(sorted(score_buckets.items(), reverse=True)),
        "sector_perf": dict(sorted(sector_perf.items(), key=lambda x: x[1]["total_pnl"], reverse=True)),
        "open_positions": open_pos,
        "closed_trades": closed,
        "cumulative_alpha": cumulative_alpha,
        "alpha_count": alpha_count,
    }


def generate_markdown_report(tracker, bot=None):
    metrics = compute_metrics(tracker, bot=bot)
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    bot_label = bot.upper() if bot else "ALL BOTS"

    lines = []
    lines.append("---")
    lines.append(f'title: "Performance Report — {today}"')
    lines.append(f"date: {today}")
    lines.append("tags:")
    lines.append("  - performance")
    lines.append("  - report")
    if bot:
        lines.append(f"  - {bot}")
    lines.append("---")
    lines.append("")
    lines.append(f"# Performance Report — {today}")
    lines.append(f"> **Agent:** {bot_label} | **Report generated:** {datetime.datetime.now().strftime('%H:%M')}")
    lines.append("")

    # Summary section
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| :--- | :--- |")
    lines.append(f"| **Trades Closed** | {metrics['total_closed']} |")
    lines.append(f"| **Positions Open** | {metrics['total_open']} |")
    if metrics['win_rate'] is not None:
        lines.append(f"| **Win Rate** | {metrics['win_rate']}% ({metrics['wins']}W / {metrics['losses']}L) |")
    else:
        lines.append("| **Win Rate** | N/A (no closed trades) |")
    lines.append(f"| **Total Return (Closed)** | {_fmt_pct(metrics['total_pnl_pct'])} |")
    if metrics.get('cumulative_alpha') is not None:
        lines.append(f"| **Cumulative Alpha vs SPY** | {_fmt_pct(metrics['cumulative_alpha'])} |")
    if metrics['avg_rr']:
        lines.append(f"| **Avg R:R (Wins/Losses)** | 1:{metrics['avg_rr']} |")
    if metrics['avg_hold_wins']:
        lines.append(f"| **Avg Hold (Wins)** | {metrics['avg_hold_wins']} days |")
    if metrics['avg_hold_losses']:
        lines.append(f"| **Avg Hold (Losses)** | {metrics['avg_hold_losses']} days |")
    lines.append("")

    # Open positions table
    lines.append("## Open Positions")
    lines.append("")
    if metrics["open_positions"]:
        lines.append("| Ticker | Bot | Entry | Current | P&L% | Days | Stop | Target 1 | Target 2 | Score |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        blinker = "🔴" if bot else ""
        for p in sorted(metrics["open_positions"], key=lambda x: x["pnl_pct"]):
            pnl_str = f"{p['pnl_pct']:+.2f}%"
            lines.append(f"| **{p['ticker']}** | {p['bot']} | ${p['entry_price']:.2f} | ${p['current_price']:.2f} | {pnl_str} | {p['days_held']}d | ${p['stop_loss']:.2f} | ${p['target_1']:.2f} | ${p['target_2']:.2f} | {p['score']} |")
    else:
        lines.append("_No open positions._")
    lines.append("")

    # Score bucket analysis
    if metrics["score_buckets"]:
        lines.append("## Score Bucket Analysis")
        lines.append("")
        lines.append("| Score Range | Trades | Wins | Losses | Win Rate | Total Return |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for bucket, data in metrics["score_buckets"].items():
            losses = data["trades"] - data["wins"]
            wr = f"{data['win_rate']}%"
            lines.append(f"| {bucket} | {data['trades']} | {data['wins']} | {losses} | {wr} | {_fmt_pct(data['total_pnl'])} |")
        lines.append("")

    # Sector breakdown
    if metrics["sector_perf"]:
        lines.append("## Sector Breakdown")
        lines.append("")
        lines.append("| Sector | Closed | Open | Wins | Losses | Win Rate | Total Return |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for sec, data in metrics["sector_perf"].items():
            closed_count = data["trades"]
            open_count = data.get("open", 0)
            losses = data["trades"] - data["wins"]
            wr = f"{data['win_rate']}%" if data["trades"] > 0 else "N/A"
            ret = _fmt_pct(data["total_pnl"]) if data["trades"] > 0 else "N/A"
            open_str = f" +{open_count} open" if open_count else ""
            lines.append(f"| {sec} | {closed_count}{open_str} | — | {data['wins']} | {losses} | {wr} | {ret} |")
        lines.append("")

    # Closed trades table
    if metrics["closed_trades"]:
        lines.append("## Closed Trades")
        lines.append("")
        lines.append("| Ticker | Bot | Entry | Exit | P&L% | Alpha vs SPY | Days | Reason | Score |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for r in sorted(metrics["closed_trades"], key=lambda x: x.get("exit_date", ""), reverse=True):
            pnl = float(r.get("pnl_pct", 0))
            alpha_str = _fmt_pct(r.get("_alpha")) if r.get("_alpha") is not None else "N/A"
            lines.append(f"| {r['ticker']} | {r['bot']} | ${r['entry_price']} | ${r['exit_price']} | {pnl:+.2f}% | {alpha_str} | {r['days_held']}d | {r['exit_reason']} | {r['score']} |")
        lines.append("")

    lines.append("---")
    lines.append(f"*Report generated at {datetime.datetime.now().strftime('%H:%M')}. Data from tracker.py.*")
    lines.append("")

    report = "\n".join(lines)
    filepath = os.path.join(_ensure_vault_dir(), f"{today} Performance Report.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  Report saved: {filepath}")
    return report


def cmd_report(bot=None):
    tracker = Tracker()
    return generate_markdown_report(tracker, bot=bot)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Performance Report")
    parser.add_argument("--bot", type=str, help="Filter by bot (scion, omaha)")
    args = parser.parse_args()

    cmd_report(bot=args.bot)
