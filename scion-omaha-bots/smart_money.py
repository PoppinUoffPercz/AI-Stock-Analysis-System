"""
smart_money.py — Smart Money Tracker for Scion-Bot.

Tracks insider activity (transactions + purchases summary) and
institutional ownership (top holders + major holders breakdown) to
answer one question: is smart money buying or selling this stock?

Provides a composite score (0-100) consumed as a confirmation signal
by both bots — it never overrides fundamentals, it only confirms or
challenges the thesis.
"""

import datetime
import numpy as np
import pandas as pd
import yfinance as yf


def _safe_int(value):
    """Coerce a value to int, defaulting to 0 on failure."""
    try:
        if value is None or pd.isna(value):
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value):
    """Coerce a value to float, defaulting to 0.0 on failure."""
    try:
        if value is None or pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_insider_purchases(rows):
    """Parse yfinance insider_purchases records -> (net_shares_6mo, buy_pct, total_transactions).

    The "Net Shares Purchased (Sold)" row is the net, but it must not be confused
    with the "% Net Shares Purchased (sold)" row (a fraction, not shares).
    """
    net = 0
    buys = 0
    sales = 0
    trans = 0
    for row in rows:
        label = str(row.get("Insider Purchases Last 6m", "")).lower()
        shares = _safe_float(row.get("Shares"))
        if "net shares purchased" in label and not label.startswith("%"):
            net = shares
            trans = _safe_int(row.get("Trans"))
        elif "purchases" in label:
            buys = shares
        elif "sales" in label:
            sales = shares
    buy_pct = buys / (buys + sales) if (buys + sales) > 0 else 0.0
    return net, buy_pct, trans


def get_insider_signal(symbol, ticker=None):
    """
    Analyze insider activity for a symbol.

    Caller may pass an existing yfinance.Ticker object (e.g., from the screener)
    to avoid redundant HTTP calls — yfinance caches per Ticker instance.

    Returns dict with:
      net_shares_6mo   — net shares bought (positive) or sold (negative)
      buy_pct          — fraction of transactions that were buys
      total_transactions
      signal           — 'bullish' / 'bearish' / 'neutral'
      score            — -10..+10
      details          — list of {insider, position, shares, value, type, date}
    """
    try:
        if ticker is None:
            ticker = yf.Ticker(symbol)
        purchases = ticker.insider_purchases
        transactions = ticker.insider_transactions
    except Exception:
        return _empty_insider_signal()

    net_shares_6mo = 0
    total_transactions = 0
    buy_pct = 0.0

    if purchases is not None and not purchases.empty:
        try:
            net_shares_6mo, buy_pct, total_transactions = _parse_insider_purchases(purchases.to_dict("records"))
        except Exception:
            pass

    details = []
    if transactions is not None and not transactions.empty:
        try:
            for _, row in transactions.head(10).iterrows():
                text = str(row.get("Text", "")).lower()
                ownership = str(row.get("Ownership", "")).upper().strip()
                if "sale" in text or ownership == "S":
                    trade_type = "SELL"
                elif "purchase" in text or "buy" in text or ownership == "P":
                    trade_type = "BUY"
                else:
                    trade_type = "OTHER"
                details.append({
                    "insider": str(row.get("Insider", "")),
                    "position": str(row.get("Position", "")),
                    "shares": _safe_int(row.get("Shares")),
                    "value": _safe_float(row.get("Value")),
                    "type": trade_type,
                    "date": str(row.get("Start Date", ""))[:10],
                })
        except Exception:
            pass

    if total_transactions == 0:
        total_transactions = len(details)

    if total_transactions > 0 and buy_pct == 0 and details:
        buys = sum(1 for d in details if d["type"] == "BUY")
        buy_pct = buys / max(len(details), 1)

    if buy_pct >= 0.70 and net_shares_6mo > 0:
        signal = "bullish"
        score = min(10, int(8 + (buy_pct - 0.70) * 10))
    elif buy_pct >= 0.60 and net_shares_6mo > 0:
        signal = "bullish"
        score = 5
    elif buy_pct <= 0.30 or net_shares_6mo < 0:
        signal = "bearish"
        score = max(-10, round(-5 - (0.30 - buy_pct) * 15) if buy_pct < 0.30 else -5)
    else:
        signal = "neutral"
        score = 0

    return {
        "net_shares_6mo": net_shares_6mo,
        "buy_pct": round(buy_pct, 3),
        "total_transactions": total_transactions,
        "signal": signal,
        "score": score,
        "details": details,
    }


def _empty_insider_signal():
    return {
        "net_shares_6mo": 0,
        "buy_pct": 0.0,
        "total_transactions": 0,
        "signal": "neutral",
        "score": 0,
        "details": [],
    }


def get_institutional_signal(symbol, ticker=None):
    """
    Analyze institutional ownership for a symbol.

    Caller may pass an existing yfinance.Ticker object to avoid redundant HTTP calls.

    Returns dict with:
      holder_count      — number of major institutions
      avg_pct_change    — average % change among top holders
      net_adding        — count of holders increasing position
      net_reducing      — count of holders reducing position
      signal            — 'bullish' / 'bearish' / 'neutral'
      score             — -10..+10
      top_holders       — list of dicts (holder, shares, pct_held, pct_change)
      institutions_pct  — % of float held by institutions
    """
    try:
        if ticker is None:
            ticker = yf.Ticker(symbol)
        inst = ticker.institutional_holders
        mf = ticker.mutualfund_holders
        major = ticker.major_holders
    except Exception:
        return _empty_institutional_signal()

    holder_count = 0
    avg_pct_change = 0.0
    net_adding = 0
    net_reducing = 0
    top_holders = []

    pct_changes = []
    for df in (inst, mf):
        if df is None or df.empty:
            continue
        holder_count += len(df)
        for _, row in df.iterrows():
            pct_change = _safe_float(row.get("pctChange"))
            pct_changes.append(pct_change)
            if pct_change > 0.01:
                net_adding += 1
            elif pct_change < -0.01:
                net_reducing += 1
            top_holders.append({
                "holder": str(row.get("Holder", "")),
                "shares": _safe_int(row.get("Shares")),
                "pct_held": _safe_float(row.get("pctHeld")),
                "pct_change": round(pct_change * 100, 2),
            })
    if pct_changes:
        avg_pct_change = np.mean(pct_changes)

    institutions_pct = 0.0
    if major is not None and not major.empty:
        try:
            major_dict = major.to_dict("split")
            for idx, label in enumerate(major_dict["index"]):
                label = str(label).lower()
                if "institutionsfloatpercentheld" in label:
                    institutions_pct = _safe_float(major_dict["data"][idx][0])
                    break
                if "institutionspercentheld" in label and institutions_pct == 0:
                    institutions_pct = _safe_float(major_dict["data"][idx][0])
        except Exception:
            pass

    if net_adding > net_reducing and avg_pct_change > 0:
        signal = "bullish"
        score = min(10, 5 + net_adding - net_reducing)
    elif net_reducing > net_adding and avg_pct_change < 0:
        signal = "bearish"
        score = max(-10, -5 - (net_reducing - net_adding))
    else:
        signal = "neutral"
        score = 0

    return {
        "holder_count": holder_count,
        "avg_pct_change": round(float(avg_pct_change) * 100, 2),
        "net_adding": net_adding,
        "net_reducing": net_reducing,
        "signal": signal,
        "score": score,
        "top_holders": top_holders[:10],
        "institutions_pct": round(institutions_pct * 100, 1) if institutions_pct else 0,
    }


def _empty_institutional_signal():
    return {
        "holder_count": 0,
        "avg_pct_change": 0.0,
        "net_adding": 0,
        "net_reducing": 0,
        "signal": "neutral",
        "score": 0,
        "top_holders": [],
        "institutions_pct": 0,
    }


def get_smart_money_score(symbol, ticker=None):
    """
    Composite Smart Money score (0-100) combining insider (60%)
    and institutional (40%) signals.

    Caller may pass an existing yfinance.Ticker object to avoid
    creating two redundant Ticker instances per symbol (each one
    triggers separate HTTP requests for the same data).
    """
    insider = get_insider_signal(symbol, ticker=ticker)
    inst = get_institutional_signal(symbol, ticker=ticker)

    insider_score_norm = insider["score"] + 10  # -10..+10 → 0..20
    inst_score_norm = inst["score"] + 10
    weighted = (insider_score_norm * 0.60 + inst_score_norm * 0.40) * (100 / 20)

    composite = round(weighted)

    if composite >= 80:
        label = "Smart Money Accumulating"
    elif composite >= 60:
        label = "Mixed - Slight Accumulation"
    elif composite >= 40:
        label = "Neutral / No Clear Signal"
    elif composite >= 20:
        label = "Mixed - Slight Selling"
    else:
        label = "Smart Money Selling Off"

    return {
        "composite_score": composite,
        "label": label,
        "insider_detail": insider,
        "institutional_detail": inst,
    }


def get_smart_money_summary(symbol):
    """One-line summary for premarket use."""
    try:
        sm = get_smart_money_score(symbol)
        insider = sm["insider_detail"]
        inst = sm["institutional_detail"]
        if insider["total_transactions"] > 0:
            insider_str = f"Insiders {insider['signal']}"
            if insider["net_shares_6mo"] != 0:
                insider_str += f" (net {insider['net_shares_6mo']:+,})"
        else:
            insider_str = "Insiders neutral"
        if inst["holder_count"] > 0:
            inst_str = f"{inst['holder_count']} holders, {inst['net_adding']} adding / {inst['net_reducing']} reducing"
        else:
            inst_str = "no holder data"
        return f"{insider_str} | {inst_str} (score: {sm['composite_score']}/100)"
    except Exception:
        return f"{symbol}: smart money data unavailable"


if __name__ == "__main__":
    print("smart_money.py — Self-test on AAPL...")
    print()
    print("=== Insider Signal ===")
    insider = get_insider_signal("AAPL")
    for k, v in insider.items():
        if k == "details":
            print(f"  {k}: ({len(v)} transactions)")
            for d in v[:3]:
                print(f"    {d}")
        else:
            print(f"  {k}: {v}")

    print()
    print("=== Institutional Signal ===")
    inst = get_institutional_signal("AAPL")
    for k, v in inst.items():
        if k == "top_holders":
            print(f"  {k}: ({len(v)} holders)")
            for h in v[:3]:
                print(f"    {h}")
        else:
            print(f"  {k}: {v}")

    print()
    print("=== Smart Money Composite ===")
    sm = get_smart_money_score("AAPL")
    print(f"  composite_score: {sm['composite_score']}")
    print(f"  label: {sm['label']}")
    print()
    print(f"Premarket summary: {get_smart_money_summary('AAPL')}")
