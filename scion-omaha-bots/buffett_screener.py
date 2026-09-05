"""
Warren Buffett-esque quality compounder screener.

Unlike the Burry screener (which looks for beaten-down roadkill stocks near 52W lows),
the Buffett screener looks for HIGH-QUALITY businesses with durable moats, consistent
high ROE/ROIC, solid balance sheets, and reasonable valuations.

Key differences from ScionScreener:
  - Stocks NEAR or ABOVE 52-week highs are FINE (quality compounds)
  - ROE > 15% for 5+ years (consistency)
  - Gross margins > 40% (pricing power / moat)
  - Low debt (D/E < 0.5)
  - Owner Earnings Yield > 6%
  - Durable competitive advantage indicators
"""

import datetime
import os

import pandas as pd
import yfinance as yf
from news_utils import extract_news_fields
from reflection import ReflectionLog
from screener import _discovery_tickers
from smart_money import get_smart_money_score
from ta_lib import compute_macd, compute_rsi, compute_smas


class BuffettScreener:
    """
    Buffett-style quality compounder screener.
    Looks for wonderful businesses at fair prices — not roadkill.
    """

    def __init__(self, tickers=None):
        # Default watchlist: high-quality compounders Burffett-style
        # Consumer staples, tech with moats, financials, healthcare.
        # Widened with OpenBB discovery (gainers + undervalued large caps).
        if tickers is None:
            base = [
                "AAPL", "MSFT", "GOOGL", "AMZN", "META", "BRK-B", "JPM", "V", "MA",
                "JNJ", "PG", "KO", "PEP", "WMT", "COST", "MCD", "DIS", "BAC",
                "AXP", "UNH", "ABBV", "LLY", "HD", "NKE", "TXN", "CSCO", "INTC",
                "NEE", "DHR", "BMY", "PFE", "MRK", "T", "VZ", "UPS", "CAT"
            ]
            extras = _discovery_tickers(lists=("gainers", "undervalued_large_caps"))
            known = set(base)
            self.tickers = base + [t for t in extras if t not in known]
        else:
            self.tickers = tickers
        self.results = []

    def fetch_quality_metrics(self, info, ticker_obj):
        """Extract Buffett-relevant quality metrics."""
        metrics = {
            "market_cap": info.get("marketCap"),
            "roe": info.get("returnOnEquity"),
            "roa": info.get("returnOnAssets"),
            "roic": None,  # Will calculate
            "gross_margins": info.get("grossMargins"),
            "operating_margins": info.get("operatingMargins"),
            "profit_margins": info.get("profitMargins"),
            "eps": info.get("trailingEps"),
            "forward_eps": info.get("forwardEps"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio"),
            "price_to_book": info.get("priceToBook"),
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "quick_ratio": info.get("quickRatio"),
            "total_cash": info.get("totalCash"),
            "total_debt": info.get("totalDebt"),
            "total_revenue": info.get("totalRevenue"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "fcf": info.get("freeCashflow"),
            "operating_cf": info.get("operatingCashflow"),
            "dividend_yield": info.get("dividendYield"),
            "payout_ratio": info.get("payoutRatio"),
            "insider_pct": info.get("heldPercentInsiders"),
            "institutional_pct": info.get("heldPercentInstitutions"),
            "beta": info.get("beta"),
        }

        # D/E in decimal if comes as percentage
        if metrics["debt_to_equity"] is not None and metrics["debt_to_equity"] > 10:
            metrics["debt_to_equity"] = metrics["debt_to_equity"] / 100.0

        # Calculate ROIC if possible
        # ROIC = NOPAT / (Total Debt + Total Equity) approx = EBIT*(1-tax) / Invested Capital
        # For screener, use Operating Income / (Total Debt + Market Cap - Cash)
        operating_income = info.get("operatingCashflow", 0)
        if operating_income and metrics["total_debt"] is not None and metrics["market_cap"]:
            invested_capital = metrics["total_debt"] + metrics["market_cap"] - (metrics["total_cash"] or 0)
            if invested_capital > 0:
                metrics["roic"] = operating_income / invested_capital

        # Owner Earnings (simplified): Net Income + D&A - Maintenance CapEx
        # Approximation: FCF + (Operating CF - FCF - CapEx) = simplified
        # For screening, approximate: Net Income (cleaner) → FCF/Market Cap = Owner Earnings Yield
        if metrics["fcf"] and metrics["market_cap"]:
            metrics["fcf_yield"] = metrics["fcf"] / metrics["market_cap"]
            metrics["owner_earnings_yield"] = metrics["fcf_yield"]  # Approx
        else:
            metrics["fcf_yield"] = None
            metrics["owner_earnings_yield"] = None

        return metrics

    def evaluate_moat(self, info, metrics):
        """Evaluate moat signals based on margins and returns."""
        moat_score = 0
        moat_notes = []

        gm = metrics.get("gross_margins")
        om = metrics.get("operating_margins")
        roe = metrics.get("roe")
        roa = metrics.get("roa")

        # Gross margin > 40% = pricing power (strong moat)
        if gm and gm > 0.40:
            moat_score += 20
            moat_notes.append(f"High gross margins ({gm*100:.1f}%) = pricing power")
        elif gm and gm > 0.25:
            moat_score += 10
            moat_notes.append(f"Moderate gross margins ({gm*100:.1f}%)")
        elif gm and gm < 0.15:
            moat_notes.append(f"Low gross margins ({gm*100:.1f}%) — possible commodity business")
            moat_score -= 10

        # Operating margin > 20% = efficient operations
        if om and om > 0.20:
            moat_score += 15
            moat_notes.append(f"Strong operating margins ({om*100:.1f}%)")
        elif om and om > 0.10:
            moat_score += 5
        elif om and om < 0.05:
            moat_score -= 10
            moat_notes.append(f"Weak operating margin ({om*100:.1f}%)")

        # ROE > 15% consistent = compounding machine
        if roe and roe > 0.20:
            moat_score += 20
            moat_notes.append(f"Exceptional ROE ({roe*100:.1f}%)")
        elif roe and roe > 0.15:
            moat_score += 15
            moat_notes.append(f"Strong ROE ({roe*100:.1f}%)")
        elif roe and roe < 0.08:
            moat_score -= 10
            moat_notes.append(f"Weak ROE ({roe*100:.1f}%)")

        # ROA > 10% = asset-light efficient
        if roa and roa > 0.10:
            moat_score += 10
        elif roa and roa < 0.04:
            moat_score -= 5

        return moat_score, moat_notes

    def evaluate_financial_health(self, metrics):
        """Berkshire-style balance sheet strength assessment."""
        health_score = 0
        notes = []

        de = metrics.get("debt_to_equity")
        if de is not None:
            if de < 0.30:
                health_score += 20
                notes.append(f"Fortress balance sheet (D/E {de:.2f})")
            elif de < 0.50:
                health_score += 15
                notes.append(f"Low leverage (D/E {de:.2f})")
            elif de < 1.0:
                health_score += 5
                notes.append(f"Moderate leverage (D/E {de:.2f})")
            else:
                notes.append(f"Moderate-high leverage (D/E {de:.2f})")
                health_score -= 5

        # Cash position
        cash = metrics.get("total_cash")
        debt = metrics.get("total_debt")
        if cash and debt:
            if cash > debt:
                health_score += 15
                notes.append("Net cash position (cash > debt)")
            elif cash > debt * 0.5:
                health_score += 5
                notes.append("Substantial cash relative to debt")
            else:
                notes.append("Low cash buffer")

        # Current ratio > 1.5
        cr = metrics.get("current_ratio")
        if cr and cr > 2.0:
            health_score += 10
        elif cr and cr > 1.5:
            health_score += 5
        elif cr and cr < 1.0:
            health_score -= 10
            notes.append("Low current ratio — liquidity risk")

        return health_score, notes

    def evaluate_valuation(self, metrics, current_price):
        """Buffett's price discipline — reasonable but not rigid."""
        val_score = 0
        notes = []

        pe = metrics.get("pe_ratio")
        fpe = metrics.get("forward_pe")
        peg = metrics.get("peg_ratio")
        oe_yield = metrics.get("owner_earnings_yield")

        # P/E relative assessment (Buffett doesn't use rigid cutoffs)
        if pe:
            if pe < 15:
                val_score += 20
                notes.append(f"Attractive P/E ({pe:.1f}x)")
            elif pe < 20:
                val_score += 15
                notes.append(f"Reasonable P/E ({pe:.1f}x)")
            elif pe < 25:
                val_score += 10
                notes.append(f"Elevated P/E ({pe:.1f}x) — quality premium acceptable")
            elif pe < 35:
                val_score += 5
                notes.append(f"High P/E ({pe:.1f}x) — only for exceptional growth")
            else:
                notes.append(f"Very high P/E ({pe:.1f}x) — risky even for moat")
                val_score -= 10

        # Forward P/E (more relevant for growth)
        if fpe:
            if fpe < 15:
                val_score += 15
            elif fpe < 20:
                val_score += 10
            elif fpe < 30:
                val_score += 5
            else:
                val_score -= 5
                notes.append(f"High forward P/E ({fpe:.1f}x) — premium priced")

        # PEG ratio ( Buffett prefers < 1.5 but accepts up to 2 for quality)
        if peg:
            if peg < 1.0:
                val_score += 15
                notes.append(f"Excellent PEG ({peg:.2f})")
            elif peg < 1.5:
                val_score += 10
                notes.append(f"Good PEG ({peg:.2f})")
            elif peg < 2.0:
                val_score += 5
            elif peg > 3.0:
                val_score -= 10
                notes.append(f"Expensive PEG ({peg:.2f})")

        # Owner earnings yield (Buffett's preferred metric)
        if oe_yield:
            if oe_yield > 0.08:
                val_score += 15
                notes.append(f"Strong owner earnings yield ({oe_yield*100:.1f}%)")
            elif oe_yield > 0.05:
                val_score += 10
                notes.append(f"Decent owner earnings yield ({oe_yield*100:.1f}%)")
            elif oe_yield > 0.03:
                val_score += 5
            else:
                val_score -= 5
                notes.append(f"Low owner earnings yield ({oe_yield*100:.1f}%)")

        return val_score, notes

    def evaluate_growth_quality(self, metrics):
        """Buffett wants businesses that compound earnings over time."""
        g_score = 0
        notes = []

        rev_g = metrics.get("revenue_growth")
        eps_g = metrics.get("earnings_growth")

        if rev_g and rev_g > 0.15:
            g_score += 15
            notes.append(f"Strong revenue growth ({rev_g*100:.1f}%)")
        elif rev_g and rev_g > 0.07:
            g_score += 10
            notes.append(f"Healthy revenue growth ({rev_g*100:.1f}%)")
        elif rev_g and rev_g < 0:
            g_score -= 10
            notes.append(f"Revenue declining ({rev_g*100:.1f}%) — secular concern")

        if eps_g and eps_g > 0.15:
            g_score += 15
            notes.append(f"Strong earnings growth ({eps_g*100:.1f}%)")
        elif eps_g and eps_g > 0.07:
            g_score += 10
            notes.append(f"Healthy earnings growth ({eps_g*100:.1f}%)")
        elif eps_g and eps_g < 0:
            g_score -= 10
            notes.append(f"EPS declining ({eps_g*100:.1f}%)")

        return g_score, notes

    def analyze_news_quality(self, news_raw):
        """Buffett cares about business-quality news, not swing-catalyst news."""
        if not news_raw:
            return 0.0, "No news"

        news_list = extract_news_fields(news_raw)

        # Buffett cares about: management changes, dividend hikes/buybacks,
        # acquisitions (sometimes), long-term contract wins, structural issues
        positive_keywords = [
            "buyback", "dividend hike", "dividend increase", "raise dividend",
            "insider buy", "long-term contract", "acquisition approved",
            "new partnership", "expansion", "guidance raised", "record quarter",
            "strong demand", "innovation", "patent", "market share gains"
        ]
        negative_keywords = [
            "fraud", "accounting irregularity", "SEC investigation", "lawsuit",
            "executive resignation", "CEO ousted", " missed guidance", "guidance cut",
            "recall", "regulatory fine", "antitrust", "market share loss",
            "declining", "secular decline", "disruption", "competition intensifying"
        ]

        pos = 0
        neg = 0
        for item in news_list[:8]:
            title = item.get("title", "").lower()
            for kw in positive_keywords:
                if kw in title:
                    pos += 1
            for kw in negative_keywords:
                if kw in title:
                    neg += 1

        if pos + neg == 0:
            return 0.0, "Neutral news flow"

        score = ((pos - neg) / (pos + neg)) * 100
        if score > 30:
            label = "Positive quality signals"
        elif score < -30:
            label = "Negative quality signals — caution"
        else:
            label = "Mixed news"
        return score, label

    def run_screener(self):
        """Execute the Buffett screening loop."""
        rl = ReflectionLog()
        reflection_context = rl.format_for_screener(bot="omaha")
        print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Launching Buffett Quality Compounder Screener...")
        print(f"Screening {len(self.tickers)} candidates for Buffett-grade businesses...\n")
        if reflection_context:
            print(f"[Reflections loaded: {len(rl.get_recent(bot='omaha'))} entries]")

        for symbol in self.tickers:
            try:
                print(f"Analyzing {symbol}...")
                ticker = yf.Ticker(symbol)
                info = ticker.info
                hist = ticker.history(period="1y")
                if hist.empty:
                    continue

                metrics = self.fetch_quality_metrics(info, ticker)
                current_price = float(hist["Close"].iloc[-1])
                low_52w = float(hist["Close"].min())
                high_52w = float(hist["Close"].max())
                # "52W range" only means that on >= ~120 sessions (entry-timing plan R7 floor).
                # Below that, display N/A instead of labeling a since-listing window as 52W.
                if len(hist) >= 120:
                    pct_from_high = (current_price - high_52w) / high_52w if high_52w > 0 else None
                    pct_from_low = (current_price - low_52w) / low_52w if low_52w > 0 else None
                else:
                    pct_from_high = pct_from_low = None

                # Score components
                moat_score, moat_notes = self.evaluate_moat(info, metrics)
                health_score, health_notes = self.evaluate_financial_health(metrics)
                val_score, val_notes = self.evaluate_valuation(metrics, current_price)
                growth_score, growth_notes = self.evaluate_growth_quality(metrics)

                # News quality (Buffett-style)
                news = ticker.news
                news_score, news_label = self.analyze_news_quality(news)

                # Smart Money: insider activity + institutional flow (replaces static insider_pct)
                insider_pct = metrics.get("insider_pct") or 0
                sm_score = None
                insider_bonus = 0
                try:
                    sm_score = get_smart_money_score(symbol, ticker=ticker)
                    insider_bonus = round((sm_score["composite_score"] - 50) / 10)
                    insider_bonus = max(-10, min(10, insider_bonus))
                except Exception:
                    # Fallback to old logic if smart money fetch fails
                    if insider_pct > 0.10:
                        insider_bonus = 10
                    elif insider_pct > 0.05:
                        insider_bonus = 5

                # Total Buffett Score (0-100 scale)
                # Weights: Moat 35%, Financial Health 20%, Valuation 20%, Growth 15%, News 5%, Insider 5%
                # Max theoretical raw = 65*0.35 + 45*0.2 + 65*0.2 + 30*0.15 + 100*0.05 + 10*1 = 64.25
                # Normalize 64.25 -> 100 using factor 1.557
                total = moat_score * 0.35 + health_score * 0.20 + val_score * 0.20 + growth_score * 0.15 + news_score * 0.05 + insider_bonus * 1.0
                buffett_score = max(0, min(100, total * 1.557))

                # Initialize all_notes with the fundamental reasons so the trend block can append
                all_notes = moat_notes + health_notes + val_notes + growth_notes
                if insider_bonus > 0 and sm_score is None:
                    all_notes.append(f"Strong insider ownership ({insider_pct*100:.1f}%)")
                if sm_score is not None and insider_bonus != 0:
                    all_notes.append(f"Smart Money: {sm_score['label']} ({insider_bonus:+d})")
                if news_score != 0:
                    all_notes.append(f"News quality: {news_label}")

                # Trend quality modifier (TA) — ±10, entry/exit timing only
                trend_modifier = 0
                try:
                    hist_sma = compute_smas(hist["Close"], periods=[50, 200])
                    rsi_val = compute_rsi(hist["Close"])
                    macd_val = compute_macd(hist["Close"])

                    sma50 = hist_sma.get(50)
                    sma200 = hist_sma.get(200)

                    if sma50 is not None and sma200 is not None:
                        if sma50 > sma200:
                            trend_modifier += 5
                            all_notes.append("Golden cross (SMA50 > SMA200)")
                        else:
                            trend_modifier -= 5
                            all_notes.append("Death cross (SMA50 < SMA200)")

                    if rsi_val["value"] > 75:
                        trend_modifier -= 5
                        all_notes.append("RSI overbought (>75)")
                    elif 40 < rsi_val["value"] < 50:
                        trend_modifier += 5
                        all_notes.append("RSI healthy pullback zone (40-50)")

                    if macd_val["cross_signal"] == "bullish":
                        trend_modifier += 3
                        all_notes.append("MACD bullish cross")
                    elif macd_val["cross_signal"] == "bearish":
                        trend_modifier -= 3
                        all_notes.append("MACD bearish cross")

                    trend_modifier = max(-10, min(10, trend_modifier))
                    buffett_score = max(0, min(100, buffett_score + trend_modifier))
                except Exception:
                    pass

                # Final compile of reasons (fundamental notes already in all_notes from initialization above)
                if trend_modifier != 0:
                    all_notes.append(f"Trend quality: {trend_modifier:+d}")
                reasons = "; ".join(all_notes[:8]) if all_notes else "No specific highlights"

                # Threshold: 40/100 minimum
                if buffett_score >= 40:
                    self.results.append({
                        "Symbol": symbol,
                        "Company": info.get("longName", symbol),
                        "Price": round(current_price, 2),
                        "Pct from 52W High": f"{pct_from_high * 100:.1f}%" if pct_from_high is not None else "N/A",
                        "Pct from 52W Low": f"{pct_from_low * 100:.1f}%" if pct_from_low is not None else "N/A",
                        "RSI": round(compute_rsi(hist["Close"])["value"], 1),
                        "SMA50": round(compute_smas(hist["Close"], periods=[50]).get(50, 0), 2),
                        "Smart Money": sm_score["composite_score"] if sm_score else "N/A",
                        "ROE": f"{metrics['roe']*100:.1f}%" if metrics.get("roe") else "N/A",
                        "Gross Margin": f"{metrics['gross_margins']*100:.1f}%" if metrics.get("gross_margins") else "N/A",
                        "D/E": round(metrics["debt_to_equity"], 2) if metrics.get("debt_to_equity") is not None else "N/A",
                        "FCF Yield": f"{metrics['fcf_yield']*100:.1f}%" if metrics.get("fcf_yield") else "N/A",
                        "P/E": round(metrics["pe_ratio"], 1) if metrics.get("pe_ratio") else "N/A",
                        "PEG": round(metrics["peg_ratio"], 2) if metrics.get("peg_ratio") else "N/A",
                        "News Quality": news_label,
                        "Buffett Score": round(buffett_score, 1),
                        "Reasons": reasons
                    })
                else:
                    print(f"  -> {symbol} scored {buffett_score:.1f}/100 (below 40 threshold, skipping)")

            except Exception as e:
                print(f"Error screening {symbol}: {e!s}")

        df = pd.DataFrame(self.results)
        if not df.empty:
            df = df.sort_values(by="Buffett Score", ascending=False)
        return df


if __name__ == "__main__":
    screener = BuffettScreener()
    results_df = screener.run_screener()

    print("\n" + "=" * 60)
    print("         BUFFETT QUALITY COMPOUNDER SCREENER RESULTS")
    print("=" * 60)

    if results_df.empty:
        print("No candidates processed successfully.")
    else:
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1200)
        display_cols = ["Symbol", "Price", "ROE", "Gross Margin", "D/E", "FCF Yield", "P/E", "PEG", "Smart Money", "Buffett Score"]
        print(results_df[display_cols].to_string(index=False))

        # Save to markdown
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "buffett_screener_output.md")
        with open(output_path, "w") as f:
            f.write("# Buffett Quality Compounder Screener Report\n")
            f.write(f"Generated on: {datetime.date.today().strftime('%B %d, %Y')}\n\n")
            try:
                f.write(results_df.to_markdown(index=False))
            except Exception:
                f.write(results_df.to_string(index=False))
        print(f"\nScreener output saved to: {output_path}")
