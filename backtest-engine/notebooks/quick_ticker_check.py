#!/usr/bin/env python
"""Quick data pull for ASTS + RDW. Uses yfinance (free tier, same as M1)."""
import numpy as np
import yfinance as yf

for ticker in ["ASTS", "RDW"]:
    t = yf.Ticker(ticker)
    info = t.info
    hist = t.history(period="3mo")
    cur = info.get("currentPrice", info.get("regularMarketPrice", "N/A"))
    h52 = info.get("fiftyTwoWeekHigh", info.get("fiftyTwoWeekHigh", "N/A"))
    l52 = info.get("fiftyTwoWeekLow", info.get("fiftyTwoWeekLow", "N/A"))
    vol_avg = float(hist["Volume"].mean()) if not hist.empty else 0
    ret_30d = float(hist["Close"].pct_change().dropna().mean()) if not hist.empty else 0
    vol_30d = float(hist["Close"].pct_change().dropna().std() * np.sqrt(252)) if not hist.empty else 0
    print(f"=== {ticker} ===")
    print(f"  Price: {cur}")
    print(f"  52W H/L: {h52} / {l52}")
    print(f"  Vol avg (3mo): {vol_avg:,.0f}")
    print(f"  30d return (ann approx): {ret_30d*252:.2%}")
    print(f"  30d vol (ann): {vol_30d:.2%}")
    print()
