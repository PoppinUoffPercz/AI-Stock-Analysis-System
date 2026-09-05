"""
shadow_audit.py — Wk1 shadow-mode audit of the entry-timing layer (plan R1-R9).

Reads the closed-trade ledger (trades.csv), recomputes each trade's entry-time
timing classification via entry_timing.assess() (history sliced to the entry
date), and reports: trigger mix, veto frequency by rule, delta distribution and
its relationship to realized PnL, rule-firing frequency (incl. the R9 suspect),
regime mix, and the R8 fill-vs-close audit.

Run:  python shadow_audit.py     (network: yfinance 2y hist per unique ticker + SPY)
Output: console summary + <Obsidian vault>/Stock Research/Performance/YYYY-MM-DD Shadow Audit.md
"""
import csv
import datetime
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yfinance as yf
from entry_timing import assess
from tracker import TRADES_FILE

VAULT_PERF = os.path.join(os.path.expanduser("~"), "OneDrive", "Documents",
                          "Obsidian Vault", "Stock Research", "Performance")


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _rule(name):
    """Map a reasons string to its rule id, e.g. 'R1 ENTRY_TRIGGER: ...' -> 'R1'."""
    return name.split(" ")[0] if name else "?"


def load_trades():
    with open(TRADES_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    trades = load_trades()
    if not trades:
        print("no trades in", TRADES_FILE)
        return

    spy = yf.Ticker("SPY").history(period="2y")
    hist_cache = {}

    rows = []
    for t in trades:
        sym, entry_date = t["ticker"], t["entry_date"]
        as_of = datetime.date.fromisoformat(entry_date)
        if sym not in hist_cache:
            hist_cache[sym] = yf.Ticker(sym).history(period="2y")
        hist = hist_cache[sym]
        hist = hist[hist.index.date <= as_of]
        spy_slice = spy[spy.index.date <= as_of]
        edays = _num(t.get("earnings_days") or None)
        res = assess(hist, spy_hist=spy_slice, earnings_days=edays)
        rows.append({
            "ticker": sym, "entry": t.get("entry_date"), "exit": t.get("exit_date"),
            "pnl": _num(t.get("pnl_pct")) or 0.0,
            "bot": t.get("bot", ""),
            "trigger": t.get("entry_trigger", ""),
            "regime": t.get("regime", ""),
            "fill": _num(t.get("fill_vs_close")),
            "delta": res["delta"], "veto": res["veto"], "reasons": res["reasons"],
        })

    n = len(rows)
    L = []
    L.append("---")
    L.append(f'title: "Shadow Audit — Wk1 ({datetime.date.today().isoformat()})"')
    L.append("tags: [shadow-audit, entry-timing]")
    L.append("---")
    L.append("")
    L.append(f"# Shadow Audit — {datetime.date.today().isoformat()}")
    L.append("")
    L.append(f"Closed trades in ledger: **{n}** "
             f"({datetime.datetime.strptime(min(r['entry'] for r in rows), '%Y-%m-%d').date()} → "
             f"{datetime.datetime.strptime(max(r['exit'] for r in rows), '%Y-%m-%d').date()}). "
             "Timing classification recomputed at each entry date (plan Phase 2, shadow mode — nothing enforced).")
    L.append("")

    # Trigger mix (R1)
    trig = {k: [r for r in rows if r["trigger"] == k] for k in ("green+vol", "green", "red")}
    L.append("## 1. Entry trigger mix (R1)")
    L.append("| Trigger | Trades | Mean PnL% |")
    L.append("| :--- | :--- | :--- |")
    for k in ("green+vol", "green", "red"):
        grp = trig.get(k, [])
        if grp:
            L.append(f"| {k} | {len(grp)} | {statistics.mean(r['pnl'] for r in grp):+.2f} |")
        else:
            L.append(f"| {k} | 0 | — |")
    L.append("")

    # Veto frequency (R2/R5/R7)
    vetoes = {}
    for r in rows:
        if r["veto"]:
            rid = _rule(r["veto"])
            vetoes.setdefault(rid, []).append(r)
    L.append("## 2. Veto frequency (shadow — would have blocked)")
    if vetoes:
        L.append("| Rule | Trades flagged | Their mean PnL% |")
        L.append("| :--- | :--- | :--- |")
        for rid, grp in sorted(vetoes.items()):
            L.append(f"| {rid} ({grp[0]['veto'][:60]}) | {len(grp)} | {statistics.mean(r['pnl'] for r in grp):+.2f} |")
        L.append("")
        L.append("Flagged trades: " + ", ".join(f"{r['ticker']} ({r['pnl']:+.1f}%)" for r in rows if r["veto"]) + ".")
    else:
        L.append("_None of the closed trades would have been vetoed._")
    L.append("")

    # Delta distribution + PnL relationship
    deltas = [r["delta"] for r in rows]
    L.append("## 3. Timing delta vs realized PnL")
    L.append(f"- Deltas: {deltas}")
    L.append(f"- Range {min(deltas)}…{max(deltas)} | mean {statistics.mean(deltas):+.1f} | median {statistics.median(deltas):+.1f}")
    pos = [r for r in rows if r["delta"] > 0]; neg = [r for r in rows if r["delta"] < 0]; zer = [r for r in rows if r["delta"] == 0]
    L.append(f"- Positive-delta trades: {len(pos)} (mean PnL {statistics.mean([r['pnl'] for r in pos]):+.2f}%) | "
             f"zero: {len(zer)} ({statistics.mean([r['pnl'] for r in zer]):+.2f}%) | "
             f"negative: {len(neg)} ({statistics.mean([r['pnl'] for r in neg]):+.2f}%)")
    if len(deltas) >= 3:
        try:
            dm = statistics.mean(deltas); pm = statistics.mean([r["pnl"] for r in rows])
            cov = sum((r["delta"] - dm) * (r["pnl"] - pm) for r in rows)
            sd_d = statistics.pstdev(deltas); sd_p = statistics.pstdev([r["pnl"] for r in rows])
            if sd_d and sd_p:
                r_corr = cov / (len(rows) * sd_d * sd_p)
                L.append(f"- Pearson r(delta, PnL) = **{r_corr:+.2f}** (n={n} — direction only, not significance)")
        except Exception:
            pass
    L.append("")

    # Rule firing frequency
    rules = {}
    for r in rows:
        for reason in r["reasons"]:
            rules.setdefault(_rule(reason), 0)
            rules[_rule(reason)] += 1
    L.append("## 4. Rule firing frequency")
    L.append("| Rule | Times fired (across entries) |")
    L.append("| :--- | :--- |")
    for rid, c in sorted(rules.items()):
        L.append(f"| {rid} | {c} |")
    r9 = sum(1 for r in rows for x in r["reasons"] if x.startswith("R9"))
    L.append("")
    L.append(f"**R9 PULLBACK_20 fires: {r9}/{n}** — the plan flagged this rule as most shadow-mode-dependent.")
    L.append("")

    # Regime mix
    up = [r for r in rows if " > " in r["regime"]]; dn = [r for r in rows if "vs" in r["regime"]]
    L.append("## 5. Regime at entry (R6)")
    if up or dn:
        L.append(f"- Full uptrend (SPY > 50d > 200d): {len(up)} trades, mean PnL "
                 f"{statistics.mean([r['pnl'] for r in up]):+.2f}%")
        L.append(f"- Below SPY 50-day (scale 0.85): {len(dn)} trades, mean PnL "
                 f"{statistics.mean([r['pnl'] for r in dn]):+.2f}%")
    else:
        L.append("_n/a_")
    L.append("")

    # R8 fill audit
    fills = [r["fill"] for r in rows if r["fill"] is not None]
    L.append("## 6. Fill vs signal-day close (R8)")
    if fills:
        L.append(f"- Mean deviation {statistics.mean(fills):+.2f}% | mean |dev| {statistics.mean(abs(f) for f in fills):.2f}% | "
                 f"max |dev| {max(abs(f) for f in fills):.2f}%")
        big = [r["ticker"] for r in rows if r["fill"] is not None and abs(r["fill"]) > 2]
        if big:
            L.append(f"- Fills >2% from close: {', '.join(big)} — worth reviewing how these entries were executed.")
    else:
        L.append("_no fill data_")
    L.append("")

    L.append("---")
    L.append(f"*Audit run {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}. "
             "Phase 2 shadow mode: scores moved, nothing gated. Next: re-run after more shadow data accumulates.*")

    report = "\n".join(L)
    os.makedirs(VAULT_PERF, exist_ok=True)
    out = os.path.join(VAULT_PERF, f"{datetime.date.today().isoformat()} Shadow Audit.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"audit saved: {out}")
    print(report)


if __name__ == "__main__":
    main()
