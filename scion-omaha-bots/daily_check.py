"""
Daily Position Monitor

Fetches current prices for all open positions, compares to stops and targets,
logs a daily P&L snapshot, and writes a vault markdown brief.
Run manually: python daily_check.py
"""
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tracker import Tracker
from credit_monitor import CreditMonitor
from debate import get_debate_score, score_modifier

VAULT_DIR = os.path.join(os.path.expanduser("~"),
    "OneDrive", "Documents", "Obsidian Vault",
    "Stock Research", "Daily Briefs")


def _ensure_vault_dir():
    os.makedirs(VAULT_DIR, exist_ok=True)
    return VAULT_DIR


def _get_vix_and_spy():
    import yfinance as yf
    result = {"vix": None, "spy": None}
    try:
        vix = yf.Ticker("^VIX")
        h = vix.history(period="5d")
        if not h.empty:
            result["vix"] = round(float(h["Close"].iloc[-1]), 2)
    except Exception:
        pass
    try:
        spy = yf.Ticker("SPY")
        h = spy.history(period="5d")
        if not h.empty:
            result["spy"] = round(float(h["Close"].iloc[-1]), 2)
    except Exception:
        pass
    return result


def generate_daily_brief(tracker=None, prices_dict=None):
    if tracker is None:
        tracker = Tracker()

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    open_pos = tracker.get_open_positions_summary()
    market = _get_vix_and_spy()

    # Log snapshot first
    tracker.log_daily_snapshot(prices_dict=prices_dict)

    lines = []
    lines.append("---")
    lines.append(f'title: "Position Check — {today}"')
    lines.append(f"date: {today}")
    lines.append("tags:")
    lines.append("  - position-check")
    lines.append("  - daily")
    lines.append("---")
    lines.append("")
    lines.append(f"# Position Check — {today}")
    lines.append("")

    # Market context
    lines.append("## Market Context")
    lines.append(f"| SPY | VIX | Positions |")
    lines.append(f"| :--- | :--- | :--- |")
    spy_str = f"${market['spy']}" if market["spy"] else "N/A"
    vix_str = f"{market['vix']}" if market["vix"] else "N/A"
    vix_note = ""
    if market["vix"]:
        if market["vix"] > 25:
            vix_note = " ⚠ Elevated"
        elif market["vix"] < 15:
            vix_note = " ✅ Low"
    lines.append(f"| {spy_str} | {vix_str}{vix_note} | {len(open_pos)} open |")
    lines.append("")

    try:
        _, cs, cl, _ = CreditMonitor().quick_pulse()
        lines.append(f"**Credit Stress:** {cs:.0f}/100 ({cl})")
        lines.append("")
    except Exception:
        pass

    # Alert zones
    if open_pos:
        alerts = []
        for p in open_pos:
            ticker = p["ticker"]
            cp = p["current_price"]
            stop = p["stop_loss"]
            t1 = p["target_1"]

            if stop and cp:
                dist_to_stop = (cp - stop) / cp * 100
                if dist_to_stop < 3:
                    alerts.append(f"⚠ **{ticker}**: Stop is near! Only {dist_to_stop:.1f}% away at ${stop:.2f}")

            if t1 and cp:
                dist_to_t1 = (t1 - cp) / cp * 100
                if dist_to_t1 < 3:
                    alerts.append(f"🎯 **{ticker}**: Target 1 within reach! Only {dist_to_t1:.1f}% away at ${t1:.2f}")

            # Thesis-break review zone (rule 2026-08-05): down 5%+ -> close now if thesis broke,
            # do NOT wait for the (wider) configured stop. Hard cap is -6%.
            if p["pnl_pct"] <= -5.0:
                alerts.append(f"🔴 **{ticker}**: Down {p['pnl_pct']:.1f}% — THESIS-BREAK REVIEW zone. "
                              f"Close now if thesis broken (hard rule: exit -5% to -6%). Do not wait for stop.")

        if alerts:
            lines.append("## Alerts")
            lines.append("")
            for a in alerts:
                lines.append(f"- {a}")
            lines.append("")

    # Position table
    lines.append("## Open Positions")
    lines.append("")
    if open_pos:
        lines.append("| Ticker | Entry | Current | P&L% | Days | Stop | Dist% | T1 | Dist% | T2 | Score | Debate |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for p in sorted(open_pos, key=lambda x: x["pnl_pct"]):
            pnl = f"{p['pnl_pct']:+.2f}%"
            sd = f"{p['distance_to_stop_pct']:+.1f}%" if p["distance_to_stop_pct"] is not None else "N/A"
            td = f"{p['distance_to_target1_pct']:+.1f}%" if p['distance_to_target1_pct'] is not None else "N/A"
            stop_str = f"${p['stop_loss']:.2f}" if p["stop_loss"] else "N/A"
            t1_str = f"${p['target_1']:.2f}" if p["target_1"] else "N/A"
            t2_str = f"${p['target_2']:.2f}" if p["target_2"] else "N/A"
            base = p['score']
            debate = get_debate_score(p['ticker'])
            mod = score_modifier(debate)
            if debate is not None:
                debate_str = f"{base}+{mod}→{base+mod}" if mod > 0 else (f"{base}{mod}→{base+mod}" if mod < 0 else f"{base}±0")
            else:
                debate_str = ""
            lines.append(f"| **{p['ticker']}** | ${p['entry_price']:.2f} | ${p['current_price']:.2f} | {pnl} | {p['days_held']}d | {stop_str} | {sd} | {t1_str} | {td} | {t2_str} | {base} | {debate_str} |")
    else:
        lines.append("_No open positions._")
    lines.append("")

    days_sorted = sorted(open_pos, key=lambda x: x["days_held"], reverse=True) if open_pos else []
    if days_sorted:
        lines.append(f"**Longest held:** {days_sorted[0]['ticker']} ({days_sorted[0]['days_held']}d)")
        lines.append(f"**Shortest held:** {days_sorted[-1]['ticker']} ({days_sorted[-1]['days_held']}d)")
        lines.append("")

        best = max(open_pos, key=lambda x: x["pnl_pct"])
        worst = min(open_pos, key=lambda x: x["pnl_pct"])
        lines.append(f"**Best performer:** {best['ticker']} ({best['pnl_pct']:+.2f}%)")
        lines.append(f"**Worst performer:** {worst['ticker']} ({worst['pnl_pct']:+.2f}%)")
        lines.append("")

    lines.append("---")
    lines.append(f"*Check run at {datetime.datetime.now().strftime('%H:%M')}. Data from tracker.py.*")
    lines.append("")

    report = "\n".join(lines)
    filepath = os.path.join(_ensure_vault_dir(), f"{today} Position Check.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  Daily brief saved: {filepath}")

    return report


def cmd_check():
    tracker = Tracker()
    generate_daily_brief(tracker=tracker)

    open_pos = tracker.get_open_positions_summary()
    if not open_pos:
        print("  No open positions.")
        return

    # Terminal quick-view
    print(f"\n  {'Ticker':<8} {'P&L%':>7} {'Days':>5} {'StopDist':>10} {'T1Dist':>9} {'Score':>6} {'DebateMod':>6}")
    print("  " + "-" * 57)
    for p in open_pos:
        sd = f"{p['distance_to_stop_pct']:+.1f}%" if p["distance_to_stop_pct"] is not None else "N/A"
        td = f"{p['distance_to_target1_pct']:+.1f}%" if p['distance_to_target1_pct'] is not None else "N/A"
        debate = get_debate_score(p['ticker'])
        mod = score_modifier(debate)
        mod_str = f"{mod:+d}" if debate is not None else ""
        print(f"  {p['ticker']:<8} {p['pnl_pct']:+.2f}% {p['days_held']:>4}d {sd:>9} {td:>8} {p['score']:>5} {mod_str:>6}")


if __name__ == "__main__":
    cmd_check()
