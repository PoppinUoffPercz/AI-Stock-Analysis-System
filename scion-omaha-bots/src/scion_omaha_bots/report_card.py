"""
Performance Dashboard Generator

Reads trades.csv and daily_pnl.csv from tracker.py,
computes win rates, R:R, score bucketing, sector breakdown,
and writes a markdown report to the Obsidian vault.
"""
import datetime
import functools
import logging
import math
import os

from scion_omaha_bots.tracker import Tracker
from stock_analysis.config import configured_outputs_root

VAULT_DIR = os.path.join(os.path.expanduser("~"),
    "OneDrive", "Documents", "Obsidian Vault",
    "Stock Research", "Performance")


def _ensure_vault_dir():
    path = configured_outputs_root(VAULT_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _fmt_pct(val):
    if val is None:
        return "N/A"
    return f"{val:+.2f}%"


def _number(value):
    """CSV numeric fields may be strings; unavailable is never a fabricated zero."""
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) and not isinstance(value, bool) else None


@functools.lru_cache(maxsize=32)
def _fetch_benchmark_prices(benchmark, entry_date, exit_date):
    """Fetch one adjusted-close range; closed historical bars are cache-safe."""
    if not entry_date or not exit_date:
        return ()
    try:
        import yfinance as yf
        start = datetime.date.fromisoformat(entry_date)
        end = datetime.date.fromisoformat(exit_date)
        if start > end:
            return ()
        hist = yf.Ticker(benchmark).history(
            start=start.isoformat(), end=(end + datetime.timedelta(days=1)).isoformat(),
            auto_adjust=True,
        )
        return tuple(
            (timestamp.date().isoformat(), price)
            for timestamp, value in hist["Close"].items()
            if start <= timestamp.date() <= end and (price := _number(value)) is not None
        )
    except (ValueError, TypeError, KeyError, OSError) as exc:
        logging.getLogger(__name__).warning("Benchmark unavailable for %s %s..%s: %s", benchmark, entry_date, exit_date, exc)
        return ()


def _benchmark_return_from_prices(prices, entry_date, exit_date):
    first, last = prices.get(entry_date), prices.get(exit_date)
    if first is None or last is None or first <= 0 or last <= 0:
        return None
    return last / first - 1


def _fetch_benchmark_return(benchmark, entry_date, exit_date):
    """Adjusted close return on exactly the two trade dates; no future bars."""
    prices = dict(_fetch_benchmark_prices(benchmark, entry_date, exit_date))
    return _benchmark_return_from_prices(prices, entry_date, exit_date)


def compute_alpha_for_trade(entry_price, exit_price, entry_date, exit_date, benchmark_prices=None):
    """Return (price return, excess adjusted-SPY return), fractions or None."""
    entry, exit_p = _number(entry_price), _number(exit_price)
    if entry is None or exit_p is None or entry <= 0 or exit_p < 0:
        return None, None
    trade_return = exit_p / entry - 1
    if benchmark_prices is None:
        bench_return = _fetch_benchmark_return("SPY", entry_date, exit_date)
    else:
        bench_return = _benchmark_return_from_prices(benchmark_prices, entry_date, exit_date)
    return trade_return, None if bench_return is None else trade_return - bench_return


def compute_metrics(tracker, bot=None):
    """Trade statistics, not portfolio returns: the ledger has no invested notionals."""
    closed = [dict(row) for row in tracker.get_closed_trades(bot=bot)]
    open_pos = [p for p in tracker.get_open_positions_summary() if bot is None or p.get("bot") == bot]
    dated = []
    for row in closed:
        try:
            start = datetime.date.fromisoformat(row.get("entry_date", ""))
            end = datetime.date.fromisoformat(row.get("exit_date", ""))
        except (TypeError, ValueError):
            continue
        if start <= end:
            dated.append((start, end))
    benchmark_prices = None
    if dated:
        first = min(start for start, _ in dated).isoformat()
        last = max(end for _, end in dated).isoformat()
        benchmark_prices = dict(_fetch_benchmark_prices("SPY", first, last))
    for row in closed:
        ret, alpha = compute_alpha_for_trade(
            row.get("entry_price"), row.get("exit_price"), row.get("entry_date"), row.get("exit_date"),
            benchmark_prices=benchmark_prices,
        )
        row["_trade_return"] = None if ret is None else round(ret * 100, 2)
        row["_alpha"] = None if alpha is None else round(alpha * 100, 2)
    valid = [r for r in closed if r["_trade_return"] is not None]
    wins = [r for r in valid if r["_trade_return"] > 0]
    losses = [r for r in valid if r["_trade_return"] < 0]
    alphas = [r["_alpha"] for r in valid if r["_alpha"] is not None]
    payoff = None
    if wins and losses:
        payoff = round((sum(r["_trade_return"] for r in wins) / len(wins)) /
                       abs(sum(r["_trade_return"] for r in losses) / len(losses)), 2)

    def hold(rows):
        values = [_number(r.get("days_held")) for r in rows]
        values = [v for v in values if v is not None and v >= 0]
        return round(sum(values) / len(values), 1) if values else None

    def group(key):
        groups = {}
        for row in closed:
            data = groups.setdefault(key(row), {"trades": 0, "wins": 0, "losses": 0, "valid": 0, "total_pnl": None})
            data["trades"] += 1
            value = row["_trade_return"]
            if value is not None:
                data["valid"] += 1
                data["wins"] += int(value > 0)
                data["losses"] += int(value < 0)
                data["total_pnl"] = round((data["total_pnl"] or 0) + value, 2)
        for data in groups.values():
            data["win_rate"] = round(data["wins"] / data["valid"] * 100, 1) if data["valid"] else None
        return groups

    def score_bucket(row):
        value = _number(row.get("score"))
        if value is None or not 0 <= value <= 100:
            return "Unavailable"
        return "80-100" if value >= 80 else "50-79" if value >= 50 else "25-49" if value >= 25 else "0-24"

    sectors = group(lambda row: row.get("sector") or "Unknown")
    for row in open_pos:
        data = sectors.setdefault(row.get("sector") or "Unknown",
                                  {"trades": 0, "wins": 0, "losses": 0, "valid": 0, "total_pnl": None, "win_rate": None})
        data["open"] = data.get("open", 0) + 1
    return {
        "total_closed": len(closed), "total_open": len(open_pos),
        "wins": len(wins), "losses": len(losses), "breakeven": len(valid) - len(wins) - len(losses),
        "unavailable_trades": len(closed) - len(valid),
        "win_rate": round(len(wins) / len(valid) * 100, 1) if valid else None,
        "avg_rr": payoff, "avg_hold_wins": hold(wins), "avg_hold_losses": hold(losses),
        # Compatibility keys retain arithmetic sums; report labels state units explicitly.
        "total_pnl_pct": round(sum(r["_trade_return"] for r in valid), 2) if valid else None,
        "cumulative_alpha": round(sum(alphas), 2) if alphas else None,
        "alpha_count": len(alphas), "score_buckets": group(score_bucket), "sector_perf": sectors,
        "open_positions": open_pos, "closed_trades": closed,
        "provenance": {"source": "tracker closed-trade ledger", "units": "percentage points",
                       "formula": "sum of individual price returns; unweighted, non-compounded",
                       "portfolio_return_status": "unavailable: invested notional/equity history absent",
                       "benchmark": "Yahoo SPY adjusted close, one cached range per report, exact trade dates; missing dates unavailable"},
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
    lines.append(f"| **Sum of trade returns (pp)** | {_fmt_pct(metrics['total_pnl_pct'])} |")
    if metrics.get('cumulative_alpha') is not None:
        lines.append(f"| **Sum of matched excess returns vs SPY (pp)** | {_fmt_pct(metrics['cumulative_alpha'])} |")
    if metrics['avg_rr']:
        lines.append(f"| **Realized payoff (avg win / avg loss)** | {metrics['avg_rr']}:1 |")
    if metrics['avg_hold_wins']:
        lines.append(f"| **Avg Hold (Wins)** | {metrics['avg_hold_wins']} days |")
    if metrics['avg_hold_losses']:
        lines.append(f"| **Avg Hold (Losses)** | {metrics['avg_hold_losses']} days |")
    lines.append("")

    lines.append("Trade-return sums are unweighted percentage points, not portfolio return. Missing inputs are unavailable; SPY comparisons use exact trade dates.")
    lines.append(f"Unavailable trades: {metrics['unavailable_trades']}; breakeven: {metrics['breakeven']}; SPY matches: {metrics['alpha_count']}.")

    # Open positions table
    lines.append("## Open Positions")
    lines.append("")
    if metrics["open_positions"]:
        lines.append("| Ticker | Bot | Entry | Current | P&L% | Days | Stop | Target 1 | Target 2 | Score |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
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
        lines.append("| Score Range | Trades | Wins | Losses | Win Rate | Sum of returns (pp) |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for bucket, data in metrics["score_buckets"].items():
            losses = data["losses"]
            wr = f"{data['win_rate']}%"
            lines.append(f"| {bucket} | {data['trades']} | {data['wins']} | {losses} | {wr} | {_fmt_pct(data['total_pnl'])} |")
        lines.append("")

    # Sector breakdown
    if metrics["sector_perf"]:
        lines.append("## Sector Breakdown")
        lines.append("")
        lines.append("| Sector | Closed | Open | Wins | Losses | Win Rate | Sum of returns (pp) |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for sec, data in metrics["sector_perf"].items():
            closed_count = data["trades"]
            open_count = data.get("open", 0)
            losses = data["losses"]
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
            pnl = r.get("_trade_return")
            alpha_str = _fmt_pct(r.get("_alpha")) if r.get("_alpha") is not None else "N/A"
            lines.append(f"| {r['ticker']} | {r['bot']} | ${r['entry_price']} | ${r['exit_price']} | {_fmt_pct(pnl)} | {alpha_str} | {r['days_held']}d | {r['exit_reason']} | {r['score']} |")
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
