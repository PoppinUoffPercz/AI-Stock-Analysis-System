"""
Warren Buffett-esque deep-dive analyzer.

Performs Buffett's Four Filters analysis:
  1. Circle of Competence assessment (sector/business model)
  2. Moat durability (Graham-style metrics + quality indicators)
  3. Management quality (insider ownership, capital allocation, dividends)
  4. Reasonable Price (Owner Earnings valuation, intrinsic value DCF)

Calculates Owner Earnings (Buffett's preferred cash flow metric) and
produces a long-term intrinsic value assessment with margin of safety.
"""

import yfinance as yf
import pandas as pd
import numpy as np
import sys
import os
import datetime

from ta_lib import compute_all as compute_ta
from smart_money import get_smart_money_score
from news_utils import extract_news_fields


class BuffettAnalyzer:
    """
    Buffett Four Filters deep-dive analyzer.
    Long-horizon quality compounder assessment.
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
        """Fetch financial statements for multi-year analysis."""
        print(f"Fetching data for {self.symbol}...")
        self.info = self.ticker.info
        self.hist = self.ticker.history(period="5y")  # 5 years for trend analysis
        self.financials = self.ticker.financials
        self.balance_sheet = self.ticker.balance_sheet
        self.cashflow = self.ticker.cashflow

    def calculate_owner_earnings(self, use_buffett_formula=True):
        """
        Buffett's Owner Earnings formula (1986 letter):
        Owner Earnings = Net Income + D&A - Maintenance CapEx

        Buffett deliberately EXCLUDES working capital changes (ΔWC) because
        they are temporary and fluctuate year-to-year. True earning power
        is Net Income plus non-cash charges minus true maintenance capex.

        When use_buffett_formula=True: Net Income + D&A - CapEx
        When use_buffett_formula=False: Operating CF - CapEx (standard FCF)
        """
        try:
            ni = None
            da = None
            capex = None

            # Get Net Income from cash flow statement (Net Income From Continuing Ops)
            if "Net Income From Continuing Operations" in self.cashflow.index:
                ni = self.cashflow.loc["Net Income From Continuing Operations"].iloc[0]
            if ni is None and "Net Income" in self.cashflow.index:
                ni = self.cashflow.loc["Net Income"].iloc[0]

            # Get D&A
            if "Depreciation And Amortization" in self.cashflow.index:
                da = self.cashflow.loc["Depreciation And Amortization"].iloc[0]
            if da is None and "Depreciation Amortization Depletion" in self.cashflow.index:
                da = self.cashflow.loc["Depreciation Amortization Depletion"].iloc[0]

            # Get CapEx
            if "Capital Expenditure" in self.cashflow.index:
                capex = self.cashflow.loc["Capital Expenditure"].iloc[0]
            if capex is None and "Capital Expenditures" in self.cashflow.index:
                capex = self.cashflow.loc["Capital Expenditures"].iloc[0]

            # Buffett formula: Owner Earnings = NI + D&A - Maintenance CapEx
            if use_buffett_formula and ni is not None and pd.notna(ni) and ni > 0:
                capex_val = capex if capex is not None else 0
                if pd.notna(capex_val):
                    if capex_val < 0:
                        owner_earnings = ni + (da or 0) + capex_val
                    else:
                        owner_earnings = ni + (da or 0) - abs(capex_val)
                    if owner_earnings > 0:
                        return owner_earnings

            # Fallback: Standard FCF (Operating CF - CapEx)
            ocf = None
            if "Operating Cash Flow" in self.cashflow.index:
                ocf = self.cashflow.loc["Operating Cash Flow"].iloc[0]
            if "Cash Flow From Continuing Operating Activities" in self.cashflow.index:
                ocf = self.cashflow.loc["Cash Flow From Continuing Operating Activities"].iloc[0]

            if ocf is not None and pd.notna(ocf) and ocf > 0:
                if capex is not None and pd.notna(capex):
                    if capex < 0:
                        return ocf + capex
                    else:
                        return ocf - abs(capex)
                return ocf

            # Last resort: info dict
            fcf_info = self.info.get("freeCashflow")
            if fcf_info and fcf_info > 0:
                return fcf_info

            ocf_info = self.info.get("operatingCashflow")
            capex_info = self.info.get("capitalExpenditures")
            if ocf_info and ocf_info > 0:
                if capex_info:
                    if capex_info < 0:
                        return ocf_info + capex_info
                    else:
                        return ocf_info - abs(capex_info)
                return ocf_info

            return None

        except Exception as e:
            print(f"Owner earnings calculation warning: {e}")
            return self.info.get("freeCashflow")

    def assess_moat_durability(self):
        """Assess the strength and durability of the economic moat."""
        gm = self.info.get("grossMargins")
        om = self.info.get("operatingMargins")
        roe = self.info.get("returnOnEquity")
        roa = self.info.get("returnOnAssets")
        rev_growth = self.info.get("revenueGrowth")

        moat = {"score": 0, "type": "Unknown", "strength": "Unknown", "details": []}

        # Gross margin streak (use info only — 1 year data point)
        if gm and gm > 0.40:
            moat["score"] += 20
            moat["details"].append(f"High gross margin ({gm*100:.1f}%) — strong pricing power")
        elif gm and gm > 0.25:
            moat["score"] += 10
            moat["details"].append(f"Moderate gross margin ({gm*100:.1f}%)")
        elif gm and gm < 0.15:
            moat["score"] -= 10
            moat["details"].append(f"Low gross margin ({gm*100:.1f}%) — commodity business suspect")

        # Operating margin
        if om and om > 0.20:
            moat["score"] += 15
            moat["details"].append(f"Strong operating margin ({om*100:.1f}%)")
        elif om and om > 0.10:
            moat["score"] += 8
        elif om and om < 0.05:
            moat["score"] -= 5

        # ROE consistency (screener-friendly check)
        if roe and roe > 0.20:
            moat["score"] += 20
            moat["details"].append(f"Exceptional ROE ({roe*100:.1f}%) — compounding machine")
            moat["strength"] = "Strong"
        elif roe and roe > 0.15:
            moat["score"] += 15
            moat["details"].append(f"Solid ROE ({roe*100:.1f}%)")
        elif roe and roe < 0.08:
            moat["score"] -= 10
            moat["details"].append(f"Weak ROE ({roe*100:.1f}%) — moat may be eroding")

        # Infer moat type from sector and metrics
        sector = self.info.get("sector", "").lower()
        if sector == "technology" and gm and gm > 0.40:
            moat["type"] = "Likely switching costs / network effects"
        elif sector == "consumer defensive" or sector == "consumer staples":
            moat["type"] = "Likely brand power"
        elif sector == "financial services":
            moat["type"] = "Likely regulatory / network / cost advantage"
        elif sector == "industrials" or sector == "utilities":
            moat["type"] = "Likely regulatory barriers / scale"

        if moat["score"] >= 40:
            moat["strength"] = "Wide Moat"
        elif moat["score"] >= 25:
            moat["strength"] = "Narrow Moat"
        elif moat["score"] >= 10:
            moat["strength"] = "No Moat"
        else:
            moat["strength"] = "Negative Moat (Avoid)"

        return moat

    def assess_management_quality(self):
        """Assess whether management thinks like owners."""
        assessment = {"score": 0, "details": [], "flags": []}

        # Insider ownership
        insider_pct = self.info.get("heldPercentInsiders", 0) or 0
        if insider_pct > 0.10:
            assessment["score"] += 15
            assessment["details"].append(f"Strong insider ownership ({insider_pct*100:.1f}%)")
        elif insider_pct > 0.05:
            assessment["score"] += 10
            assessment["details"].append(f"Moderate insider ownership ({insider_pct*100:.1f}%)")
        elif insider_pct < 0.01:
            assessment["flags"].append("Very low insider ownership — minimal alignment")

        # Dividend history (10+ years preferred — we check current yield & payout)
        div_yield = self.info.get("dividendYield")
        payout = self.info.get("payoutRatio")
        if div_yield and div_yield > 0:
            assessment["score"] += 10
            assessment["details"].append(f"Pays dividend (yield {div_yield*100:.2f}%)")
            if payout and 0.20 < payout < 0.60:
                assessment["score"] += 5
                assessment["details"].append("Sustainable payout ratio")
            elif payout and payout > 0.80:
                assessment["flags"].append(f"High payout ratio ({payout*100:.0f}%) — dividend may be unsustainable")

        # Share buyback indicator: compare shares outstanding YoY if we have data
        try:
            if not self.financials.empty and "Diluted EPS" in self.financials.index:
                # If EPS is growing while net income is stable, shares are being reduced
                pass
            # Check treasury shares from balance sheet
            if not self.balance_sheet.empty and "Treasury Shares Number" in self.balance_sheet.index:
                treasury = self.balance_sheet.loc["Treasury Shares Number"]
                if not treasury.empty and len(treasury) >= 2:
                    recent = treasury.iloc[0]
                    prior = treasury.iloc[1]
                    if pd.notna(recent) and pd.notna(prior):
                        if recent > prior:
                            assessment["score"] += 15
                            assessment["details"].append("Active share buybacks (treasury shares increasing)")
                        elif recent < prior:
                            assessment["flags"].append("Possible share dilution (treasury shares decreasing)")
        except Exception:
            pass

        # Return on equity (high ROE w/o excessive leverage = good management)
        roe = self.info.get("returnOnEquity")
        de = self.info.get("debtToEquity")
        if de and de > 10:
            de = de / 100.0
        if roe and roe > 0.15 and (de is None or de < 1.0):
            assessment["score"] += 10
            assessment["details"].append("High ROE achieved without excessive leverage (Buffett approved)")
        elif roe and roe > 0.15 and de and de > 1.5:
            assessment["flags"].append("ROE is high but driven by leverage — not Buffett-quality")

        return assessment

    def evaluate_technical_trend(self):
        """Technical trend quality check for long-term holdings (entry/exit timing)."""
        if self.hist.empty or len(self.hist) < 200:
            return None
        try:
            ta = compute_ta(self.hist)
            current_price = float(self.hist["Close"].iloc[-1])

            sma50 = ta["sma"].get(50, 0)
            sma200 = ta["sma"].get(200, 0)
            golden_cross = sma50 > sma200

            price_vs_sma200 = ((current_price - sma200) / sma200 * 100) if sma200 is not None and sma200 != 0 else 0
            price_vs_sma50 = ((current_price - sma50) / sma50 * 100) if sma50 is not None and sma50 != 0 else 0

            rsi = ta["rsi"]["value"]
            squeeze = ta["squeeze"]

            if golden_cross and price_vs_sma200 > -5:
                regime = "uptrend"
            elif not golden_cross and price_vs_sma200 < -10:
                regime = "downtrend"
            else:
                regime = "neutral"

            return {
                "price_vs_sma200": round(price_vs_sma200, 1),
                "price_vs_sma50": round(price_vs_sma50, 1),
                "golden_cross": golden_cross,
                "rsi": {"value": rsi, "regime": ta["rsi"]["regime"]},
                "macd": ta["macd"]["cross_signal"],
                "squeeze": squeeze["squeeze_on"],
                "regime": regime
            }
        except Exception:
            return None

    def calculate_intrinsic_value(self, growth_rate=0.08, discount_rate=0.10, terminal_growth=0.03):
        """
        Buffett-style intrinsic value calculation using Owner Earnings.

        Intrinsic Value = Σ (Owner Earnings_t / (1 + r)^t) + TV / (1 + r)^n
        """
        shares_outstanding = self.info.get("sharesOutstanding")
        current_price = self.hist["Close"].iloc[-1] if not self.hist.empty else self.info.get("currentPrice")

        # Use calculate_owner_earnings (prefers cashflow statement over info dict)
        oe_annual = self.calculate_owner_earnings()

        # Final fallback: info freeCashflow if cashflow statement failed
        if oe_annual is None or oe_annual <= 0:
            oe_annual = self.info.get("freeCashflow")

        if not oe_annual or oe_annual <= 0 or not shares_outstanding or not current_price:
            return None

        # Stage 1: Project 10 years of owner earnings
        projected_oe = []
        temp_oe = oe_annual
        for year in range(1, 11):
            temp_oe *= (1 + growth_rate)
            projected_oe.append(temp_oe)

        # Discount to present
        pv_oe = [oe / ((1 + discount_rate) ** year) for year, oe in zip(range(1, 11), projected_oe)]
        sum_pv_oe = sum(pv_oe)

        # Terminal value (Gordon Growth)
        tv = projected_oe[-1] * (1 + terminal_growth) / (discount_rate - terminal_growth)
        pv_tv = tv / ((1 + discount_rate) ** 10)

        # Intrinsic equity value
        intrinsic_ev = sum_pv_oe + pv_tv

        # Adjust for net cash/debt
        total_debt = self.info.get("totalDebt") or 0
        total_cash = self.info.get("totalCash") or 0
        intrinsic_equity = intrinsic_ev + total_cash - total_debt

        intrinsic_share_price = intrinsic_equity / shares_outstanding
        margin_of_safety = (intrinsic_share_price - current_price) / intrinsic_share_price if intrinsic_share_price > 0 else 0

        return {
            "current_oe_annual": oe_annual,
            "oe_per_share": round(oe_annual / shares_outstanding, 2),
            "intrinsic_share_price": round(intrinsic_share_price, 2),
            "current_share_price": round(current_price, 2),
            "margin_of_safety_pct": f"{margin_of_safety * 100:.1f}%" if margin_of_safety > 0 else "None (overvalued)",
            "projected_oe_10y": [round(x, 2) for x in projected_oe],
            "terminal_value": round(tv, 2),
            "pv_terminal_value": round(pv_tv, 2),
            "sum_pv_oe_10y": round(sum_pv_oe, 2)
        }

    def assess_circle_of_competence(self):
        """Assess whether the business is understandable and stable."""
        sector = self.info.get("sector", "Unknown")
        industry = self.info.get("industry", "Unknown")
        rev_growth = self.info.get("revenueGrowth")
        beta = self.info.get("beta")

        assessment = {
            "sector": sector,
            "industry": industry,
            "simple_business": False,
            "stable_sector": False,
            "predictable": False,
            "notes": []
        }

        # Simple business heuristic: revenue per employee reasonable, low beta
        if beta and beta < 1.5:
            assessment["predictable"] = True
            assessment["notes"].append(f"Low beta ({beta:.2f}) — defensive")
        elif beta and beta > 2.0:
            assessment["notes"].append(f"High beta ({beta:.2f}) — volatile")

        # Stable sector check
        stable_sectors = ["Consumer Defensive", "Consumer Staples", "Utilities", "Financial Services", "Healthcare"]
        if sector in stable_sectors:
            assessment["stable_sector"] = True
            assessment["notes"].append(f"Stable sector ({sector})")

        # Revenue trend
        if rev_growth and rev_growth > 0.05:
            assessment["notes"].append(f"Growing revenue ({rev_growth*100:.1f}% YoY)")
        elif rev_growth and rev_growth < 0:
            assessment["notes"].append(f"Declining revenue ({rev_growth*100:.1f}%) — circle-of-competence caution")

        assessment["simple_business"] = True  # Heuristic; users should verify

        return assessment

    def generate_full_report(self):
        """Run all four filters and produce a Buffett-style analysis report."""
        self.fetch_all_data()

        # === The Four Filters ===
        coc = self.assess_circle_of_competence()
        moat = self.assess_moat_durability()
        mgmt = self.assess_management_quality()
        intrinsic = self.calculate_intrinsic_value()
        tech_trend = self.evaluate_technical_trend()
        try:
            sm_data = get_smart_money_score(self.symbol)
        except Exception:
            sm_data = None
        current_price = self.hist["Close"].iloc[-1] if not self.hist.empty else self.info.get("currentPrice", "N/A")

        # News context
        news_raw = self.ticker.news or []
        news_items = extract_news_fields(news_raw)

        # Build report
        report = []
        report.append(f"# OMAHA-BOT ANALYSIS: {self.symbol}")
        report.append(f"> **Target Asset:** {self.info.get('longName', self.symbol)}")
        report.append(f"> **Sector:** {self.info.get('sector', 'N/A')} / {self.info.get('industry', 'N/A')}")
        report.append(f"> **Analysis Date:** {datetime.date.today().strftime('%B %d, %Y')}\n")
        report.append("> *Buffett's Four Filters Analysis — Long-Horizon Quality Compounder Viewpoint*\n")
        report.append("---\n")

        # Executive Summary
        report.append("## Executive Summary")
        report.append(f"| Parameter | Value |")
        report.append(f"| :--- | :--- |")
        report.append(f"| **Current Price** | ${current_price} |")
        if intrinsic:
            oe_val = intrinsic.get('current_oe_annual')
            if isinstance(oe_val, (int, float)):
                if abs(oe_val) >= 1e9:
                    report.append(f"| **Owner Earnings (annual)** | ${oe_val/1e9:.2f}B |")
                elif abs(oe_val) >= 1e6:
                    report.append(f"| **Owner Earnings (annual)** | ${oe_val/1e6:.0f}M |")
                else:
                    report.append(f"| **Owner Earnings (annual)** | ${oe_val:,.0f} |")
            else:
                report.append("| **Owner Earnings** | N/A |")
            report.append(f"| **OE per Share** | ${intrinsic['oe_per_share']} |")
            report.append(f"| **Intrinsic Value (DCF)** | ${intrinsic['intrinsic_share_price']} |")
            report.append(f"| **Margin of Safety** | {intrinsic['margin_of_safety_pct']} |")
        report.append(f"| **Moat Strength** | {moat['strength']} ({moat['type']}) |")
        report.append("")

        # Filter 1: Circle of Competence
        report.append("## Filter 1: Circle of Competence")
        report.append(f"- **Sector:** {coc['sector']}")
        report.append(f"- **Industry:** {coc['industry']}")
        for note in coc["notes"]:
            report.append(f"- {note}")
        verdict = "PASS" if (coc["simple_business"] and coc["predictable"]) else "REVIEW"
        report.append(f"- **Verdict:** {verdict} — confirm you can project this business 10 years forward\n")

        # Filter 2: Economic Moat
        report.append("## Filter 2: Durable Competitive Advantage (Economic Moat)")
        report.append(f"- **Moat Score:** {moat['score']}/55")
        report.append(f"- **Moat Strength:** {moat['strength']}")
        report.append(f"- **Likely Moat Type:** {moat['type']}")
        report.append("\n**Indicators:**")
        for detail in moat["details"]:
            report.append(f"- {detail}")
        moat_verdict = "PASS (Wide Moat)" if moat["score"] >= 40 else ("REVIEW (Narrow Moat)" if moat["score"] >= 25 else "FAIL — Insufficient Moat")
        report.append(f"\n**Verdict:** {moat_verdict}\n")

        # Filter 3: Management Quality
        report.append("## Filter 3: Honest & Competent Management")
        report.append(f"- **Management Score:** {mgmt['score']}/55")
        report.append("\n**Positive Signals:**")
        for d in mgmt["details"]:
            report.append(f"- {d}")
        if mgmt["flags"]:
            report.append("\n**Concerns:**")
            for f in mgmt["flags"]:
                report.append(f"- [WARNING] {f}")
        mgmt_verdict = "PASS" if mgmt["score"] >= 25 else ("REVIEW" if mgmt["score"] >= 15 else "CAUTION")
        report.append(f"\n**Verdict:** {mgmt_verdict}\n")

        # Filter 4: Reasonable Price
        report.append("## Filter 4: Reasonable Price (Owner Earnings Valuation)")
        if intrinsic:
            oe_val = intrinsic.get('current_oe_annual')
            if oe_val and isinstance(oe_val, (int, float)):
                if abs(oe_val) >= 1e9:
                    report.append(f"- **Owner Earnings (annual run-rate):** ${oe_val/1e9:.2f}B")
                elif abs(oe_val) >= 1e6:
                    report.append(f"- **Owner Earnings (annual run-rate):** ${oe_val/1e6:.0f}M")
                else:
                    report.append(f"- **Owner Earnings (annual run-rate):** ${oe_val:,.0f}")
            else:
                report.append("- **Owner Earnings:** N/A")
            report.append(f"- **OE per Share:** ${intrinsic['oe_per_share']}")
            report.append(f"- **Intrinsic Share Price (10y DCF + TV):** ${intrinsic['intrinsic_share_price']}")
            report.append(f"- **Current Share Price:** ${intrinsic['current_share_price']}")
            report.append(f"- **Margin of Safety:** {intrinsic['margin_of_safety_pct']}")
            report.append(f"- *Growth assumption: 8% OE growth for 10y; 3% terminal; 10% discount rate*")
            val_verdict = "PASS (Margin of Safety Positive)" if isinstance(intrinsic['margin_of_safety_pct'], str) and "%" in intrinsic['margin_of_safety_pct'] and not intrinsic['margin_of_safety_pct'].startswith("None") else "REVIEW (No Margin of Safety)"
        else:
            report.append("*Could not calculate Owner Earnings — insufficient or negative free cash flow data.*")
            val_verdict = "FAIL — Cannot Value"
        report.append(f"\n**Verdict:** {val_verdict}\n")

        # Technical Trend Quality (entry/exit timing)
        if tech_trend:
            report.append("## Filter 5: Technical Trend Quality")
            report.append(f"- **Price vs SMA200:** {tech_trend['price_vs_sma200']:+.1f}%")
            report.append(f"- **Price vs SMA50:** {tech_trend['price_vs_sma50']:+.1f}%")
            report.append(f"- **Golden Cross (SMA50 > SMA200):** {'Yes' if tech_trend['golden_cross'] else 'No'}")
            report.append(f"- **RSI(14):** {tech_trend['rsi']['value']} -> {tech_trend['rsi']['regime'].capitalize()}")
            report.append(f"- **MACD:** {tech_trend['macd'] or 'neutral'}")
            report.append(f"- **TTM Squeeze:** {'ON' if tech_trend['squeeze'] else 'OFF'}")
            verdict = "Uptrend intact, no warning flags" if tech_trend["regime"] == "uptrend" else ("Downtrend — thesis review warranted" if tech_trend["regime"] == "downtrend" else "Mixed signals — monitor closely")
            report.append(f"- **Trend Verdict:** {verdict}")
            report.append("")

        # Smart Money section
        if sm_data:
            report.append("## Smart Money Signals")
            report.append(f"**Composite Score:** {sm_data['composite_score']}/100 -- {sm_data['label']}")
            insider = sm_data["insider_detail"]
            if insider["total_transactions"] > 0:
                report.append("\n### Insider Activity (Filter 3 Enhancement)")
                report.append(f"- **Net shares (6mo):** {insider['net_shares_6mo']:+,.0f}")
                report.append(f"- **Buy pct:** {insider['buy_pct']*100:.1f}% of {insider['total_transactions']} transactions")
                report.append(f"- **Signal:** {insider['signal'].capitalize()} ({insider['score']:+d})")
                if insider["details"]:
                    report.append("\n| Date | Insider | Position | Type | Shares | Value |")
                    report.append("|---|---|---|---|---|---|")
                    for d in insider["details"][:6]:
                        report.append(f"| {d['date']} | {d['insider']} | {d['position']} | {d['type']} | {d['shares']:,} | ${d['value']:,.0f} |")
            inst = sm_data["institutional_detail"]
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
                    for h in inst["top_holders"][:6]:
                        report.append(f"| {h['holder']} | {h['shares']:,} | {h['pct_held']*100:.2f}% | {h['pct_change']:+.2f}% |")
            report.append("")

        # Quick Stats
        report.append("## Quick Fundamental Stats")
        report.append(f"| Metric | Value | Buffett Threshold |")
        report.append(f"| :--- | :--- | :--- |")
        report.append(f"| **ROE** | {self.info.get('returnOnEquity', 0)*100:.1f}% | > 15% preferred |" if self.info.get("returnOnEquity") else "| **ROE** | N/A | > 15% |")
        report.append(f"| **Gross Margin** | {self.info.get('grossMargins', 0)*100:.1f}% | > 40% (moat indicator) |" if self.info.get("grossMargins") else "| **Gross Margin** | N/A | > 40% |")
        report.append(f"| **Operating Margin** | {self.info.get('operatingMargins', 0)*100:.1f}% | > 20% |" if self.info.get("operatingMargins") else "| **Operating Margin** | N/A | > 20% |")
        de = self.info.get("debtToEquity")
        if de and de > 10: de = de / 100
        report.append(f"| **Debt/Equity** | {de:.2f} | < 0.50 |" if de is not None else "| **Debt/Equity** | N/A | < 0.50 |")
        report.append(f"| **P/E Ratio** | {self.info.get('trailingPE', 'N/A')} | < 25 (flexible) |")
        report.append(f"| **Forward P/E** | {self.info.get('forwardPE', 'N/A')} | < 20 |")
        report.append(f"| **PEG Ratio** | {self.info.get('pegRatio', 'N/A')} | < 2.0 |")
        report.append(f"| **FCF Yield** | {(self.info.get('freeCashflow', 0) / self.info.get('marketCap', 1))*100:.1f}% | > 5% |" if self.info.get("freeCashflow") and self.info.get("marketCap") else "| **FCF Yield** | N/A | > 5% |")
        report.append("")

        # Recent News (Long-Term Quality View)
        report.append("## Recent News (Quality Compounder View)")
        if news_items:
            for item in news_items[:5]:
                report.append(f"- {item['title']} — *{item['publisher']}*")
        else:
            report.append("*No recent news found.*")

        # Final Verdict
        report.append("\n## Final Buffett Verdict\n")
        overall = "All Four Filters Pass — **Buffett-Grade Compounder Candidate**"
        if moat["score"] < 25:
            overall = "Moat filter concern — approach with caution"
        elif mgmt["score"] < 15:
            overall = "Management filter concern — review capital allocation"
        elif intrinsic and "None" in str(intrinsic.get("margin_of_safety_pct", "")):
            overall = "Price filter concern — may be overvalued; wait for pullback"
        report.append(f"**{overall}**")

        if intrinsic and isinstance(intrinsic['margin_of_safety_pct'], str) and "%" in intrinsic['margin_of_safety_pct'] and not intrinsic['margin_of_safety_pct'].startswith("None"):
            report.append(f"\n*Consider building a long-term position in {self.symbol}. This is a hold-for-decades compounder scenario, NOT a swing trade.*")
        else:
            report.append(f"\n*{self.symbol} may be fundamentally sound but not attractively priced. Add to watchlist and wait for a market correction or pullback to initiate.*")

        report.append("\n---\n")
        report.append("> **DISCLAIMER:** This report is generated by Omaha-Bot, a Warren Buffett-style analysis simulation. It is NOT financial advice. Buffett's methodology requires deep human judgment about business quality, management integrity, and competitive dynamics that bots cannot replicate. Always conduct your own due diligence.")

        # Save
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"buffett_report_{self.symbol}.md")
        with open(output_path, "w") as f:
            f.write("\n".join(report))
        print(f"Buffett Report saved to: {output_path}")

        return "\n".join(report)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python buffett_analyzer.py <SYMBOL>")
        sys.exit(1)

    symbol = sys.argv[1]
    analyzer = BuffettAnalyzer(symbol)
    analyzer.generate_full_report()
