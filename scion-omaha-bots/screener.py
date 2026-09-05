import csv
import datetime
import os

import entry_timing
import pandas as pd
import yfinance as yf
from news_utils import extract_news_fields
from reflection import ReflectionLog
from smart_money import get_smart_money_score
from ta_lib import (
    compute_atr,
    compute_macd,
    compute_rsi,
    compute_smas,
    compute_ttm_squeeze,
    compute_volume_ratio,
)


def _discovery_tickers(limit=80, lists=("losers", "undervalued_large_caps")):
    """Extra universe symbols from OpenBB discovery lists; [] when unavailable.

    ponytail: caps the discovery universe at `limit`; raise the cap for a
    full ~400-symbol scan.
    """
    try:
        from openbb import obb
    except Exception:
        return []
    symbols = []
    try:
        for name in lists:
            df = getattr(obb.equity.discovery, name)().to_df()
            if df is None or df.empty or "symbol" not in df.columns:
                continue
            for s in df["symbol"].dropna().astype(str):
                s = s.strip().upper()
                if s.isalpha():
                    symbols.append(s)
    except Exception:
        pass
    seen = set()
    unique = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique[:limit]


class ScionScreener:
    """
    Michael Burry-esque swing trading screener.
    Focuses on 'roadkill' or 'ick' stocks trading near their 52-week lows,
    with strong balance sheets, high free cash flow yields, and recent negative/panic news.
    """
    def __init__(self, tickers=None):
        # Default to a small curated list of potentially undervalued/volatile sectors (Retail, Biotech, Energy, Value)
        # or a user-provided list. Widened with OpenBB discovery symbols (today's losers + undervalued large caps).
        if tickers is None:
            base = [
                "EL", "LULU", "MELI", "REGN", "MOH", "BABA", "JD", "BIDU", 
                "INTC", "CVS", "PFE", "DIS", "T", "F", "GM", "KSS",
                "M", "XOM", "CVX", "DAL", "UAL", "AAL", "LMT", "GD", "NOC"
            ]
            extras = _discovery_tickers()
            known = set(base)
            self.tickers = base + [t for t in extras if t not in known]
        else:
            self.tickers = tickers
        self.results = []
        self.shadow_rows = []

    def fetch_fundamental_metrics(self, info, ticker_obj):
        """Extract fundamental metrics with graceful fallbacks."""
        metrics = {
            "market_cap": info.get("marketCap"),
            "current_ratio": info.get("currentRatio"),
            "debt_to_equity": info.get("debtToEquity"),
            "fcf": info.get("freeCashflow"),
            "ebitda": info.get("ebitda"),
            "enterprise_value": info.get("enterpriseValue"),
            "roe": info.get("returnOnEquity"),
            "insider_pct": info.get("heldPercentInsiders"),
            "shares_outstanding": info.get("sharesOutstanding"),
        }

        # Calculate D/E in decimal format if it comes as percentage
        if metrics["debt_to_equity"] is not None and metrics["debt_to_equity"] > 10:
            metrics["debt_to_equity"] = metrics["debt_to_equity"] / 100.0

        # Fallback for FCF from Cashflow Statements if not in info
        if metrics["fcf"] is None:
            try:
                cf = ticker_obj.cashflow
                if not cf.empty:
                    # Try to calculate: Operating Cash Flow + Capital Expenditures (which is negative in statement)
                    ocf = cf.loc['Operating Cash Flow'].iloc[0] if 'Operating Cash Flow' in cf.index else 0
                    capex = cf.loc['Capital Expenditures'].iloc[0] if 'Capital Expenditures' in cf.index else 0
                    metrics["fcf"] = ocf + capex
            except Exception:
                pass

        # Calculate FCF Yield
        if metrics["fcf"] and metrics["market_cap"]:
            metrics["fcf_yield"] = metrics["fcf"] / metrics["market_cap"]
        else:
            metrics["fcf_yield"] = None

        return metrics

    def analyze_technical_support(self, hist):
        """Run full TA analysis on price history for entry/exit timing signals."""
        if hist.empty:
            return {
                "pct_from_low": None, "low_52w": None,
                "is_support_base": False,
                "rsi": {"value": 50, "regime": "neutral"},
                "macd": {"macd_line": 0, "signal_line": 0, "histogram": 0, "cross_signal": None},
                "sma": {},
                "volume": {"ratio": 0, "regime": "normal"},
                "squeeze": {"squeeze_on": False, "bars_in_squeeze": 0},
                "atr": {"value": None}
            }

        current_price = hist['Close'].iloc[-1]
        # R7 fix (entry-timing plan 2026-08-05): never fabricate pct_from_low=0.0 for
        # short history (that auto-granted +30 "Deep bottom" to young listings like CBRS).
        # Compute from available data; entry_timing.assess() vetoes the near-low thesis
        # below 120 trading days.
        low_52w = hist['Close'].min()
        pct_from_low = (current_price - low_52w) / low_52w if low_52w > 0 else None

        recent_prices = hist['Close'].iloc[-14:]
        recent_std_pct = recent_prices.std() / recent_prices.mean()
        is_support_base = (pct_from_low <= 0.15) and (recent_std_pct < 0.04)

        return {
            "pct_from_low": pct_from_low,
            "low_52w": low_52w,
            "is_support_base": is_support_base,
            "rsi": compute_rsi(hist["Close"]),
            "macd": compute_macd(hist["Close"]),
            "sma": compute_smas(hist["Close"]),
            "volume": compute_volume_ratio(hist["Volume"]),
            "squeeze": compute_ttm_squeeze(hist),
            "atr": compute_atr(hist)
        }

    def analyze_news_sentiment(self, news_raw):
        """
        Analyze news for Burry's 'ick' factors and panic capitulation.
        Looks for highly pessimistic headlines that suggest severe fear, 
        which is a contra-indicator for a contrarian value trade if support holds.
        """
        if not news_raw:
            return 0.0, "No news available"

        news_list = extract_news_fields(news_raw, legacy=True)

        # Keywords showing panic ("ick" factor) vs. positive reversals
        ick_keywords = [
            "miss", "plunge", "downgrade", "crisis", "investigation", "sue", "lawsuit",
            "crash", "slashed", "drop", "decline", "debt", "bankruptcy", "probe", "hated",
            "worst", "layoff", "struggle", "bearish", "sell", "collapse"
        ]
        reversal_keywords = [
            "buyback", "insider", "purchase", "upgrade", "settles", "resolution", "contract",
            "approval", "acquire", "beat", "recovery", "stabilize", "rebound"
        ]

        ick_score = 0
        reversal_score = 0

        for item in news_list[:8]:
            title = item.get("title", "").lower()
            for word in ick_keywords:
                if word in title:
                    ick_score += 1
            for word in reversal_keywords:
                if word in title:
                    reversal_score += 1

        total_hits = ick_score + reversal_score
        if total_hits == 0:
            sentiment_score = 0.0
        else:
            sentiment_score = ((reversal_score - ick_score) / total_hits) * 100.0

        if sentiment_score < -30:
            sentiment_label = "Extreme Panic ('Ick' Factor High)"
        elif sentiment_score > 30:
            sentiment_label = "Positive Catalyst / Reversal"
        else:
            sentiment_label = "Neutral / Quiet Pessimism"

        return sentiment_score, sentiment_label

    def run_screener(self):
        """Execute the screening loop across all tickers."""
        rl = ReflectionLog()
        reflection_context = rl.format_for_screener(bot="scion")
        print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Launching Scion Trading Screener...")
        print(f"Screening {len(self.tickers)} candidates for Michael Burry swing set-ups...")
        if reflection_context:
            print(f"[Reflections loaded: {len(rl.get_recent(bot='scion'))} entries]")

        # SPY regime for the entry-timing scalar (R6) — fetch once, reuse across symbols
        spy_hist = None
        try:
            spy_hist = yf.Ticker("SPY").history(period="1y")
        except Exception:
            pass
        
        for symbol in self.tickers:
            try:
                print(f"Analyzing {symbol}...")
                ticker = yf.Ticker(symbol)
                info = ticker.info
                
                # Fetch 1 year of daily data — needs full 52W for accurate "Dist from 52W Low"
                hist = ticker.history(period="1y")
                if hist.empty:
                    continue

                # 1. Fundamental evaluation
                fundamentals = self.fetch_fundamental_metrics(info, ticker)
                
                # 2. Technical evaluation
                tech = self.analyze_technical_support(hist)
                pct_from_low = tech["pct_from_low"]
                low_52w = tech["low_52w"]
                is_support = tech["is_support_base"]
                current_price = hist['Close'].iloc[-1]

                # 3. News analysis
                news = ticker.news
                sentiment_score, sentiment_label = self.analyze_news_sentiment(news)

                # Criteria evaluation (Burry-esque loose screening for swing trades)
                # We want: 
                #  - Trading near 52-week low (within 15%)
                #  - Solid Current ratio (> 1.5, preferably > 2)
                #  - FCF yield > 5% (or close to it)
                #  - Debt/Equity < 1.0 (to avoid imminent bankruptcy)
                
                curr_ratio = fundamentals.get("current_ratio") or 0
                d_e = fundamentals.get("debt_to_equity") or 999
                fcf_y = fundamentals.get("fcf_yield") or 0

                # Score the opportunity (0 to 100)
                scion_score = 0
                reasons = []

                # Add points for technical bottoming
                if pct_from_low <= 0.10:
                    scion_score += 30
                    reasons.append("Deep bottom (within 10% of 52W low)")
                elif pct_from_low <= 0.15:
                    scion_score += 20
                    reasons.append("Near bottom (within 15% of 52W low)")

                if is_support:
                    scion_score += 20
                    reasons.append("Established support base (low recent volatility)")

                # Add points for fundamental guardrails
                if curr_ratio >= 2.0:
                    scion_score += 15
                    reasons.append("Fortress liquidity (Current Ratio >= 2.0)")
                elif curr_ratio >= 1.5:
                    scion_score += 10
                    reasons.append("Adequate liquidity (Current Ratio >= 1.5)")

                if d_e <= 0.50:
                    scion_score += 15
                    reasons.append("Low debt risk (D/E <= 0.50)")
                elif d_e <= 1.0:
                    scion_score += 10
                    reasons.append("Moderate debt risk (D/E <= 1.0)")

                if fcf_y >= 0.08:
                    scion_score += 20
                    reasons.append(f"Exceptional cash generator (FCF Yield: {fcf_y*100:.1f}%)")
                elif fcf_y >= 0.05:
                    scion_score += 10
                    reasons.append(f"Adequate cash generator (FCF Yield: {fcf_y*100:.1f}%)")

                # "Ick" Factor modifier: high pessimistic news with stable price is bullish for contrarian swing
                if sentiment_score < -25 and pct_from_low <= 0.15:
                    scion_score += 10
                    reasons.append("High Pessimism / 'Ick' Capitulation holding support")

                # Reversal Catalyst modifier
                if sentiment_score > 25:
                    scion_score += 10
                    reasons.append("Active Reversal / Buying Catalyst news")

                # Timing layer (entry_timing.py, plan R1-R9) — shadow mode: log, don't gate.
                # Score rules R1/R3/R4/R6/R9 feed ta_modifier (+-20); vetoes R2/R5/R7 are
                # logged as VETO but not enforced until plan Phase 3.
                ta_modifier = 0

                # MACD kept as existing minor modifier (plan 3.1)
                if tech["macd"]["cross_signal"] == "bullish":
                    ta_modifier += 3
                    reasons.append("MACD bullish cross")
                elif tech["macd"]["cross_signal"] == "bearish":
                    ta_modifier -= 2
                    reasons.append("MACD bearish cross")
                score_old = max(0, min(100, scion_score + ta_modifier))

                earnings_days = None
                try:
                    from earnings import get_upcoming_earnings
                    er = get_upcoming_earnings([symbol], max_days=45)
                    if er:
                        earnings_days = er[0]["days_away"]
                except Exception:
                    pass
                timing = entry_timing.assess(hist, spy_hist=spy_hist, earnings_days=earnings_days)

                ta_modifier += timing["delta"]
                ta_modifier = max(-20, min(20, ta_modifier))
                scion_score = max(0, min(100, scion_score + ta_modifier))
                if timing["veto"]:
                    reasons.append(f"VETO: {timing['veto']} (shadow, not enforced)")
                for r in timing["reasons"]:
                    reasons.append(r)

                # Smart Money modifier — ±10, confirmation only
                sm_score = None
                sm_modifier = 0
                try:
                    sm_score = get_smart_money_score(symbol, ticker=ticker)
                    sm_modifier = round((sm_score["composite_score"] - 50) / 10)
                    sm_modifier = max(-10, min(10, sm_modifier))
                    scion_score = max(0, min(100, scion_score + sm_modifier))
                    score_old = max(0, min(100, score_old + sm_modifier))
                    if sm_modifier != 0:
                        reasons.append(f"Smart Money: {sm_modifier:+d} ({sm_score['label']})")
                except Exception:
                    pass

                # Shadow-mode log: record timing fields for EVERY screened
                # symbol (not just >= 25) so R9/ENTRY_QUALITY can be
                # calibrated from daily accumulation (plan Phase 2).
                self.shadow_rows.append({
                    "date": datetime.date.today().isoformat(),
                    "symbol": symbol,
                    "close": round(current_price, 2),
                    "score_old": score_old,
                    "scion_score": scion_score,
                    "ta_modifier": ta_modifier,
                    "timing_delta": timing["delta"],
                    "entry_trigger": timing["fields"].get("entry_trigger", ""),
                    "regime": timing["fields"].get("regime", ""),
                    "earnings_days": earnings_days if earnings_days is not None else "",
                    "veto": timing["veto"] or "",
                    "reasons": "; ".join(timing["reasons"])
                })

                # Store result only if it meets a minimum threshold (25/100)
                if scion_score >= 25:
                    self.results.append({
                        "Symbol": symbol,
                        "Company": info.get("longName", symbol),
                        "Price": round(current_price, 2),
                        "52W Low": round(low_52w, 2),
                        "Dist from Low": f"{pct_from_low * 100:.1f}%",
                        "RSI": round(tech["rsi"]["value"], 1),
                        "MACD": tech["macd"]["cross_signal"] or "neutral",
                        "SMA50": round(tech["sma"].get(50, 0), 2) if tech["sma"].get(50) else "N/A",
                        "Current Ratio": round(curr_ratio, 2) if curr_ratio else "N/A",
                        "Debt/Equity": round(d_e, 2) if d_e != 999 else "N/A",
                        "FCF Yield": f"{fcf_y * 100:.1f}%" if fcf_y else "N/A",
                        "Smart Money": sm_score["composite_score"] if sm_score else "N/A",
                        "Sentiment Score": round(sentiment_score, 1),
                        "Sentiment": sentiment_label,
                        "Entry Trigger": timing["fields"].get("entry_trigger", ""),
                        "Regime": timing["fields"].get("regime", ""),
                        "Timing Delta": timing["delta"],
                        "Score (old)": score_old,
                        "Scion Score": scion_score,
                        "Reasons": ", ".join(reasons)
                    })
                else:
                    print(f"  -> {symbol} scored {scion_score}/100 (below 25 threshold, skipping)")

            except Exception as e:
                print(f"Error screening {symbol}: {e!s}")

        # Convert results to DataFrame and sort by Scion Score
        df = pd.DataFrame(self.results)
        if not df.empty:
            df = df.sort_values(by="Scion Score", ascending=False)
        self._write_shadow_log()
        return df

    def _write_shadow_log(self):
        """Append today's per-symbol timing rows to shadow_log.csv.

        Idempotent per (date, symbol): re-runs of the screener on the same
        day append nothing new. First run creates the file with a header.
        """
        if not self.shadow_rows:
            print("Shadow log: no rows to write")
            return 0
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shadow_log.csv")
        fields = ["date", "symbol", "close", "score_old", "scion_score",
                  "ta_modifier", "timing_delta", "entry_trigger", "regime",
                  "earnings_days", "veto", "reasons"]
        seen = set()
        if os.path.exists(path) and os.path.getsize(path) > 0:
            try:
                with open(path, "r", newline="", encoding="utf-8") as f:
                    for r in csv.DictReader(f):
                        seen.add((r.get("date"), r.get("symbol")))
            except Exception as e:
                print(f"Shadow log: could not read existing log ({e}); will append anyway")
        added = 0
        rows = []
        for r in self.shadow_rows:
            key = (r["date"], r["symbol"])
            if key in seen:
                continue
            rows.append(r)
            seen.add(key)
            added += 1
        if rows:
            new_file = not os.path.exists(path) or os.path.getsize(path) == 0
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                if new_file:
                    w.writeheader()
                w.writerows(rows)
        print(f"Shadow log: {added} new row(s) appended ({len(self.shadow_rows)} screened) -> {os.path.basename(path)}")
        return added

if __name__ == "__main__":
    screener = ScionScreener()
    results_df = screener.run_screener()
    
    print("\n" + "="*50)
    print("           SCION SWING SCREENER RESULTS")
    print("="*50)
    
    if results_df.empty:
        print("No candidates processed successfully.")
    else:
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1000)
        display_cols = ["Symbol", "Price", "Dist from Low", "RSI", "MACD", "Smart Money", "Current Ratio", "FCF Yield", "Scion Score"]
        if all(c in results_df.columns for c in display_cols):
            print(results_df[display_cols].to_string(index=False))
        else:
            print(results_df.to_string(index=False))
        
        # Save results to markdown file
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screener_output.md")
        with open(output_path, "w") as f:
            f.write("# Scion Swing Trading Screener Report\n")
            f.write(f"Generated on: {datetime.date.today().strftime('%B %d, %Y')}\n\n")
            try:
                f.write(results_df.to_markdown(index=False))
            except Exception:
                f.write(results_df.to_string(index=False))
        print(f"\nScreener output successfully saved to: {output_path}")
