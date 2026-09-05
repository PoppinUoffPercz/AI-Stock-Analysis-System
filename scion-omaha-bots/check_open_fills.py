"""Check open positions' fill prices against their logged entry-date OHLC.

The six still-open backfill positions were stamped 2026-07-08 by
backfill_current_positions() - same batch that misdated VRT/BA/AXON/LNG.
This tells us whether the whole batch drifted or only the closed trades.
"""
import json
import sys

import yfinance as yf

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

pos = json.load(open("open_positions.json", encoding="utf-8"))
print(f"{'symbol':<6}{'entry_date':<12}{'fill':>9}{'low':>9}{'high':>9}{'close':>9}  verdict")
for sym, p in pos.items():
    d = p.get("entry_date", "")
    fill = p.get("entry_price")
    if fill is None or d == "":
        print(f"{sym:<6} no price/date on file")
        continue
    try:
        h = yf.Ticker(sym).history(period="3mo", interval="1d", auto_adjust=False).reset_index()
        h["dstr"] = h["Date"].dt.strftime("%Y-%m-%d")
        day = h[h["dstr"] == d]
        if day.empty:
            print(f"{sym:<6}{d:<12}{fill:>9.2f}  no bar for date")
            continue
        lo, hi, c = float(day["Low"].iloc[0]), float(day["High"].iloc[0]), float(day["Close"].iloc[0])
        inside = lo <= fill <= hi
        verdict = "OK real fill" if inside else "MISMATCH - date drift"
        print(f"{sym:<6}{d:<12}{fill:>9.2f}{lo:>9.2f}{hi:>9.2f}{c:>9.2f}  {verdict}")
    except Exception as e:
        print(f"{sym:<6}{d:<12}{fill:>9.2f}  ERROR {e}")
