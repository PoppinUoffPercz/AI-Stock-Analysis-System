"""
entry_timing.py — Entry-timing layer for the Scion/Omaha engine.

Implements R1-R9 from "2026-08-05 Entry Timing Implementation Plan":
  R1 ENTRY_TRIGGER  R2 EXTENSION_CAP  R3 RSI_ZONE  R4 VOLUME_CONFIRM
  R5 EARNINGS_GATE  R6 REGIME_SCALE   R7 HISTORY_FLOOR  R8 EXECUTION
  R9 PULLBACK_20

assess() returns {delta, veto, reasons, fields}. Vetoes are returned but
NOT enforced here — shadow mode (plan Phase 2-3): the screener logs them
and only Phase 3 turns them into gates.

Self-check (__main__) replays the 14 historical entries and asserts their
classification matches the plan's table — the plan's Phase-1 gate.
"""
import datetime
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ta_lib import compute_rsi, compute_smas, compute_ttm_squeeze, compute_volume_ratio


def _sma_series(close, period):
    return pd.Series(close).rolling(period).mean()


def _rising(series, lookback=5):
    """True when the last value sits above its value `lookback` bars ago."""
    if series is None or len(series) < lookback + 1:
        return False
    return bool(series.iloc[-1] > series.iloc[-1 - lookback])


def assess(hist, spy_hist=None, earnings_days=None, params=None):
    """
    Compute entry-timing fields + score deltas for the last bar of `hist`.

    hist:          OHLCV DataFrame (slice it to <= entry date for replays)
    spy_hist:      SPY OHLCV for the R6 regime scalar; None -> scale 1.0
    earnings_days: days until next earnings (None = unknown / no gate)
    params:        optional overrides for calibrated knobs:
                     r1_red_no_reversal  R1 penalty for red close, no reversal (default -5,
                                         calibrated Wk1 2026-08-05: -10 over-penalized
                                         strong-trend red days like AXON, run10 +38.5%, +20%)
                     r5_veto_runup_pct   R5 veto fires only when run-up > this pct
                                         (default 10.0; None = unconditional <=3d veto)

    Returns {delta, veto, reasons, fields}. delta is already regime-scaled
    and clamped to [-20, 20]. veto is a string or None.
    """
    p = params or {}
    delta, veto, reasons = 0, None, []
    fields = {}
    if hist is None or len(hist) < 2:
        return {"delta": 0, "veto": "insufficient data", "reasons": [], "fields": {"days": 0}}

    close = hist["Close"]
    price = float(close.iloc[-1])
    prev = float(close.iloc[-2])
    hi, lo = float(hist["High"].iloc[-1]), float(hist["Low"].iloc[-1])
    day_range = hi - lo
    reversal = day_range > 0 and (price - lo) / day_range >= 0.6
    green = price > prev

    rsi = compute_rsi(close)["value"]
    sma = compute_smas(close)
    vol_ratio = compute_volume_ratio(hist["Volume"])["ratio"]
    squeeze_fire = compute_ttm_squeeze(hist)["histogram_color"] in ("lime", "green")

    low = float(close.iloc[-252:].min())  # 52W low, or since-IPO low for young names
    pct_from_low = (price - low) / low if low > 0 else None
    days = len(hist)

    sma20, sma50, sma200 = sma.get(20), sma.get(50), sma.get(200)
    sma20_series, sma50_series, sma200_series = (
        _sma_series(close, 20), _sma_series(close, 50), _sma_series(close, 200))
    sma50_rising, sma200_rising = _rising(sma50_series), _rising(sma200_series)

    fields.update({
        "days": days,
        "entry_day_sign": "green" if green else "red",
        "entry_day_pct": round((price / prev - 1) * 100, 2) if prev else 0.0,
        "entry_trigger": "green+vol" if green and vol_ratio >= 1.2 else ("green" if green else "red"),
        "reversal_bar": reversal,
        "vol_ratio": vol_ratio,
        "squeeze_fire": squeeze_fire,
        "rsi": rsi,
        "pct_from_low": round(pct_from_low * 100, 1) if pct_from_low is not None else None,
        "sma20": sma20, "sma50": sma50, "sma200": sma200,
        "sma50_rising": sma50_rising,
        "execution": "signal-day close",  # R8: fixed policy, log fills in tracker
    })

    # R1 ENTRY_TRIGGER — red close without a reversal bar is the entry killer.
    # Calibrated Wk1 (2026-08-05): -10 -> -5. The strategy buys red days by design
    # (4/8 entries); AXON's red close with a +38.5% run-up still won +20%, so the
    # flat -10 was over-penalizing strong-trend pullbacks. -5 keeps the signal
    # without the distortion (grid: r(delta,PnL) +0.16 -> +0.21).
    if not green and not reversal:
        r1 = p.get("r1_red_no_reversal", -5)
        delta += r1
        reasons.append(f"R1 ENTRY_TRIGGER: red close, no reversal bar ({r1:+d})")
    else:
        if green and vol_ratio >= 1.2:
            delta += 5
            reasons.append("R1 ENTRY_TRIGGER: green close + vol ratio >= 1.2 (+5)")
        if green and squeeze_fire:
            delta += 2  # A+ trigger; R1 caps at +7 (5+2)
            reasons.append("R1 ENTRY_TRIGGER: TTM squeeze firing on green close -> A+ (+2)")
        if not green:
            reasons.append("R1 ENTRY_TRIGGER: red close but bullish reversal bar (no penalty)")

    # R2 EXTENSION_CAP — >100% off the 52W low below SMA50 = broken-momentum chase
    if pct_from_low is not None and pct_from_low > 1.0:
        if sma50 is not None and price < sma50:
            veto = "R2 EXTENSION_CAP: >100% off 52W low and below SMA50 (chase)"
        else:
            delta -= 10
            reasons.append("R2 EXTENSION_CAP: >100% off 52W low, above SMA50 (-10)")

    # R3 RSI_ZONE
    if rsi < 25:
        fields["rsi_zone"] = "extreme-oversold"
        reasons.append("R3 RSI_ZONE: RSI < 25 - require 2 consecutive green closes")
    elif rsi > 72:
        delta -= 5
        fields["rsi_zone"] = "exhaustion"
        reasons.append("R3 RSI_ZONE: RSI > 72 (exhaustion, -5)")
    elif 25 <= rsi <= 45 and pct_from_low is not None and pct_from_low <= 0.15 and green:
        delta += 5
        fields["rsi_zone"] = "mean-reversion"
        reasons.append("R3 RSI_ZONE: RSI 25-45 near 52W low with green trigger (+5)")
    elif 45 < rsi <= 65 and sma50 is not None and price > sma50 and sma50_rising:
        delta += 5
        fields["rsi_zone"] = "momentum-pullback"
        reasons.append("R3 RSI_ZONE: RSI 45-65 in uptrend pullback (+5)")
    else:
        fields["rsi_zone"] = "neutral"

    # R4 VOLUME_CONFIRM
    if vol_ratio >= 1.2:
        if green:
            delta += 3
            reasons.append("R4 VOLUME_CONFIRM: vol >= 1.2 on green day (+3)")
        else:
            delta -= 3
            reasons.append("R4 VOLUME_CONFIRM: vol >= 1.2 on red day (distribution, -3)")

    # R5 EARNINGS_GATE — no entry within 3 trading days of earnings; run-up is a trim signal.
    # Calibrated Wk1 (2026-08-05): unconditional <=3d veto -> fires only on run-up > 10%.
    # The old veto blocked BMY (+8.9% win, run10 +7.2%); the 10% threshold matches the
    # existing run-up penalty below, so the veto is now its hard-gate form.
    if earnings_days is not None:
        run10 = None
        if len(close) >= 11:
            run10 = (price / float(close.iloc[-11]) - 1) * 100
        veto_runup = p.get("r5_veto_runup_pct", 10.0)
        if earnings_days <= 3:
            if veto_runup is not None and run10 is not None and run10 > veto_runup:
                veto = f"R5 EARNINGS_GATE: earnings within 3 trading days with {run10:.0f}% run-up"
                reasons.append(f"R5 EARNINGS_GATE: within 3 days of earnings + {run10:.0f}% run-up (VETO)")
            elif veto_runup is None:
                veto = "R5 EARNINGS_GATE: earnings within 3 trading days"
                reasons.append("R5 EARNINGS_GATE: within 3 trading days of earnings (VETO)")
            else:
                reasons.append("R5 EARNINGS_GATE: within 3 days of earnings, no run-up (no veto)")
        elif earnings_days <= 10 and run10 is not None and run10 > 10:
            delta -= 10
            reasons.append(f"R5 EARNINGS_GATE: {run10:.0f}% run-up into earnings over 10 sessions (-10)")

    # R6 REGIME_SCALE — scale the delta, never veto (KTOS/BMY won below SPY 50-day)
    scale = 1.0
    if spy_hist is not None and len(spy_hist) >= 200:
        spy = spy_hist["Close"]
        spx = float(spy.iloc[-1])
        s50 = float(_sma_series(spy, 50).iloc[-1])
        s200 = float(_sma_series(spy, 200).iloc[-1])
        if spx > s50 > s200:
            scale = 1.0
        elif spx > s200:
            scale = 0.85
        else:
            scale = 0.7
        fields["regime"] = (f"SPY {spx:.0f} > 50d {s50:.0f} > 200d {s200:.0f}" if scale == 1.0
                            else f"SPY {spx:.0f} vs 50d {s50:.0f} / 200d {s200:.0f}")
        if scale < 1.0:
            reasons.append(f"R6 REGIME_SCALE: SPY below 50-day, delta x{scale}")
    else:
        fields["regime"] = "n/a"
    fields["regime_scale"] = scale

    # R7 HISTORY_FLOOR — near-52W-low thesis needs >= 120 trading days (CBRS bug fix)
    if days < 120 and pct_from_low is not None and pct_from_low <= 0.15:
        veto = "R7 HISTORY_FLOOR: <120 trading days of history for near-52W-low thesis"
        reasons.append(f"R7 HISTORY_FLOOR: {days} days of history (VETO)")

    # R9 PULLBACK_20 — with-trend pullback to the 20-day, green recovery above it
    up = (sma50 is not None and sma200 is not None and price > sma50 > sma200
          and sma50_rising and sma200_rising)
    if up and sma20 is not None:
        prev_pullback = float(close.iloc[-2]) <= sma20_series.iloc[-2] * 1.03
        if prev_pullback and green and price > sma20:
            delta += 5
            reasons.append("R9 PULLBACK_20: pulled back to 20-day, green recovery above (+5)")
        elif price < sma20:
            delta -= 5
            reasons.append("R9 PULLBACK_20: undercut 20-day, no recovery (-5)")

    # Regime scale applies to the whole timing delta
    if scale != 1.0:
        delta = round(delta * scale)
    delta = max(-20, min(20, delta))

    fields["delta"] = delta
    return {"delta": delta, "veto": veto, "reasons": reasons, "fields": fields}


if __name__ == "__main__":
    # Phase-1 gate: classification of all 14 historical entries matches the plan table.
    import yfinance as yf

    # (ticker, entry_date, expected day sign, expected pct_from_low range)
    ENTRIES = [
        ("KTOS", "2026-07-30", "green", (0.0, 0.12)),
        ("AXON", "2026-07-08", "red", None),
        ("LNG", "2026-07-08", "green", None),
        ("BMY", "2026-07-30", "green", None),
        ("APP", "2026-07-08", "red", None),
        ("ADBE", "2026-07-08", "red", None),
        ("VRT", "2026-07-08", "green", (1.0, 2.0)),
        ("BA", "2026-07-08", "red", None),
        ("ZTS", "2026-07-08", "red", None),
        ("NVDA", "2026-07-08", "green", None),
        ("GOOGL", "2026-07-08", "red", None),
        ("WFC", "2026-07-08", "red", None),
        ("GD", "2026-07-08", "red", None),
        ("CBRS", "2026-07-08", None, None),  # R7 veto expected (young listing)
    ]

    print("Replaying 14 historical entries against entry_timing.assess()...")
    spy = yf.Ticker("SPY").history(period="1y")
    fails = 0
    for sym, date, exp_sign, exp_pct in ENTRIES:
        hist = yf.Ticker(sym).history(period="1y")
        as_of = datetime.date.fromisoformat(date)
        hist = hist[hist.index.date <= as_of]
        if len(hist) < 2:
            print(f"  {sym:6s} {date}  NO DATA"); fails += 1
            continue

        res = assess(hist, spy_hist=spy)
        f = res["fields"]
        checks = []
        if exp_sign is not None:
            checks.append(("entry_day_sign", f["entry_day_sign"] == exp_sign))
        if exp_pct is not None and f["pct_from_low"] is not None:
            lo, hi = exp_pct
            checks.append(("pct_from_low", lo <= f["pct_from_low"] / 100 <= hi))
        if sym == "VRT":
            checks.append(("R2 veto", res["veto"] is not None and "R2" in res["veto"]))
        if sym == "CBRS":
            checks.append(("R7 veto", res["veto"] is not None and "R7" in res["veto"]))

        ok = all(ok for _, ok in checks)
        fails += 0 if ok else 1
        print(f"  {sym:6s} {date}  sign={f['entry_day_sign']:5s} pct={f['pct_from_low']:>6} "
              f"rsi={f['rsi']:>5} vol={f['vol_ratio']} veto={res['veto']} "
              f"{'OK' if ok else 'FAIL'}")

    print(f"\n  {'ALL 14 ENTRIES MATCH PLAN TABLE' if fails == 0 else f'{fails} CHECK(S) FAILED'}")
    sys.exit(1 if fails else 0)
