"""
Buffett News Engine — Moat-Violation & Competitive-Threat Monitor.

Designed for Omaha-Bot's long-horizon quality-compounder strategy.
Detects:
  1. Moat threats (competition, regulation, disruption)
  2. Management quality events (CEO departure, scandal, governance)
  3. Dividend safety issues (cuts, suspensions)
  4. Industry disruption (tech shifts, regulatory action)
  5. Thesis-breaking events (fraud, antitrust, delisting)
"""
import datetime
import json
import os

import yfinance as yf
from news_utils import extract_news_fields

# Buffett-relevant keyword categories
MOAT_THREAT_KEYWORDS = [
    "competition", "competitor", "market share", "disrupt", "substitute",
    "commoditization", "price war", "eroding", "entrant", "copycat",
    "generic", "open source", "margin compression", "losing share"
]

MANAGEMENT_KEYWORDS = [
    "CEO", "chief executive", "resign", "departure", "ousted", "fired",
    "board", "governance", "insider selling", "insider trading",
    "succession", "interim CEO", "executive", "chairman", "founder"
]

REGULATORY_KEYWORDS = [
    "antitrust", "regulation", "regulator", "DOJ", "FTC", "SEC",
    "investigation", "probe", "lawsuit", "class action", "fine",
    "penalty", "sanction", "break up", "monopoly", "divestiture"
]

DIVIDEND_KEYWORDS = [
    "dividend cut", "dividend suspended", "dividend reduced",
    "payout ratio", "dividend coverage", "dividend safety"
]

THESIS_BREAKING_KEYWORDS = [
    "delisting", "bankruptcy", "fraud", "indictment", "going concern",
    "accounting irregularity", "restatement", "default", "insolvency"
]

COMPETITIVE_STRENGTH_KEYWORDS = [
    "buyback", "dividend increase", "raise guidance", "record revenue",
    "market leader", "award", "patent", "exclusive", "partnership",
    "moat", "pricing power", "switching cost", "network effect",
    "brand", "loyalty", "recurring revenue", "subscription"
]


class BuffettNewsEngine:
    """
    Monitors a watchlist of quality compounders for events that
    threaten (or reinforce) their competitive moats.
    """

    def __init__(self, watchlist=None):
        self.watchlist = watchlist or []
        self.seen_titles = {}
        state_root = os.environ.get("STOCK_ANALYSIS_STATE_ROOT", os.path.dirname(__file__))
        self._state_file = os.path.join(state_root, "buffett_news_state.json")
        self.load_seen_state()

    def load_seen_state(self):
        if os.path.exists(self._state_file):
            try:
                with open(self._state_file, "r") as f:
                    self.seen_titles = json.load(f)
                self.seen_titles = {k: set(v) for k, v in self.seen_titles.items()}
            except Exception:
                self.seen_titles = {}
        self.seen_titles = {k: v for k, v in self.seen_titles.items()}

    def save_seen_state(self):
        serializable = {k: list(v) for k, v in self.seen_titles.items()}
        os.makedirs(os.path.dirname(os.path.abspath(self._state_file)), exist_ok=True)
        with open(self._state_file, "w") as f:
            json.dump(serializable, f, indent=2)

    def add_to_watchlist(self, symbol):
        if symbol.upper() not in self.watchlist:
            self.watchlist.append(symbol.upper())

    def score_article(self, title):
        """Score a single news article. Returns (severity, classification)."""
        title_lower = title.lower()
        moat_hits = sum(1 for kw in MOAT_THREAT_KEYWORDS if kw in title_lower)
        mgmt_hits = sum(1 for kw in MANAGEMENT_KEYWORDS if kw in title_lower)
        reg_hits = sum(1 for kw in REGULATORY_KEYWORDS if kw in title_lower)
        div_hits = sum(1 for kw in DIVIDEND_KEYWORDS if kw in title_lower)
        breaking_hits = sum(1 for kw in THESIS_BREAKING_KEYWORDS if kw in title_lower)
        strength_hits = sum(1 for kw in COMPETITIVE_STRENGTH_KEYWORDS if kw in title_lower)

        total_threats = moat_hits + mgmt_hits + reg_hits + div_hits + breaking_hits
        total = total_threats + strength_hits

        if total == 0:
            return 0.0, "NEUTRAL"

        if breaking_hits > 0:
            return -100.0, "THESIS_BREAKING"

        if moat_hits >= 2 or (moat_hits > 0 and reg_hits > 0):
            return -75.0, "MOAT_THREAT"

        if mgmt_hits >= 2:
            return -60.0, "MANAGEMENT_ALERT"

        if reg_hits > 0:
            return -50.0, "REGULATORY_RISK"

        if div_hits > 0:
            return -40.0, "DIVIDEND_ALERT"

        if strength_hits >= 2:
            return 50.0, "MOAT_REINFORCED"

        if strength_hits > 0:
            return 25.0, "POSITIVE"

        return -10.0, "LOW_THREAT"

    def fetch_news(self, symbol):
        try:
            t = yf.Ticker(symbol)
            raw_news = t.news or []
            parsed = extract_news_fields(raw_news, description=True)
            return parsed
        except Exception as e:
            print(f"[BuffettNewsEngine] Error fetching news for {symbol}: {e}")
            return []

    def get_new_news(self, symbol):
        if symbol not in self.seen_titles:
            self.seen_titles[symbol] = set()

        all_news = self.fetch_news(symbol)
        new_items = []
        for item in all_news:
            title = item.get("title", "")
            if title and title not in self.seen_titles[symbol]:
                severity, classification = self.score_article(title)
                new_items.append({
                    "title": title,
                    "publisher": item.get("publisher", ""),
                    "link": item.get("link", ""),
                    "pubDate": item.get("pubDate", ""),
                    "severity": severity,
                    "classification": classification
                })
                self.seen_titles[symbol].add(title)

        self.save_seen_state()
        return new_items

    def scan_watchlist(self):
        results = {
            "thesis_breaking": [],
            "moat_threat": [],
            "management_alert": [],
            "regulatory": [],
            "dividend_alert": [],
            "positive": [],
            "neutral": []
        }

        for symbol in self.watchlist:
            new_news = self.get_new_news(symbol)
            for item in new_news:
                entry = {"symbol": symbol, **item}
                cls = item["classification"]
                if cls == "THESIS_BREAKING":
                    results["thesis_breaking"].append(entry)
                elif cls == "MOAT_THREAT":
                    results["moat_threat"].append(entry)
                elif cls == "MANAGEMENT_ALERT":
                    results["management_alert"].append(entry)
                elif cls == "REGULATORY_RISK":
                    results["regulatory"].append(entry)
                elif cls == "DIVIDEND_ALERT":
                    results["dividend_alert"].append(entry)
                elif cls in ("MOAT_REINFORCED", "POSITIVE"):
                    results["positive"].append(entry)
                else:
                    results["neutral"].append(entry)

        return results

    def generate_alert_text(self, scan_results):
        lines = []
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        has_actionable = any(v for cat, v in scan_results.items() if cat != "neutral")

        if not has_actionable:
            return None

        lines.append(f"*OMAHA NEWS ALERT* [{ts}]")
        lines.append("")

        thesis_breaking = scan_results["thesis_breaking"]
        moat_threat = scan_results["moat_threat"]
        management = scan_results["management_alert"]
        regulatory = scan_results["regulatory"]
        dividend = scan_results["dividend_alert"]
        positive = scan_results["positive"]

        if thesis_breaking:
            lines.append("*THESIS BREAKING (REVIEW POSITION)*")
            for item in thesis_breaking:
                lines.append(f"  [{item['symbol']}] {item['title']}")
                lines.append(f"    Source: {item['publisher']}")
            lines.append("")

        if moat_threat:
            lines.append("*MOAT THREAT DETECTED*")
            for item in moat_threat:
                lines.append(f"  [{item['symbol']}] {item['title']}")
                lines.append(f"    Source: {item['publisher']}")
            lines.append("")

        if management:
            lines.append("*MANAGEMENT/COMPENSATION ALERT*")
            for item in management:
                lines.append(f"  [{item['symbol']}] {item['title']}")
                lines.append(f"    Source: {item['publisher']}")
            lines.append("")

        if regulatory:
            lines.append("*REGULATORY/LEGAL RISK*")
            for item in regulatory:
                lines.append(f"  [{item['symbol']}] {item['title']}")
                lines.append(f"    Source: {item['publisher']}")
            lines.append("")

        if dividend:
            lines.append("*DIVIDEND ALERT*")
            for item in dividend:
                lines.append(f"  [{item['symbol']}] {item['title']}")
                lines.append(f"    Source: {item['publisher']}")
            lines.append("")

        if positive:
            lines.append("*MOAT REINFORCEMENT / POSITIVE SIGNALS*")
            for item in positive:
                lines.append(f"  [{item['symbol']}] {item['title']}")
                lines.append(f"    Source: {item['publisher']}")
            lines.append("")

        return "\n".join(lines)


if __name__ == "__main__":
    engine = BuffettNewsEngine(watchlist=["KO", "PG", "JNJ", "MSFT", "AAPL"])
    results = engine.scan_watchlist()
    alert_text = engine.generate_alert_text(results)

    if alert_text:
        print(alert_text)
    else:
        print("No new significant news detected on moat factors.")
