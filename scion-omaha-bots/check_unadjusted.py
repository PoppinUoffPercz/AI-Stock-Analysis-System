"""Re-test fill-inside-range using UNADJUSTED yfinance prices.

Separates dividend-adjustment noise (small offsets, real fills) from
genuinely misdated entries (fill price never traded on the logged date).
"""
import csv, sys
import yfinance as yf

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

rows = list(csv.DictReader(open("trades.csv", encoding="utf-8")))
for r in rows:
    sym = r["ticker"]
    d = r["entry_date"]
    fill = float(r["entry_price"])
    h = yf.Ticker(sym).history(period="3mo", interval="1d", auto_adjust=False).reset_index()
    h["dstr"] = h["Date"].dt.strftime("%Y-%m-%d")
    day = h[h["dstr"] == d]
    if day.empty:
        print(f"{sym:<6} {d}: no unadjusted bar")
        continue
    lo, hi = float(day["Low"].iloc[0]), float(day["High"].iloc[0])
    c = float(day["Close"].iloc[0])
    inside = lo <= fill <= hi
    tag = "OK real fill" if inside else "MISMATCH"
    dev = (fill - c) / c * 100
    print(f"{sym:<6} fill={fill:>9.2f} {d} unadj range {lo:>9.2f}..{hi:>9.2f} close={c:>9.2f}  dev_from_close={dev:>6.2f}%  -> {tag}")
