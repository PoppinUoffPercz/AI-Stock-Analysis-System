"""Diagnose R8 fill-vs-close anomaly: is each logged fill inside the entry-day OHLC range?"""
import csv, sys
import yfinance as yf

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

rows = list(csv.DictReader(open("trades.csv", encoding="utf-8")))
hdr = f"{'symbol':<6}{'entry_date':<12}{'fill':>9}{'close':>10}{'low':>8}{'high':>9}{'fill_vs_close':>13}  range_ok?"
print(hdr)
for r in rows:
    sym = r["ticker"]
    d = r["entry_date"]
    fill = float(r["entry_price"])
    try:
        h = yf.Ticker(sym).history(period="1mo", interval="1d")
        if h.empty:
            print(f"{sym:<6}{d:<12} no data at all")
            continue
        # yfinance 1d single-date range returns nothing; locate the row by date string
        h = h.reset_index()
        h["dstr"] = h["Date"].dt.strftime("%Y-%m-%d")
        day = h[h["dstr"] == d]
        if day.empty:
            print(f"{sym:<6}{d:<12} no bar for entry date (dates available: {h['dstr'].iloc[-3:].tolist()})")
            continue
        c = float(day["Close"].iloc[0])
        lo = float(day["Low"].iloc[0])
        hi = float(day["High"].iloc[0])
        ok = "YES" if lo <= fill <= hi else "NO  <-- mismatch"
        print(f"{sym:<6}{d:<12}{fill:>9.2f}{c:>10.2f}{lo:>8.2f}{hi:>9.2f}{float(r['fill_vs_close']):>13.2f}  {ok}")
    except Exception as e:
        print(f"{sym:<6}{d:<12} ERROR {e}")
