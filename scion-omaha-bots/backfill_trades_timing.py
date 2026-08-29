"""
backfill_trades_timing.py — One-time migration of trades.csv to the new
21-column schema (plan R8/tracker change): backfill entry_day_sign,
entry_trigger, vol_ratio, regime, earnings_days, fill_vs_close for the
existing closed trades by running entry_timing.assess() sliced to each
trade's entry date. Original columns are preserved verbatim.
"""
import csv
import datetime
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import yfinance as yf

from entry_timing import assess
from tracker import TRADES_FILE, TRADES_HEADERS

NEW_FIELDS = ["entry_day_sign", "entry_trigger", "vol_ratio", "regime",
              "earnings_days", "fill_vs_close"]


def slice_to(df, as_of):
    """Return rows with index.date <= as_of (the entry date, inclusive)."""
    return df[df.index.date <= as_of]


def historical_earnings_days(ticker, entry_dt):
    """Calendar days from entry_dt to the first earnings date >= entry_dt."""
    try:
        edf = yf.Ticker(ticker).get_earnings_dates(limit=12)
        if edf is None or len(edf) == 0:
            return None
        dates = [d.date() if hasattr(d, "date") else d for d in edf.index]
        dates = [d for d in dates if d >= entry_dt]
        return (min(dates) - entry_dt).days if dates else None
    except Exception:
        return None


def main():
    # 1. Backup the original file.
    bak = TRADES_FILE + ".bak"
    shutil.copy2(TRADES_FILE, bak)
    print(f"backup -> {bak}")

    # 2. Load existing rows (old 15-col schema).
    with open(TRADES_FILE, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"loaded {len(rows)} closed trades")

    # 3. SPY history once for R6 regime (slice per entry date).
    spy = yf.Ticker("SPY").history(period="2y")
    if len(spy) < 200:
        print("WARNING: SPY 2y history too short for R6")

    for r in rows:
        sym = r["ticker"]
        entry_dt = datetime.date.fromisoformat(r["entry_date"])
        try:
            hist = slice_to(yf.Ticker(sym).history(period="2y"), entry_dt)
            spy_slice = slice_to(spy, entry_dt)
            if len(hist) < 2:
                print(f"  {sym:6s} {r['entry_date']}  NO DATA, left unchanged")
                continue

            entry_close = float(hist["Close"].iloc[-1])
            try:
                entry_price = float(r["entry_price"])
                fill_dev = round((entry_price - entry_close) / entry_close * 100, 2)
            except (TypeError, ValueError):
                fill_dev = ""

            edays = historical_earnings_days(sym, entry_dt)
            res = assess(hist, spy_hist=spy_slice, earnings_days=edays)
            f = res["fields"]

            r["entry_day_sign"] = f["entry_day_sign"]
            r["entry_trigger"] = f["entry_trigger"]
            r["vol_ratio"] = round(f["vol_ratio"], 2)
            r["regime"] = f["regime"]
            r["earnings_days"] = "" if edays is None else edays
            r["fill_vs_close"] = fill_dev

            flags = []
            if res["veto"]:
                flags.append(f"VETO:{res['veto'][:12]}")
            print(f"  {sym:6s} {r['entry_date']} sign={f['entry_day_sign']:5s} "
                  f"trig={r['entry_trigger']:9s} vol={r['vol_ratio']:>4} "
                  f"edays={r['earnings_days']} fill={r['fill_vs_close']:>6} "
                  f"regime={r['regime'][:30]} {' '.join(flags)}")
        except Exception as e:
            print(f"  {sym:6s} {r['entry_date']}  FAILED: {e}; left unchanged")

    # 4. Rewrite under the new header, original values preserved.
    with open(TRADES_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADES_HEADERS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"rewrote {len(rows)} rows with {len(TRADES_HEADERS)} columns -> {TRADES_FILE}")


if __name__ == "__main__":
    main()
