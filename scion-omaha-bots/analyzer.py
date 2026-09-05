import datetime
import os
import sys

import pandas as pd
import yfinance as yf
from news_utils import extract_news_fields
from smart_money import get_smart_money_score
from ta_lib import compute_all as compute_ta


class ScionAnalyzer:
    """
    Michael Burry-esque deep-dive fundamental and technical analyzer.
    Performs conservative DCF and NCAV (Net-Net) valuations, balances sheet stress-testing,
    technical support validation, and entry/exit strategy framing.
    """
    def __init__(self, symbol):
        self.symbol = symbol.upper()
        self.ticker = yf.Ticker(self.symbol)
        self.info = {}
        self.hist = pd.DataFrame()
        self.financials = pd.DataFrame()
        self.balance_sheet = pd.DataFrame()
        self.cashflow = pd.DataFrame()

    def fetch_all_data(self):
        """Fetch all necessary ticker details, financials, and history."""
        print(f"Fetching data for {self.symbol}...")
        self.info = self.ticker.info
        self.hist = self.ticker.history(period="1y") # 1 year for technical analysis
        
        # Get financial statements (annual)
        self.financials = self.ticker.financials
        self.balance_sheet = self.ticker.balance_sheet
        self.cashflow = self.ticker.cashflow

        if self.financials.empty or self.balance_sheet.empty or self.cashflow.empty:
            print("Warning: Annual financial statements are incomplete. Some models will use fallback info.")

    def run_dcf_model(self, discount_rate=0.10, growth_rate=0.04, terminal_growth=0.02):
        """
        Conservative Discounted Free Cash Flow (DFCF) model.
        Projects FCF for 5 years and discounts back to present.
        """
        fcf = self.info.get("freeCashflow")
        market_cap = self.info.get("marketCap")
        shares_outstanding = self.info.get("sharesOutstanding")
        current_price = self.hist['Close'].iloc[-1] if not self.hist.empty else self.info.get("currentPrice")

        # Fallback FCF calculation from Cash Flow Statement
        if fcf is None and not self.cashflow.empty:
            try:
                ocf = self.cashflow.loc['Operating Cash Flow'].iloc[0] if 'Operating Cash Flow' in self.cashflow.index else 0
                capex = self.cashflow.loc['Capital Expenditures'].iloc[0] if 'Capital Expenditures' in self.cashflow.index else 0
                fcf = ocf + capex # Capex is negative, so this subtracts capex
            except Exception:
                pass

        if not fcf or fcf <= 0 or not shares_outstanding or not current_price:
            return None # Cannot calculate DCF

        # Project FCF for next 5 years
        projected_fcf = []
        temp_fcf = fcf
        for year in range(1, 6):
            temp_fcf *= (1 + growth_rate)
            projected_fcf.append(temp_fcf)

        # Discount FCFs to present value
        discount_factors = [(1 + discount_rate) ** year for year in range(1, 6)]
        pv_fcf = [fcf_val / factor for fcf_val, factor in zip(projected_fcf, discount_factors)]
        sum_pv_fcf = sum(pv_fcf)

        # Calculate Terminal Value (using Gordon Growth Model on Year 5 FCF)
        terminal_value = (projected_fcf[-1] * (1 + terminal_growth)) / (discount_rate - terminal_growth)
        pv_terminal_value = terminal_value / ((1 + discount_rate) ** 5)

        # Total Enterprise Value
        intrinsic_ev = sum_pv_fcf + pv_terminal_value

        # Adjust for Net Debt to get Intrinsic Equity Value
        total_debt = self.info.get("totalDebt") or 0
        total_cash = self.info.get("totalCash") or 0
        
        intrinsic_equity = intrinsic_ev + total_cash - total_debt
        intrinsic_share_price = intrinsic_equity / shares_outstanding

        margin_of_safety = (intrinsic_share_price - current_price) / intrinsic_share_price if intrinsic_share_price > current_price else 0.0

        return {
            "Current FCF": fcf,
            "Intrinsic Share Price": round(intrinsic_share_price, 2),
            "Current Share Price": round(current_price, 2),
            "Margin of Safety": f"{margin_of_safety * 100:.1f}%" if margin_of_safety > 0 else "None",
            "Projected FCFs (5y)": [round(x, 2) for x in projected_fcf],
            "Terminal Value": round(terminal_value, 2)
        }

    def run_net_net_model(self):
        """
        Classic Benjamin Graham Net-Net (NCAV) valuation.
        NCAV = Current Assets - Total Liabilities.
        """
        if self.balance_sheet.empty:
            return None

        try:
            # Extract balance sheet rows - yfinance uses 'Current Assets' not 'Total Current Assets'
            current_assets = self.balance_sheet.loc['Current Assets'].iloc[0] if 'Current Assets' in self.balance_sheet.index else None
            # Fallback to 'Total Current Assets'
            if current_assets is None:
                current_assets = self.balance_sheet.loc['Total Current Assets'].iloc[0] if 'Total Current Assets' in self.balance_sheet.index else None
            
            total_liabilities = self.balance_sheet.loc['Total Liabilities Net Minority Interest'].iloc[0] if 'Total Liabilities Net Minority Interest' in self.balance_sheet.index else None
            
            if total_liabilities is None:
                total_liab = self.balance_sheet.loc['Total Liabilities'].iloc[0] if 'Total Liabilities' in self.balance_sheet.index else None
                total_liabilities = total_liab

            if current_assets is None or total_liabilities is None:
                return None

            ncav = current_assets - total_liabilities
            shares_outstanding = self.info.get("sharesOutstanding")
            current_price = self.hist['Close'].iloc[-1] if not self.hist.empty else self.info.get("currentPrice")

            if not shares_outstanding or not current_price:
                return None

            ncav_per_share = ncav / shares_outstanding
            net_net_ratio = current_price / ncav_per_share if ncav_per_share > 0 else 999.0

            return {
                "Total Current Assets": current_assets,
                "Total Liabilities": total_liabilities,
                "Net Current Asset Value (NCAV)": ncav,
                "NCAV per Share": round(ncav_per_share, 2),
                "Current Price": round(current_price, 2),
                "Net-Net Ratio (Price / NCAV)": round(net_net_ratio, 2) if net_net_ratio != 999.0 else "Negative",
                "Is Net-Net Candidate (Price < 2/3 NCAV)": net_net_ratio <= 0.67 if net_net_ratio != 999.0 else False
            }
        except Exception as e:
            print(f"Error modeling Net-Net: {e!s}")
            return None

    def run_financial_health_audit(self):
        """Stress-test balance sheet leverage and short-term liquidity."""
        current_ratio = self.info.get("currentRatio")
        quick_ratio = self.info.get("quickRatio")
        debt_to_equity = self.info.get("debtToEquity")
        roe = self.info.get("returnOnEquity")

        # Fallback calculations
        if debt_to_equity is not None and debt_to_equity > 10:
            debt_to_equity = debt_to_equity / 100.0

        return {
            "Current Ratio": current_ratio if current_ratio else "N/A",
            "Quick Ratio": quick_ratio if quick_ratio else "N/A",
            "Debt to Equity": debt_to_equity if debt_to_equity is not None else "N/A",
            "Return on Equity (ROE)": f"{roe * 100:.1f}%" if roe else "N/A",
            "Short Interest % of Float": f"{self.info.get('shortPercentOfFloat', 0) * 100:.2f}%" if self.info.get('shortPercentOfFloat') else "N/A",
            "Insider Ownership": f"{self.info.get('heldPercentInsiders', 0) * 100:.2f}%" if self.info.get('heldPercentInsiders') else "N/A"
        }

    def _classify_regime(self, ta, current_price):
        """Classify overall technical regime from combined TA signals."""
        rsi = ta["rsi"]["value"]
        sma50 = ta["sma"].get(50)
        sma200 = ta["sma"].get(200)
        macd_cross = ta["macd"]["cross_signal"]

        if sma50 is not None and sma200 is not None:
            if rsi < 30:
                return "Bearish but oversold — mean-reversion opportunity"
            if current_price < sma50 and macd_cross == "bearish":
                return "Bearish — below SMA50 with MACD confirmation"
            if current_price > sma50 and macd_cross == "bullish":
                return "Bullish — above SMA50 with MACD confirmation"
            if current_price < sma200:
                return "Bearish — below SMA200 (downtrend)"
            if rsi > 70:
                return "Bullish but overbought — wait for pullback"
            if current_price > sma50:
                return "Bullish — trending above SMA50"
        return "Neutral — no clear signal"

    def determine_technical_levels(self):
        """Full technical analysis with RSI, MACD, Bands, ATR, Squeeze."""
        if self.hist.empty:
            return None

        ta = compute_ta(self.hist)
        current_price = float(self.hist["Close"].iloc[-1])

        lower_bb = ta["bollinger"]["lower"] or 0
        sma100 = ta["sma"].get(100, ta["sma"].get(50, lower_bb))
        low_52w = float(self.hist["Close"].min())

        upper_bb = ta["bollinger"]["upper"] or 0
        sma50 = ta["sma"].get(50, upper_bb)
        high_52w = float(self.hist["Close"].max())

        atr_val = ta["atr"]["value"] or 0
        if atr_val > 0:
            dynamic_stop = max(low_52w, current_price - 3 * atr_val)
        else:
            # Fallback: 8% below current price if no ATR data
            dynamic_stop = max(low_52w, current_price * 0.92)

        squeeze_label = "ON" if ta["squeeze"]["squeeze_on"] else "OFF"
        if ta["squeeze"]["squeeze_on"]:
            squeeze_label += f" ({ta['squeeze']['bars_in_squeeze']} bars, {ta['squeeze']['histogram_color']})"

        regime = self._classify_regime(ta, current_price)

        return {
            "Current Price": round(current_price, 2),
            "52-Week Low": round(low_52w, 2),
            "52-Week High": round(high_52w, 2),
            "Entry Zone": f"${round(low_52w, 2)} - ${round(low_52w * 1.15, 2)}",
            "Suggested Stop Loss": round(dynamic_stop, 2),
            "Target 1 (+20% Pop)": round(current_price * 1.20, 2),
            "Target 2 (+40% Pop)": round(current_price * 1.40, 2),
            "RSI": ta["rsi"],
            "MACD": ta["macd"],
            "SMAs": ta["sma"],
            "Bollinger Bands": ta["bollinger"],
            "ATR": round(atr_val, 2),
            "TTM Squeeze": squeeze_label,
            "Volume": ta["volume"],
            "Support Levels": {
                "S1 (lower BB)": round(lower_bb, 2) if lower_bb else 0,
                "S2 (SMA100)": round(sma100, 2) if sma100 else 0,
                "S3 (52W low)": round(low_52w, 2)
            },
            "Resistance Levels": {
                "R1 (SMA50)": round(sma50, 2) if sma50 is not None else 0,
                "R2 (upper BB)": round(upper_bb, 2) if upper_bb else 0,
                "R3 (52W high)": round(high_52w, 2)
            },
            "Signal Regime": regime
        }

    def run_news_catalyst_analyzer(self):
        """Parse yfinance news and evaluate catalyst scoring and 'ick' context."""
        news_raw = self.ticker.news
        if not news_raw:
            return []

        news_items = extract_news_fields(news_raw, legacy=True)
        analyzed_news = []
        for item in news_items[:5]:  # Top 5 news articles
            title = item.get("title", "")
            publisher = item.get("publisher", "")
            link = item.get("link", "")

            # Simple catalyst classification
            sentiment = "Neutral"
            title_lower = title.lower()
            if any(w in title_lower for w in ["miss", "drop", "plunge", "crisis", "cut", "downgrade", "debt", "bankruptcy"]):
                sentiment = "Ick / Panic Capitulation"
            elif any(w in title_lower for w in ["buyback", "insider", "purchase", "upgrade", "beat", "contract", "approval"]):
                sentiment = "Reversal / Catalyst"

            analyzed_news.append({
                "Title": title,
                "Publisher": publisher,
                "Sentiment Class": sentiment,
                "Link": link
            })
        return analyzed_news

    def generate_full_report(self):
        """Execute all modules and assemble the full Scion Analysis Report in Markdown."""
        self.fetch_all_data()
        
        dcf = self.run_dcf_model()
        net_net = self.run_net_net_model()
        health = self.run_financial_health_audit()
        tech = self.determine_technical_levels()
        news = self.run_news_catalyst_analyzer()

        current_price = tech["Current Price"] if tech else self.info.get("currentPrice", "N/A")
        
        report = []
        report.append(f"# SCION SWING TRADE ANALYTICS: {self.symbol}")
        report.append(f"> **Target Asset:** {self.info.get('longName', self.symbol)}")
        report.append(f"> **Sector/Industry:** {self.info.get('sector', 'N/A')} / {self.info.get('industry', 'N/A')}")
        report.append(f"> **Analysis Date:** {datetime.date.today().strftime('%B %d, %Y')}\n")
        report.append("---")

        # 1. Executive Setup
        report.append("\n## Executive Setup")
        report.append("| Parameter | Value | Details |")
        report.append("| :--- | :--- | :--- |")
        report.append(f"| **Current Price** | ${current_price} | Current market trade price |")
        if tech:
            report.append(f"| **Entry Zone** | {tech['Entry Zone']} | Under Burry's 10-15% of 52W low threshold |")
            report.append(f"| **Stop Loss** | ${tech['Suggested Stop Loss']} | Non-negotiable 52W low cutoff level |")
            report.append(f"| **Target 1 (+20%)** | ${tech['Target 1 (+20% Pop)']} | First profit-taking scale-out point |")
            report.append(f"| **Target 2 (+40%)** | ${tech['Target 2 (+40% Pop)']} | Full liquidation target point |")
            report.append(f"| **52-Week Range** | ${tech['52-Week Low']} - ${tech['52-Week High']} | Historical price range |")

        # Insert Technical Analysis section
        if tech:
            report.append("\n## Technical Analysis")
            report.append("| Indicator | Value | Signal |")
            report.append("| :--- | :--- | :--- |")
            report.append(f"| **RSI(14)** | {tech['RSI']['value']} | {tech['RSI']['regime'].upper()} |")
            macd = tech['MACD']
            macd_signal = macd['cross_signal'] or 'neutral'
            report.append(f"| **MACD(12,26,9)** | {macd['macd_line']} / {macd['signal_line']} | {macd_signal} (hist: {macd['histogram']}) |")
            sma50 = tech['SMAs'].get(50)
            sma200 = tech['SMAs'].get(200)
            if sma50 is not None and sma200 is not None:
                report.append(f"| **SMA50 / SMA200** | ${sma50} / ${sma200} | Price vs SMA50: {'above' if current_price > sma50 else 'below'} |")
            elif sma50 is not None:
                report.append(f"| **SMA50** | ${sma50} | Price vs SMA50: {'above' if current_price > sma50 else 'below'} |")
            else:
                report.append("| **SMA50 / SMA200** | N/A | Insufficient history |")
            bb = tech['Bollinger Bands']
            if bb['upper']:
                report.append(f"| **Bollinger (20,2)** | L ${bb['lower']} / M ${bb['middle']} / U ${bb['upper']} | %B: {bb['percent_b']} |")
            report.append(f"| **ATR(14)** | ${tech['ATR']} | Avg daily range |")
            report.append(f"| **TTM Squeeze** | {tech['TTM Squeeze']} | {'Watch for breakout' if 'ON' in tech['TTM Squeeze'] else 'Normal volatility'} |")
            vol = tech['Volume']
            report.append(f"| **Volume** | {vol['current_volume']:,.0f} ({vol['ratio']}x avg) | {vol['regime'].upper()} |")

            report.append("\n**Support Levels:**")
            for k, v in tech['Support Levels'].items():
                report.append(f"  - {k}: ${v}")
            report.append("\n**Resistance Levels:**")
            for k, v in tech['Resistance Levels'].items():
                report.append(f"  - {k}: ${v}")
            report.append(f"\n**Regime:** {tech['Signal Regime']}")

        # Smart Money section
        try:
            sm = get_smart_money_score(self.symbol)
            report.append("\n## Smart Money Signals")
            report.append(f"**Composite Score:** {sm['composite_score']}/100 -- {sm['label']}")
            insider = sm["insider_detail"]
            if insider["total_transactions"] > 0:
                report.append("\n### Insider Activity")
                report.append(f"- **Net shares (6mo):** {insider['net_shares_6mo']:+,.0f}")
                report.append(f"- **Buy pct:** {insider['buy_pct']*100:.1f}% of {insider['total_transactions']} transactions")
                report.append(f"- **Signal:** {insider['signal'].capitalize()} ({insider['score']:+d})")
                if insider["details"]:
                    report.append("\n| Date | Insider | Position | Type | Shares | Value |")
                    report.append("|---|---|---|---|---|---|")
                    for d in insider["details"][:8]:
                        report.append(f"| {d['date']} | {d['insider']} | {d['position']} | {d['type']} | {d['shares']:,} | ${d['value']:,.0f} |")
            inst = sm["institutional_detail"]
            if inst["holder_count"] > 0:
                report.append("\n### Institutional Ownership")
                report.append(f"- **Total holders:** {inst['holder_count']}")
                report.append(f"- **Adding / reducing:** {inst['net_adding']} adding, {inst['net_reducing']} reducing")
                report.append(f"- **Avg pct change:** {inst['avg_pct_change']:+.2f}%")
                report.append(f"- **Institutions pct of float:** {inst['institutions_pct']:.1f}%")
                report.append(f"- **Signal:** {inst['signal'].capitalize()} ({inst['score']:+d})")
                if inst["top_holders"]:
                    report.append("\n| Holder | Shares | Pct Held | Pct Change |")
                    report.append("|---|---|---|---|")
                    for h in inst["top_holders"][:8]:
                        report.append(f"| {h['holder']} | {h['shares']:,} | {h['pct_held']*100:.2f}% | {h['pct_change']:+.2f}% |")
        except Exception:
            pass

        # 2. Intrinsic Valuation Models
        report.append("\n## Intrinsic Valuation Models")
        if dcf:
            report.append("### 1. Conservative Discounted Cash Flow (DCF)")
            report.append(f"- **Implied Share Price:** ${dcf['Intrinsic Share Price']}")
            report.append(f"- **Margin of Safety:** {dcf['Margin of Safety']}")
            report.append(f"- **Projected Terminal Value:** ${dcf['Terminal Value']:,}")
            report.append("- *Growth Assumption: 4% annual FCF growth for 5y; 2% terminal growth; 10% discount rate.*")
        else:
            report.append("\n### 1. Discounted Cash Flow (DCF)")
            report.append("*Could not model DCF: Company has negative, unstable, or missing Free Cash Flow data.*")

        if net_net:
            report.append("\n### 2. Graham Net-Net (NCAV) Model")
            report.append(f"- **Net Current Asset Value (NCAV):** ${net_net['Net Current Asset Value (NCAV)'] / 1e6:.2f} Million")
            report.append(f"- **NCAV per Share:** ${net_net['NCAV per Share']}")
            report.append(f"- **Price / NCAV Ratio:** {net_net['Net-Net Ratio (Price / NCAV)']}")
            report.append(f"- **Is Graham Net-Net Asset Play?** {'**YES** (Price < 2/3 NCAV)' if net_net['Is Net-Net Candidate (Price < 2/3 NCAV)'] else 'No'}")
        else:
            report.append("\n### 2. Graham Net-Net (NCAV) Model")
            report.append("*Could not model NCAV: Balance sheet data incomplete or current assets do not exceed total liabilities.*")

        # 3. Balance Sheet Stress-Test & Ownership
        report.append("\n## Balance Sheet & Ownership Audit")
        report.append("| Metric | Value | Burry Ideal Guardrails | Rating |")
        report.append("| :--- | :--- | :--- | :--- |")
        cr = health.get("Current Ratio")
        cr_rating = "Fortress" if isinstance(cr, float) and cr >= 2.0 else ("Adequate" if isinstance(cr, float) and cr >= 1.5 else "Weak")
        report.append(f"| **Current Ratio** | {cr} | $\\ge 2.0$ | {cr_rating} |")
        
        de = health.get("Debt to Equity")
        de_rating = "Fortress" if isinstance(de, float) and de <= 0.5 else ("Adequate" if isinstance(de, float) and de <= 1.0 else "Leveraged")
        report.append(f"| **Debt to Equity** | {de} | $\\le 0.50$ (or $\\le 1.0$) | {de_rating} |")
        
        report.append(f"| **Return on Equity (ROE)** | {health.get('Return on Equity (ROE)')} | 12% - 25% | - |")
        report.append(f"| **Insider Ownership** | {health.get('Insider Ownership')} | $\\ge 10.0\\%$ Preferred | - |")
        report.append(f"| **Short Interest % of Float** | {health.get('Short Interest % of Float')} | High short interest adds squeeze potential | - |")

        # 4. News Catalyst & Sentiment Intake
        report.append("\n## News Catalyst & Sentiment Intake")
        if news:
            for item in news:
                report.append(f"- **[{item['Sentiment Class']}]** {item['Title']}")
                report.append(f"  *Source: {item['Publisher']}*")
        else:
            report.append("*No recent news found.*")

        # 5. Swing Trading Thesis & Mechanics
        report.append("\n## Scion Swing Thesis & Mechanics")
        report.append("### The Bull Case (Reversal Rebound)")
        report.append(f"1. **Extremely Low Valuation:** Stock is trading at a depressed price range near its 52-week low of ${tech['52-Week Low'] if tech else 'N/A'}, pricing in extreme market fear.")
        report.append("2. **Asset Floor Support:** Strong balance sheet and liquid assets provide a cushion, minimizing the risk of permanent business failure.")
        report.append("3. **Squeeze & Mean-Reversion Potential:** High pessimism and potential short interest mean any slightly positive catalyst news could spark a massive 20-40% recovery pop.")
        
        report.append("\n### The Bear Case (Risk Mitigation)")
        report.append("1. **Value Trap Potential:** Negative industry trends could persist, causing the stock to stagnate at the bottom for longer than expected.")
        report.append(f"2. **The Loss-Mitigation Rule Execution:** If negative forces persist and the price breaks below the 52-week support of ${tech['52-Week Low'] if tech else 'N/A'}, **immediately execute the stop-loss order at ${tech['Suggested Stop Loss'] if tech else 'N/A'}** to cut losses and protect trading capital.")

        report.append("\n---")
        report.append("\n> **DISCLAIMER:** This report is generated by a Scion-Bot simulation program based on Michael Burry's documented historical style. It is NOT investment advice. Verify all financial statements before executing trades.")

        # Save report
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"scion_report_{self.symbol}.md")
        with open(output_path, "w") as f:
            f.write("\n".join(report))
        print(f"Deep-dive Scion Report successfully generated at: {output_path}")
        
        return "\n".join(report)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyzer.py <SYMBOL>")
        sys.exit(1)
    
    symbol = sys.argv[1]
    analyzer = ScionAnalyzer(symbol)
    analyzer.generate_full_report()
