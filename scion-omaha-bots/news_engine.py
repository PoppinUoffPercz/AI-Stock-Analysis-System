"""
News Intake Engine for the Michael Burry Swing Trading Agent.

Continuously monitors a watchlist of tickers for news catalysts and
sentiment shifts. Designed to detect:
  1. Extreme Pessimism Capitulation (negative news barrage + price holds support)
  2. Reversal Catalysts (positive inflection in hated stocks)
  3. Stop-Loss Alert Triggers (breaking news that invalidates a thesis)

Integrates with the screener and analyzer modules.
"""
import datetime
import json
import os

import yfinance as yf
from news_utils import extract_news_fields

# Burry's "ick" and reversal keyword dictionaries
ICK_KEYWORDS = [
    "miss", "plunge", "downgrade", "crisis", "investigation", "sue", "lawsuit",
    "crash", "slashed", "drop", "decline", "debt", "bankruptcy", "probe", "hated",
    "worst", "layoff", "struggle", "bearish", "sell", "collapse", "fraud",
    "recall", "halt", "warning", "cut", "suspend", "default", "delisting"
]

REVERSAL_KEYWORDS = [
    "buyback", "insider", "purchase", "upgrade", "settles", "resolution", "contract",
    "approval", "acquire", "beat", "recovery", "stabilize", "rebound", "raise",
    "exceeds", "surge", "rally", "boost", "win", "launch", "expand", "partner",
    "merger", "deal", "dividend", "split", "short squeeze"
]

THESIS_BREAKING_KEYWORDS = [
    "delisting", "bankruptcy", "fraud", "investigation", "indictment", " SEC",
    "class action", "accounting irregularity", "going concern", "default"
]


class NewsEngine:
    """
    Continuously or on-demand monitors news for tickers in a watchlist.
    Can be called from the orchestrator to check for new catalysts on
    watchlist and portfolio positions.
    """

    def __init__(self, watchlist=None):
        self.watchlist = watchlist or []
        self.seen_titles = {}  # symbol -> set of seen titles (for dedup)
        state_root = os.environ.get("STOCK_ANALYSIS_STATE_ROOT", os.path.dirname(__file__))
        self._state_file = os.path.join(state_root, "news_state.json")
        self.load_seen_state()

    def load_seen_state(self):
        if os.path.exists(self._state_file):
            try:
                with open(self._state_file, "r") as f:
                    self.seen_titles = json.load(f)
                    # Convert lists back to sets
                    self.seen_titles = {k: set(v) for k, v in self.seen_titles.items()}
            except Exception:
                self.seen_titles = {}
        self.seen_titles = {k: v for k, v in self.seen_titles.items()}

    def save_seen_state(self):
        # Convert sets to lists for JSON serialization
        serializable = {k: list(v) for k, v in self.seen_titles.items()}
        os.makedirs(os.path.dirname(os.path.abspath(self._state_file)), exist_ok=True)
        with open(self._state_file, "w") as f:
            json.dump(serializable, f, indent=2)

    def add_to_watchlist(self, symbol):
        if symbol.upper() not in self.watchlist:
            self.watchlist.append(symbol.upper())

    def score_article(self, title):
        """Score a single news article title. Returns (score, classification)."""
        title_lower = title.lower()
        ick_hits = sum(1 for kw in ICK_KEYWORDS if kw in title_lower)
        reversal_hits = sum(1 for kw in REVERSAL_KEYWORDS if kw in title_lower)
        breaking_hits = sum(1 for kw in THESIS_BREAKING_KEYWORDS if kw in title_lower)

        total = ick_hits + reversal_hits
        if total == 0 and breaking_hits == 0:
            return 0.0, "NEUTRAL"

        if breaking_hits > 0:
            return -100.0, "THESIS_BREAKING"

        score = ((reversal_hits - ick_hits) / total) * 100.0

        if score < -50:
            classification = "EXTREME_PANIC"
        elif score < -20:
            classification = "ICK"
        elif score > 50:
            classification = "STRONG_REVERSAL"
        elif score > 20:
            classification = "REVERSAL"
        else:
            classification = "NEUTRAL"

        return score, classification

    def fetch_news(self, symbol):
        """Fetch and parse all news for a symbol."""
        try:
            t = yf.Ticker(symbol)
            raw_news = t.news or []
            parsed = extract_news_fields(raw_news, description=True)
            return parsed
        except Exception as e:
            print(f"[NewsEngine] Error fetching news for {symbol}: {e}")
            return []

    def get_new_news(self, symbol):
        """Get only news not previously seen for this symbol."""
        if symbol not in self.seen_titles:
            self.seen_titles[symbol] = set()

        all_news = self.fetch_news(symbol)
        new_items = []
        for item in all_news:
            title = item.get("title", "")
            if title and title not in self.seen_titles[symbol]:
                score, classification = self.score_article(title)
                new_items.append({
                    "title": title,
                    "publisher": item.get("publisher", ""),
                    "link": item.get("link", ""),
                    "pubDate": item.get("pubDate", ""),
                    "sentiment_score": score,
                    "sentiment_class": classification
                })
                self.seen_titles[symbol].add(title)

        self.save_seen_state()
        return new_items

    def scan_watchlist(self):
        """
        Scan all watchlist symbols for new news and return
        categorized alerts.
        Returns: {
            "extreme_panic": [...],    # High pessimism + price holding = buy signal
            "reversal_catalyst": [...],  # Positive catalyst in hated stock
            "thesis_breaking": [...],  # Should trigger immediate sell consideration
            "neutral": [...]
        }
        """
        results = {
            "extreme_panic": [],
            "reversal_catalyst": [],
            "thesis_breaking": [],
            "neutral": []
        }

        for symbol in self.watchlist:
            new_news = self.get_new_news(symbol)
            for item in new_news:
                entry = {
                    "symbol": symbol,
                    **item
                }
                cls = item["sentiment_class"]
                if cls == "THESIS_BREAKING":
                    results["thesis_breaking"].append(entry)
                elif cls == "EXTREME_PANIC":
                    results["extreme_panic"].append(entry)
                elif cls in ("STRONG_REVERSAL", "REVERSAL"):
                    results["reversal_catalyst"].append(entry)
                else:
                    results["neutral"].append(entry)

        return results

    def generate_alert_text(self, scan_results):
        """Generate a human-readable alert summary for WhatsApp notifications."""
        lines = []
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        has_alerts = any(v for v in scan_results.values())

        if not has_alerts:
            return None  # No new news worth reporting

        lines.append(f"*SCION NEWS ALERT* [{ts}]")
        lines.append("")

        if scan_results["thesis_breaking"]:
            lines.append("*⚠ THESIS-BREAKING NEWS (ACTION REQUIRED)*")
            for item in scan_results["thesis_breaking"]:
                lines.append(f"  [{item['symbol']}] {item['title']}")
                lines.append(f"    Source: {item['publisher']}")
                lines.append("    -> Consider immediate stop-loss review")
            lines.append("")

        if scan_results["extreme_panic"]:
            lines.append("*Extreme Panic Detected (Ick Buying Opportunity)*")
            for item in scan_results["extreme_panic"]:
                lines.append(f"  [{item['symbol']}] {item['title']}")
                lines.append(f"    Source: {item['publisher']}")
                lines.append("    -> If price holds support, this may be a capitulation buy")
            lines.append("")

        if scan_results["reversal_catalyst"]:
            lines.append("*Reversal Catalysts (Buy Trigger)*")
            for item in scan_results["reversal_catalyst"]:
                lines.append(f"  [{item['symbol']}] {item['title']}")
                lines.append(f"    Source: {item['publisher']}")
                lines.append("    -> Positive inflection in depressed stock")
            lines.append("")

        return "\n".join(lines)


if __name__ == "__main__":
    engine = NewsEngine(watchlist=["EL", "LULU", "PFE", "INTC", "CVS"])
    results = engine.scan_watchlist()
    alert_text = engine.generate_alert_text(results)
    
    if alert_text:
        print(alert_text)
    else:
        print("No new news alerts detected.")
