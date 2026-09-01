"""
Decision Reflection Log

Mirrors TradingAgents' memory/reflection concept:
- Stores structured reflection entries for closed trades
- Re-injects recent reflections into screener context
- No LLM needed — reflections are auto-generated from trade data
"""
import json
import os
import datetime

STATE_ROOT = os.environ.get(
    "STOCK_ANALYSIS_STATE_ROOT", os.path.dirname(os.path.abspath(__file__))
)
REFLECTION_FILE = os.path.join(STATE_ROOT, "reflection_log.json")


class ReflectionLog:
    def __init__(self, path=REFLECTION_FILE):
        self.path = path

    def load(self):
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def save(self, entries):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)

    def add_entry(self, ticker, bot, entry_date, exit_date, entry_price, exit_price,
                  pnl_pct, exit_reason, thesis, alpha=None, sector=None):
        pnl_pct = float(pnl_pct)
        direction = "correct" if pnl_pct > 0 else ("incorrect" if pnl_pct < 0 else "breakeven")
        try:
            entry_dt = datetime.datetime.strptime(entry_date, "%Y-%m-%d") if entry_date else datetime.datetime.now()
            exit_dt = datetime.datetime.strptime(exit_date, "%Y-%m-%d") if exit_date else datetime.datetime.now()
            days_held = (exit_dt - entry_dt).days
        except Exception:
            days_held = 0

        lesson = self._generate_lesson(ticker, direction, pnl_pct, exit_reason, days_held, bot)

        entry = {
            "ticker": ticker,
            "bot": bot,
            "entry_date": entry_date,
            "exit_date": exit_date,
            "pnl_pct": round(pnl_pct, 2),
            "alpha": round(alpha, 2) if alpha is not None else None,
            "direction": direction,
            "thesis": thesis or "",
            "exit_reason": exit_reason,
            "days_held": days_held,
            "lesson": lesson,
            "sector": sector or "Unknown",
            "timestamp": datetime.datetime.now().isoformat(),
        }

        entries = self.load()
        entries.append(entry)
        # Keep last 100 entries
        if len(entries) > 100:
            entries = entries[-100:]
        self.save(entries)
        return entry

    def _generate_lesson(self, ticker, direction, pnl_pct, exit_reason, days_held, bot):
        lessons = []
        if direction == "correct":
            lessons.append(f"{ticker} was a {pnl_pct:+.1f}% winner over {days_held}d.")
            if "target" in exit_reason.lower():
                lessons.append("Exited on target — plan worked.")
            elif "stop" in exit_reason.lower():
                lessons.append("Exited on stop despite positive outcome — review exit timing.")
            else:
                lessons.append(f"Exited: {exit_reason}.")
        elif direction == "incorrect":
            lessons.append(f"{ticker} lost {pnl_pct:+.1f}% over {days_held}d.")
            if "stop" in exit_reason.lower():
                lessons.append("Stop-loss respected — discipline preserved capital.")
            else:
                lessons.append(f"Exited: {exit_reason}. Review thesis assumptions.")
            if days_held < 10:
                lessons.append("Short hold suggests entry timing was wrong or catalyst failed.")
        else:
            lessons.append(f"{ticker} was breakeven over {days_held}d.")
            lessons.append(f"Exited: {exit_reason}. No edge found.")

        lessons.append(f"Bot: {bot}.")
        return " ".join(lessons)

    def get_recent(self, limit=5, bot=None):
        entries = self.load()
        if bot:
            entries = [e for e in entries if e.get("bot", "").lower() == bot.lower()]
        return entries[-limit:] if entries else []

    def get_by_ticker(self, ticker, limit=3):
        entries = self.load()
        filtered = [e for e in entries if e.get("ticker", "").upper() == ticker.upper()]
        return filtered[-limit:]

    def format_for_screener(self, bot=None):
        recent = self.get_recent(limit=5, bot=bot)
        if not recent:
            return ""

        lines = ["\n--- Recent Closed-Trade Reflections ---"]
        for e in reversed(recent):
            pnl = f"{e['pnl_pct']:+.1f}%"
            alpha = f" (alpha {e['alpha']:+.1f}%)" if e.get("alpha") is not None else ""
            lines.append(f"  {e['ticker']}: {pnl}{alpha} | {e['lesson']}")
        lines.append("--- End Reflections ---\n")
        return "\n".join(lines)


def log_reflection_on_exit(ticker, exit_price, exit_reason, tracker):
    """Convenience: log a reflection using tracker's open position data."""
    positions = tracker.load_open_positions()
    closed_data = None
    if ticker.upper() not in positions:
        # Already removed — check if we can reconstruct from recent trades
        closed = tracker.get_closed_trades()
        for r in closed:
            if r.get("ticker", "").upper() == ticker.upper():
                closed_data = r
                break
    else:
        pos = positions[ticker.upper()]
        closed_data = pos

    if not closed_data:
        return None

    entry_price = float(closed_data.get("entry_price", 0))
    pnl_pct = round((exit_price - entry_price) / entry_price * 100, 2) if entry_price else 0

    from report_card import compute_alpha_for_trade
    _, alpha = compute_alpha_for_trade(
        entry_price, exit_price,
        closed_data.get("entry_date", ""),
        datetime.datetime.now().strftime("%Y-%m-%d")
    )

    rl = ReflectionLog()
    return rl.add_entry(
        ticker=ticker.upper(),
        bot=closed_data.get("bot", "scion"),
        entry_date=closed_data.get("entry_date", ""),
        exit_date=datetime.datetime.now().strftime("%Y-%m-%d"),
        entry_price=entry_price,
        exit_price=exit_price,
        pnl_pct=pnl_pct,
        exit_reason=exit_reason,
        thesis=closed_data.get("thesis", ""),
        alpha=alpha,
        sector=closed_data.get("sector", "Unknown"),
    )


if __name__ == "__main__":
    rl = ReflectionLog()
    print(f"Reflection log: {rl.path}")
    recent = rl.get_recent(limit=5)
    if recent:
        print("\nRecent reflections:")
        for e in recent:
            print(f"  {e['ticker']}: {e['pnl_pct']:+.1f}% ({e['direction']}) — {e['lesson']}")
    else:
        print("(No reflections yet)")

    print(rl.format_for_screener())
