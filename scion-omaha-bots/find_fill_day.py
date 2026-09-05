"""Which days' [low, high] ranges contain the logged fill/exit prices?

If a fill price is inside day X's range, X is a plausible real execution day.
Compare that to the logged entry_date to expose the logging convention.
"""
import csv
import sys

import yfinance as yf

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

rows = list(csv.DictReader(open("trades.csv", encoding="utf-8")))
for r in rows:
    sym = r["ticker"]
    fill = float(r["entry_price"])
    exit_p = float(r["exit_price"])
    d = r["entry_date"]
    h = yf.Ticker(sym).history(period="3mo", interval="1d").reset_index()
    h["dstr"] = h["Date"].dt.strftime("%Y-%m-%d")
    h["lo"] = h["Low"].astype(float)
    h["hi"] = h["High"].astype(float)
    print(f"=== {sym}  entry_date={d}  fill={fill:.2f}  exit={exit_p:.2f}")

    fill_days = h[(h["lo"] <= fill) & (fill <= h["hi"])]
    print("  fill inside ranges of:", fill_days["dstr"].tolist())
    if len(fill_days) >= 1:
        fd = fill_days["dstr"].iloc[0]
        print(f"    -> earliest plausible fill day: {fd}  (logged: {d})")
        ed = h.index[h["dstr"] == d]
        if len(ed):
            diff = (fill_days.index[0] - ed[0])
            print(f"    -> {abs(diff)} trading day(s) {'after' if diff > 0 else 'before'} logged date")
    else:
        print("    -> fill price is NOT inside ANY day's range in 3mo window")

    exit_days = h[(h["lo"] <= exit_p) & (exit_p <= h["hi"])]
    print(f"  exit inside ranges of: {exit_days['dstr'].tolist()[:5]}")
    print()
