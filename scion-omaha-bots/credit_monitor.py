"""
Credit Market Monitor

Tracks US credit market health using live Treasury yields, credit spreads
from bond ETFs, SOFR, and periodic private credit news scanning.

Produces a Composite Credit Stress Index (0-100) where higher = worse.

Output modes:
  python credit_monitor.py         Full report with details
  python credit_monitor.py --pulse Condensed snapshot for premarket briefings

Integrates into both Scion-Bot and Omaha-Bot premarket commands.
"""
import datetime
import json
import os
import re
import sys
import urllib.request
import yfinance as yf


# --- Bond ETF tickers ---
TREASURY_TICKERS = {
    "30Y": "^TYX",
    "10Y": "^TNX",
    "5Y": "^FVX",
    "13WK": "^IRX",
}

ETF_TICKERS = {
    "IEF": "7-10 Year Treasury",
    "LQD": "IG Corporate Bonds",
    "HYG": "High Yield Corporate Bonds",
    "SHY": "1-3 Year Treasury",
    "TLT": "20+ Year Treasury",
}

# --- Private credit news keywords ---
PIK_KEYWORDS = [
    "payment in kind", "PIK", "PIK note", "PIK toggle",
    "capitalized interest", "deferral", "interest capitalization",
]

DEFAULT_KEYWORDS = [
    "default", "non-accrual", "distressed", "restructuring",
    "bankruptcy", "Chapter 11", "insolvency",
]

BDC_KEYWORDS = [
    "BDC", "business development company", "maturity wall",
    "refinancing risk", "covenant light", "cov-lite",
    "private credit", "direct lending", "private lending",
]

WARNING_KEYWORDS = [
    "credit crunch", "liquidity crisis", "margin call",
    "forced selling", "contagion", "systemic risk",
    "credit event", "funding freeze",
]

ALL_PRIVATE_CREDIT_KW = PIK_KEYWORDS + DEFAULT_KEYWORDS + BDC_KEYWORDS + WARNING_KEYWORDS


def _html_to_sofr(text):
    """Parse current SOFR value from sofrrate.com HTML."""
    m = re.search(r'SOFR[^<]*?(\d+\.\d+)%', text, re.IGNORECASE)
    if m:
        return float(m.group(1))
    m = re.search(r'(\d+\.\d+)%\s*</div>\s*<div[^>]*>Latest', text, re.IGNORECASE)
    if m:
        return float(m.group(1))
    m = re.search(r'>(\d+\.\d+)%<', text)
    if m:
        return float(m.group(1))
    return None


def _get_openbb():
    """Lazily import OpenBB; returns None when unavailable. Import is slow (~seconds)."""
    try:
        from openbb import obb
        return obb
    except Exception:
        return None


def _fmt_val(val, style="float"):
    if val is None:
        return "N/A"
    try:
        v = float(val)
        if style == "pct":
            return f"{v:.2f}%"
        elif style == "pct1":
            return f"{v:.1f}%"
        elif style == "bp":
            return f"{v:.0f} bps"
        elif style == "bp1":
            return f"{v:.1f} bps"
        elif style == "float2":
            return f"{v:.2f}"
        elif style == "int":
            return str(int(v))
        else:
            return f"{v:.1f}"
    except (ValueError, TypeError):
        return str(val)


class CreditMonitor:
    """
    Tracks US credit market health and computes a Composite Credit Stress Index.

    The composite score is a weighted average of six sub-scores (each 0-100):
      25% - Yield curve slope (2s10s)
      20% - 30Y Treasury yield level
      20% - High yield credit spread
      15% - Investment grade credit spread
      10% - SOFR trajectory
      10% - Private credit news severity
    """

    def __init__(self, data_dir=None):
        self.data_dir = data_dir or os.path.dirname(os.path.abspath(__file__))
        self.state_file = os.path.join(self.data_dir, "credit_state.json")
        self.vault_base = os.path.expanduser(
            "~/OneDrive/Documents/Obsidian Vault/Stock Research/Credit Monitor"
        )

        self.yields = {}
        self.yield_history = {}
        self.spreads = {}
        self.spread_history = {}
        self.sofr = None
        self.private_credit_alerts = []
        self.state = self._load_state()

    # ── State persistence ──

    def _load_state(self):
        if not os.path.exists(self.state_file):
            return {"seen_news": {}, "spread_percentiles": {}}
        try:
            with open(self.state_file, "r") as f:
                return json.load(f)
        except Exception:
            return {"seen_news": {}, "spread_percentiles": {}}

    def _save_state(self):
        try:
            with open(self.state_file, "w") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            print(f"  (Could not save credit state: {e})")

    # ── Data fetchers ──

    def get_treasury_yields(self):
        """Fetch current Treasury yields from OpenBB, falling back to yfinance."""
        obb = _get_openbb()
        if obb is not None:
            try:
                return self._get_treasury_yields_openbb(obb)
            except Exception:
                pass
        results = {}
        history = {}
        for tenor, ticker in TREASURY_TICKERS.items():
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period="5d")
                if hist.empty:
                    continue
                close = float(hist["Close"].iloc[-1])
                change = None
                if len(hist) >= 2:
                    change = close - float(hist["Close"].iloc[-2])
                results[tenor] = {"value": close, "change": change}

                hist1y = t.history(period="1y")
                if not hist1y.empty:
                    vals = [float(x) for x in hist1y["Close"].dropna()]
                    history[tenor] = {
                        "high": max(vals),
                        "low": min(vals),
                        "avg": sum(vals) / len(vals),
                        "current": close,
                    }
            except Exception as e:
                results[tenor] = {"value": None, "change": None, "error": str(e)}

        shy_yield_pct = self._get_etf_yield("SHY")
        if shy_yield_pct is not None:
            results["2Y"] = {"value": shy_yield_pct, "change": None}

        self.yields = results
        self.yield_history = history
        return results

    def _get_treasury_yields_openbb(self, obb):
        """Treasury yields from OpenBB (fraction -> percent). Raises on failure."""
        df = obb.fixedincome.government.treasury_rates().to_df()
        if df is None or df.empty:
            raise ValueError("OpenBB treasury_rates empty")
        mapping = {
            "13WK": "month_3",
            "2Y": "year_2",
            "5Y": "year_5",
            "10Y": "year_10",
            "30Y": "year_30",
        }
        window = df.tail(252)
        results = {}
        history = {}
        for tenor, col in mapping.items():
            if col not in df.columns:
                continue
            series = df[col].dropna()
            if series.empty:
                continue
            close = float(series.iloc[-1]) * 100
            change = None
            if len(series) >= 2:
                change = (float(series.iloc[-1]) - float(series.iloc[-2])) * 100
            results[tenor] = {"value": close, "change": change}
            w = window[col].dropna()
            if not w.empty:
                history[tenor] = {
                    "high": float(w.max()) * 100,
                    "low": float(w.min()) * 100,
                    "avg": float(w.mean()) * 100,
                    "current": close,
                }
        if not results:
            raise ValueError("no OpenBB treasury columns mapped")
        self.yields = results
        self.yield_history = history
        return results

    def _get_etf_yield(self, ticker_str):
        """Get yield for a bond ETF, with fallback logic."""
        try:
            t = yf.Ticker(ticker_str)
            info = t.fast_info
            yld = info.get("yield")
            if yld is not None and yld > 0:
                return float(yld) * 100  # fast_info yield is decimal
            info_full = t.info
            yld2 = info_full.get("yield", info_full.get("ytm"))
            if yld2 is not None and yld2 > 0:
                if yld2 < 1:
                    return yld2 * 100
                return float(yld2)
            hist = t.history(period="6mo")
            if not hist.empty and "Dividends" in hist.columns:
                total_divs = hist["Dividends"].sum()
                avg_price = float(hist["Close"].mean())
                if avg_price > 0 and total_divs > 0:
                    return (total_divs / avg_price) * 100
        except Exception:
            pass
        return None

    def get_credit_spreads(self):
        """
        Calculate IG and HY credit spreads from bond ETFs.
        Spread = ETF YTM or distribution yield minus IEF (7-10Y Treasury) yield.
        """
        results = {}

        try:
            ief_yield = self._get_etf_yield("IEF")
            if ief_yield is None or ief_yield <= 0:
                ief_yield = self._get_etf_yield("IEF")  # retry once
            results["risk_free_yield"] = ief_yield

            for ticker in ["LQD", "HYG"]:
                etf_yield = self._get_etf_yield(ticker)
                if etf_yield is not None and ief_yield is not None and ief_yield > 0:
                    spread_bps = (etf_yield - ief_yield) * 100
                else:
                    spread_bps = None

                results[ticker] = {
                    "yield": etf_yield,
                    "spread_bps": spread_bps,
                    "history": None,
                }
        except Exception as e:
            results["error"] = str(e)

        self.spreads = results
        return results

    def get_sofr(self):
        """Fetch current SOFR rate from OpenBB, falling back to sofrrate.com."""
        obb = _get_openbb()
        if obb is not None:
            try:
                df = obb.fixedincome.rate.sofr().to_df()
                rate = float(df["rate"].dropna().iloc[-1]) * 100
                self.sofr = rate
                return rate
            except Exception:
                pass
        try:
            req = urllib.request.Request(
                "https://www.sofrrate.com/",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8")
            rate = _html_to_sofr(html)
            if rate is not None:
                self.sofr = rate
                return rate
        except Exception:
            pass
        self.sofr = None
        return None

    def scan_private_credit_news(self):
        """
        Scan for private credit / BDC related news by fetching financial
        news headlines and cross-referencing against known keywords.
        """
        alerts = []
        if "seen_news" not in self.state:
            self.state["seen_news"] = {}

        for ticker in ["KKR", "ARCC", "FSK", "BX", "OBDC", "MAIN"]:
            try:
                t = yf.Ticker(ticker)
                raw = t.news or []
                for item in raw[:15]:
                    content = item.get("content", item)
                    title = content.get("title", "")
                    if not title:
                        continue
                    if title in self.state["seen_news"]:
                        continue
                    title_lower = title.lower()
                    matches = [kw for kw in ALL_PRIVATE_CREDIT_KW if kw.lower() in title_lower]
                    if matches:
                        severity = "INFO"
                        if any(kw.lower() in title_lower for kw in WARNING_KEYWORDS + DEFAULT_KEYWORDS):
                            severity = "WARNING"
                        if any(kw.lower() in title_lower for kw in ["bankruptcy", "Chapter 11", "default on"]):
                            severity = "CRITICAL"
                        alerts.append({
                            "ticker": ticker,
                            "title": title,
                            "keywords_found": matches,
                            "severity": severity,
                        })
                    self.state["seen_news"][title] = True
            except Exception:
                continue

        self.private_credit_alerts = alerts
        if alerts:
            self._save_state()
        return alerts

    # ── Scoring functions (each returns 0-100, higher = more stress) ──

    def _score_yield_curve(self):
        """
        Score based on 2s10s slope.
        Deep inversion = bad. Bear steepening from deep inversion also bad.
        """
        y10 = self.yields.get("10Y", {}).get("value")
        y2 = self.yields.get("2Y", {}).get("value")
        if y10 is None or y2 is None:
            return 30

        slope = y10 - y2

        if slope < -0.75:
            return 90
        elif slope < -0.50:
            return 75
        elif slope < -0.25:
            return 55
        elif slope < 0:
            return 40
        elif slope < 0.50:
            return 20
        elif slope < 1.00:
            return 30
        else:
            return 45

    def _score_30y_level(self):
        """Score based on 30Y Treasury absolute level vs recent history."""
        val = self.yields.get("30Y", {}).get("value")
        hist = self.yield_history.get("30Y")

        if val is None:
            return 30

        if hist and hist.get("high", 0) > hist.get("low", 0):
            rng = hist["high"] - hist["low"]
            if rng > 0:
                pctile = (val - hist["low"]) / rng
                return min(100, pctile * 100)

        if val >= 5.5:
            return 100
        elif val >= 5.0:
            return 75
        elif val >= 4.5:
            return 50
        elif val >= 4.0:
            return 30
        elif val >= 3.5:
            return 15
        else:
            return 5

    def _score_hy_spread(self):
        """Score based on HY credit spread. Uses absolute levels primarily,
        blended with trailing percentile for momentum signal."""
        hy = self.spreads.get("HYG", {})
        spread = hy.get("spread_bps")
        hist = hy.get("history")

        if spread is None:
            return 30

        if spread >= 800:
            abs_score = 100
        elif spread >= 600:
            abs_score = 80
        elif spread >= 500:
            abs_score = 65
        elif spread >= 400:
            abs_score = 50
        elif spread >= 300:
            abs_score = 35
        elif spread >= 200:
            abs_score = 20
        else:
            abs_score = 10

        pctile_score = 50
        if hist and hist["high"] > hist["low"]:
            pctile = (spread - hist["low"]) / (hist["high"] - hist["low"]) * 100
            pctile_score = min(100, max(0, pctile))

        return int(abs_score * 0.7 + pctile_score * 0.3)

    def _score_ig_spread(self):
        """Score based on IG credit spread. Absolute level blended with percentile."""
        ig = self.spreads.get("LQD", {})
        spread = ig.get("spread_bps")
        hist = ig.get("history")

        if spread is None:
            return 30

        if spread >= 300:
            abs_score = 100
        elif spread >= 200:
            abs_score = 70
        elif spread >= 150:
            abs_score = 45
        elif spread >= 100:
            abs_score = 25
        elif spread >= 75:
            abs_score = 15
        else:
            abs_score = 8

        pctile_score = 50
        if hist and hist["high"] > hist["low"]:
            pctile = (spread - hist["low"]) / (hist["high"] - hist["low"]) * 100
            pctile_score = min(100, max(0, pctile))

        return int(abs_score * 0.7 + pctile_score * 0.3)

    def _score_sofr(self):
        """Score based on SOFR rate level."""
        if self.sofr is None:
            return 15

        if self.sofr >= 5.5:
            return 80
        elif self.sofr >= 5.0:
            return 60
        elif self.sofr >= 4.0:
            return 40
        elif self.sofr >= 3.0:
            return 20
        elif self.sofr >= 2.0:
            return 10
        else:
            return 5

    def _score_private_credit(self):
        """Score based on recent private credit news severity."""
        if not self.private_credit_alerts:
            return 5

        has_critical = any(a["severity"] == "CRITICAL" for a in self.private_credit_alerts)
        has_warning = any(a["severity"] == "WARNING" for a in self.private_credit_alerts)
        count = len(self.private_credit_alerts)

        if has_critical and count >= 5:
            return 95
        elif has_critical:
            return 80
        elif has_warning and count >= 5:
            return 70
        elif has_warning:
            return 55
        elif count >= 5:
            return 40
        elif count >= 2:
            return 25
        else:
            return 15

    # ── Composite score ──

    def calculate_composite_score(self):
        """Compute weighted composite credit stress index (0-100)."""
        components = [
            ("Yield Curve (2s10s)", self._score_yield_curve(), 0.25),
            ("30Y Treasury Level", self._score_30y_level(), 0.20),
            ("HY Credit Spread", self._score_hy_spread(), 0.20),
            ("IG Credit Spread", self._score_ig_spread(), 0.15),
            ("SOFR Level", self._score_sofr(), 0.10),
            ("Private Credit", self._score_private_credit(), 0.10),
        ]

        composite = sum(score * weight for _, score, weight in components)
        return round(composite, 1), components

    @staticmethod
    def _classify(score):
        if score < 20:
            return "Benign", "Low stress"
        elif score < 40:
            return "Elevated", "Caution warranted"
        elif score < 60:
            return "Stressed", "Reduce risk exposure"
        elif score < 80:
            return "Crisis", "Defensive posture"
        else:
            return "Systemic", "Capital preservation"

    # ── Report generation ──

    def fetch_all(self):
        """Run all data fetches."""
        self.get_treasury_yields()
        self.get_credit_spreads()
        self.get_sofr()
        self.scan_private_credit_news()

    def generate_report(self):
        """Generate a full credit market report string."""
        self.fetch_all()
        score, components = self.calculate_composite_score()
        label, advice = self._classify(score)

        lines = []
        lines.append("=" * 60)
        lines.append(f"  CREDIT MARKET MONITOR")
        lines.append(f"  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 60)
        lines.append("")

        lines.append(f"COMPOSITE CREDIT STRESS INDEX: {score:.1f}/100")
        lines.append(f"  Classification: {label}")
        lines.append(f"  Advice: {advice}")
        lines.append("")

        lines.append("-- Treasury Yields --")
        for tenor in ["13WK", "2Y", "5Y", "10Y", "30Y"]:
            d = self.yields.get(tenor, {})
            v = d.get("value")
            ch = d.get("change")
            if v is not None:
                ch_str = f" ({ch:+.2f}%)" if ch is not None else ""
                lines.append(f"  {tenor}: {v:.2f}%{ch_str}")
            else:
                lines.append(f"  {tenor}: N/A")
        lines.append("")

        y10 = self.yields.get("10Y", {}).get("value")
        y2 = self.yields.get("2Y", {}).get("value")
        if y10 is not None and y2 is not None:
            slope = y10 - y2
            lines.append(f"  2s10s Slope: {slope:+.2f}% {'INVERTED' if slope < 0 else 'Normal'}")
        lines.append("")

        lines.append("-- Credit Spreads --")
        rf = self.spreads.get("risk_free_yield")
        if rf:
            lines.append(f"  IEF (7-10Y Treasury) Yield: {rf:.2f}%")

        for ticker, display_name in [("LQD", "IG (LQD)"), ("HYG", "HY (HYG)")]:
            d = self.spreads.get(ticker, {})
            yld = d.get("yield")
            spd = d.get("spread_bps")
            if yld is not None:
                lines.append(f"  {display_name} Yield: {yld:.2f}%")
            if spd is not None:
                lines.append(f"  {display_name} Spread: {spd:.0f} bps")
        lines.append("")

        if self.sofr is not None:
            lines.append(f"-- SOFR: {self.sofr:.2f}% --")
        else:
            lines.append("-- SOFR: N/A --")
        lines.append("")

        lines.append("-- Component Scores --")
        for name, score, weight in components:
            bar = "#" * int(score // 5) + "." * (20 - int(score // 5))
            lines.append(f"  {name:25s} [{bar}] {score:.0f}/100 (wt: {weight:.0%})")
        lines.append("")

        if self.private_credit_alerts:
            lines.append("-- Private Credit Alerts --")
            for a in self.private_credit_alerts[:10]:
                tag = {"CRITICAL": "!!!", "WARNING": "!!", "INFO": "!"}
                lines.append(f"  [{tag.get(a['severity'],'?')}] [{a['ticker']}] {a['title']}")
            if len(self.private_credit_alerts) > 10:
                lines.append(f"  ... and {len(self.private_credit_alerts) - 10} more")
            lines.append("")

        lines.append(f"Risk Posture: {label} -- {advice}")
        lines.append("-" * 60)

        return "\n".join(lines), score, label

    def quick_pulse(self):
        """Generate a condensed credit snapshot for premarket briefings."""
        self.fetch_all()
        score, components = self.calculate_composite_score()
        label, advice = self._classify(score)

        y30 = self.yields.get("30Y", {}).get("value")
        y10 = self.yields.get("10Y", {}).get("value")
        y2 = self.yields.get("2Y", {}).get("value")
        hy_spd = self.spreads.get("HYG", {}).get("spread_bps")
        ig_spd = self.spreads.get("LQD", {}).get("spread_bps")
        hyield = self.spreads.get("HYG", {}).get("yield")
        igyield = self.spreads.get("LQD", {}).get("yield")

        slope_str = ""
        if y10 is not None and y2 is not None:
            slope = y10 - y2
            slope_str = f"{slope:+.2f}% {'(INV)' if slope < 0 else ''}"

        parts = [
            f"CREDIT STRESS: {score:.0f}/100 - {label} | {advice}",
        ]
        if y10 is not None:
            parts.append(f"10Y={y10:.2f}%")
        if y30 is not None:
            parts.append(f"30Y={y30:.2f}%")
        if slope_str:
            parts.append(f"2s10s={slope_str}")
        if hy_spd is not None:
            parts.append(f"HY={hy_spd:.0f}bps")
        if ig_spd is not None:
            parts.append(f"IG={ig_spd:.0f}bps")
        if self.sofr is not None:
            parts.append(f"SOFR={self.sofr:.2f}%")

        return " | ".join(parts), score, label, components

    def save_report_to_vault(self, report_text):
        """Save full report to Obsidian vault."""
        if not os.path.exists(self.vault_base):
            try:
                os.makedirs(self.vault_base)
            except Exception:
                return False
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        path = os.path.join(self.vault_base, f"{date_str} Credit Report.md")
        try:
            with open(path, "w") as f:
                f.write(report_text)
            return path
        except Exception:
            return None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Credit Market Monitor")
    parser.add_argument("--pulse", action="store_true", help="Condensed output for premarket")
    args = parser.parse_args()

    monitor = CreditMonitor()

    if args.pulse:
        pulse, score, label, _ = monitor.quick_pulse()
        print(pulse)
        return

    report, score, label = monitor.generate_report()
    print(report)

    saved = monitor.save_report_to_vault(report)
    if saved:
        print(f"\nReport saved to:\n{saved}")


if __name__ == "__main__":
    main()
