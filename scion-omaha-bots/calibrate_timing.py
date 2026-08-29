"""
calibrate_timing.py — Wk1 calibration of entry-timing rule parameters (plan Phase 2).

Grid-search over the two rules the Wk1 audit flagged:
  R1: red-close + no-reversal penalty (current -10; candidates -10/-7/-5/-3)
  R5: <=3d earnings veto conditionality (None=unconditional, 5%, 10% run-up)

Evaluation against the 8 closed trades (delta -> realized PnL):
  - r(delta, PnL)
  - mean PnL of positive- vs negative-delta groups (separation)
  - the veto set and its mean PnL (a good veto flags losers, not winners)

Selection is interpreted manually: n=8 means the grid ranks candidates, it does
not prove significance. Prefer round, interpretable params that improve
separation without overfitting the best single trade.
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


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    with open(TRADES_FILE, newline="", encoding="utf-8") as f:
        trades = list(csv.DictReader(f))

    spy = yf.Ticker("SPY").history(period="2y")
    cache = {}
    rows = []
    for t in trades:
        sym, entry_date = t["ticker"], t["entry_date"]
        as_of = datetime.date.fromisoformat(entry_date)
        if sym not in cache:
            cache[sym] = yf.Ticker(sym).history(period="2y")
        hist = cache[sym]
        hist = hist[hist.index.date <= as_of]
        rows.append({
            "ticker": sym,
            "pnl": _num(t.get("pnl_pct")) or 0.0,
            "hist": hist,
            "spy": spy[spy.index.date <= as_of],
            "edays": _num(t.get("earnings_days") or None),
        })

    overall_mean = statistics.mean(r["pnl"] for r in rows)

    def evaluate(params):
        out = []
        for r in rows:
            res = assess(r["hist"], spy_hist=r["spy"], earnings_days=r["edays"], params=params)
            out.append({"ticker": r["ticker"], "pnl": r["pnl"], "delta": res["delta"],
                        "veto": res["veto"]})
        deltas = [o["delta"] for o in out]
        pos = [o for o in out if o["delta"] > 0]
        neg = [o for o in out if o["delta"] < 0]
        vetoed = [o for o in out if o["veto"]]
        dm, pm = statistics.mean(deltas), statistics.mean([o["pnl"] for o in out])
        sd_d, sd_p = statistics.pstdev(deltas), statistics.pstdev([o["pnl"] for o in out])
        r_corr = (sum((o["delta"] - dm) * (o["pnl"] - pm) for o in out) /
                  (len(out) * sd_d * sd_p)) if sd_d and sd_p else float("nan")
        return {
            "r": r_corr,
            "pos_mean": statistics.mean([o["pnl"] for o in pos]) if pos else float("nan"),
            "neg_mean": statistics.mean([o["pnl"] for o in neg]) if neg else float("nan"),
            "sep": (statistics.mean([o["pnl"] for o in pos]) - statistics.mean([o["pnl"] for o in neg])
                    if pos and neg else float("nan")),
            "vetoed": [f"{o['ticker']}({o['pnl']:+.1f})" for o in vetoed],
            "veto_mean": statistics.mean([o["pnl"] for o in vetoed]) if vetoed else float("nan"),
            "deltas": deltas,
        }

    # Sanity: default params must produce the calibrated deltas.
    base = evaluate({})
    assert base["deltas"] == [0, 5, 0, -5, -5, 4, 0, 7], base["deltas"]
    print("baseline (default params) deltas match calibrated expectation: OK")

    # BMY run-up, to ground the R5 threshold choice.
    bmy = [r for r in rows if r["ticker"] == "BMY"][0]
    close = bmy["hist"]["Close"]
    print(f"BMY run10 into 7/30 entry: {(float(close.iloc[-1]) / float(close.iloc[-11]) - 1) * 100:+.1f}%")
    ax = [r for r in rows if r["ticker"] == "AXON"][0]
    axc = ax["hist"]["Close"]
    print(f"AXON run10 into 7/8 entry:  {(float(axc.iloc[-1]) / float(axc.iloc[-11]) - 1) * 100:+.1f}%")

    print(f"\noverall mean PnL: {overall_mean:+.2f}%  (veto that beats this = flags losers)\n")
    print(f"{'R1 pen':>7} {'R5 veto':>9} | {'r':>6} {'posMean':>8} {'negMean':>8} {'sep':>7} | veto set / veto mean")
    print("-" * 100)
    for r1 in (-10, -7, -5, -3):
        for r5 in (None, 5.0, 10.0):
            params = {"r1_red_no_reversal": r1}
            if r5 is not None:
                params["r5_veto_runup_pct"] = r5
            e = evaluate(params)
            label = "uncond" if r5 is None else f">{r5:.0f}%"
            vset = ", ".join(e["vetoed"]) if e["vetoed"] else "-"
            vmean = f"{e['veto_mean']:+.1f}" if e["vetoed"] else "-"
            print(f"{r1:>7} {label:>9} | {e['r']:>+6.2f} {e['pos_mean']:>+8.1f} "
                  f"{e['neg_mean']:>+8.1f} {e['sep']:>+7.1f} | {vset} ({vmean})")


if __name__ == "__main__":
    main()
