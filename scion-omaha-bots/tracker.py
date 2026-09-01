"""
Trade Logger & Performance Database

Tracks every entry + exit, snapshots open positions daily,
and persists to CSV for analysis by report_card.py and feedback.py.
"""
import csv
import os
import datetime
import json
import yfinance as yf
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reflection import ReflectionLog, log_reflection_on_exit

STATE_ROOT = os.environ.get(
    "STOCK_ANALYSIS_STATE_ROOT", os.path.dirname(os.path.abspath(__file__))
)
TRADES_FILE = os.path.join(STATE_ROOT, "trades.csv")
DAILY_PNL_FILE = os.path.join(STATE_ROOT, "daily_pnl.csv")
OPEN_POSITIONS_FILE = os.path.join(STATE_ROOT, "open_positions.json")

TRADES_HEADERS = [
    "ticker", "bot", "entry_date", "exit_date", "entry_price", "exit_price",
    "stop_loss", "target_1", "target_2", "score", "exit_reason",
    "pnl_pct", "days_held", "thesis", "sector",
    "entry_day_sign", "entry_trigger", "vol_ratio", "regime", "earnings_days", "fill_vs_close"
]

DAILY_HEADERS = [
    "date", "ticker", "bot", "current_price", "pnl_pct", "days_held",
    "distance_to_stop_pct", "distance_to_target1_pct", "score"
]


def _ensure_file(path, headers):
    if not os.path.exists(path):
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(headers)
        except Exception:
            pass


def _append_row(path, headers, row):
    _ensure_file(path, headers)
    try:
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(row)
    except Exception as e:
        print(f"  [tracker] Could not write: {e}")


def _read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _get_current_price(ticker):
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="2d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def _get_sector(ticker):
    try:
        info = yf.Ticker(ticker).info
        return info.get("sector", "Unknown")
    except Exception:
        return "Unknown"


def _get_day_range(ticker, date_str):
    """Return (low, high, close) for the trading day matching date_str, or None.

    Uses unadjusted prices so dividend adjustments never trip the check.
    Reuses the date-string match proven in diagnose_fills.py / check_unadjusted.py.
    """
    try:
        h = yf.Ticker(ticker).history(period="3mo", interval="1d", auto_adjust=False)
        if h is None or h.empty:
            return None
        h = h.reset_index()
        h["dstr"] = h["Date"].dt.strftime("%Y-%m-%d")
        day = h[h["dstr"] == date_str]
        if day.empty:
            return None
        return (
            float(day["Low"].iloc[0]),
            float(day["High"].iloc[0]),
            float(day["Close"].iloc[0]),
        )
    except Exception:
        return None


def _check_price_in_day_range(ticker, date_str, price, label):
    """Warn when a logged fill/exit price falls outside that day's OHLC range.

    Warning-only: after-hours fills legitimately sit outside the regular session
    range, so this flags for human verification instead of blocking the log.
    """
    rng = _get_day_range(ticker, date_str)
    if rng is None:
        print(f"  [tracker] range check skipped for {ticker} {date_str} (no bar found)")
        return None
    lo, hi, close = rng
    if lo <= price <= hi:
        print(f"  [tracker] range check OK: {ticker} {label} ${price:.2f} inside {date_str} {lo:.2f}..{hi:.2f}")
    else:
        print(
            f"  [tracker] WARN: {ticker} {label} ${price:.2f} is OUTSIDE {date_str} "
            f"range {lo:.2f}..{hi:.2f} (close {close:.2f}) - verify execution date/price"
        )
    return (lo, hi, close)


class Tracker:
    def __init__(self):
        self.trades_file = TRADES_FILE
        self.pnl_file = DAILY_PNL_FILE
        self.positions_file = OPEN_POSITIONS_FILE
        _ensure_file(self.trades_file, TRADES_HEADERS)
        _ensure_file(self.pnl_file, DAILY_HEADERS)

    def load_open_positions(self):
        if os.path.exists(self.positions_file):
            with open(self.positions_file, "r") as f:
                return json.load(f)
        return {}

    def save_open_positions(self, positions):
        os.makedirs(os.path.dirname(os.path.abspath(self.positions_file)), exist_ok=True)
        with open(self.positions_file, "w") as f:
            json.dump(positions, f, indent=2)

    def log_entry(self, ticker, bot="scion", entry_price=None, stop_loss=None,
                  target1=None, target2=None, score=0, thesis="", entry_date=None,
                  entry_day_sign=None, entry_trigger=None, vol_ratio=None,
                  regime=None, earnings_days=None, fill_vs_close=None):
        ticker = ticker.upper()
        positions = self.load_open_positions()
        if ticker in positions:
            print(f"  [tracker] {ticker} already open. Use log_exit first.")
            return

        if entry_date is None:
            entry_date = datetime.datetime.now().strftime("%Y-%m-%d")

        if entry_price is not None:
            rng = _check_price_in_day_range(ticker, entry_date, entry_price, "fill")
            if fill_vs_close is None and rng is not None:
                fill_vs_close = round((entry_price - rng[2]) / rng[2] * 100, 2)

        sector = _get_sector(ticker)

        positions[ticker] = {
            "ticker": ticker,
            "bot": bot,
            "entry_date": entry_date,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "target_1": target1,
            "target_2": target2,
            "score": score,
            "thesis": thesis,
            "sector": sector,
            "status": "OPEN",
            "entry_day_sign": entry_day_sign,
            "entry_trigger": entry_trigger,
            "vol_ratio": vol_ratio,
            "regime": regime,
            "earnings_days": earnings_days,
            "fill_vs_close": fill_vs_close,
        }
        self.save_open_positions(positions)
        print(f"  [tracker] LOGGED ENTRY: {ticker} @ ${entry_price} | Score: {score} | Bot: {bot}")

    def log_exit(self, ticker, exit_price=None, exit_reason="manual"):
        ticker = ticker.upper()
        positions = self.load_open_positions()
        if ticker not in positions:
            print(f"  [tracker] {ticker} not found in open positions.")
            return

        pos = positions.pop(ticker)
        self.save_open_positions(positions)

        entry = pos["entry_price"]
        if exit_price is None:
            exit_price = _get_current_price(ticker) or entry

        pnl_pct = round((exit_price - entry) / entry * 100, 2)
        try:
            entry_dt = datetime.datetime.strptime(pos["entry_date"], "%Y-%m-%d")
            days_held = (datetime.datetime.now() - entry_dt).days
        except Exception:
            days_held = 0

        exit_date = datetime.datetime.now().strftime("%Y-%m-%d")
        if exit_price is not None:
            _check_price_in_day_range(ticker, exit_date, exit_price, "exit")

        row = [
            ticker,
            pos.get("bot", ""),
            pos.get("entry_date", ""),
            exit_date,
            entry,
            exit_price,
            pos.get("stop_loss", ""),
            pos.get("target_1", ""),
            pos.get("target_2", ""),
            pos.get("score", 0),
            exit_reason,
            pnl_pct,
            days_held,
            pos.get("thesis", ""),
            pos.get("sector", ""),
            pos.get("entry_day_sign", ""),
            pos.get("entry_trigger", ""),
            pos.get("vol_ratio", ""),
            pos.get("regime", ""),
            pos.get("earnings_days", ""),
            pos.get("fill_vs_close", ""),
        ]
        _append_row(self.trades_file, TRADES_HEADERS, row)

        try:
            from report_card import compute_alpha_for_trade
            _, alpha = compute_alpha_for_trade(
                entry, exit_price,
                pos.get("entry_date", ""),
                datetime.datetime.now().strftime("%Y-%m-%d")
            )
            rl = ReflectionLog()
            rl.add_entry(
                ticker=ticker, bot=pos.get("bot", "scion"),
                entry_date=pos.get("entry_date", ""),
                exit_date=datetime.datetime.now().strftime("%Y-%m-%d"),
                entry_price=entry, exit_price=exit_price,
                pnl_pct=pnl_pct, exit_reason=exit_reason,
                thesis=pos.get("thesis", ""), alpha=alpha,
                sector=pos.get("sector", "Unknown"),
            )
        except Exception as e:
            print(f"  [tracker] Reflection log error: {e}")

        print(f"  [tracker] LOGGED EXIT: {ticker} @ ${exit_price} | PnL: {pnl_pct}% | Reason: {exit_reason}")

    def log_daily_snapshot(self, prices_dict=None):
        positions = self.load_open_positions()
        if not positions:
            print("  [tracker] No open positions to snapshot.")
            return

        today = datetime.datetime.now().strftime("%Y-%m-%d")
        count = 0
        for ticker, pos in positions.items():
            cp = prices_dict.get(ticker) if prices_dict else _get_current_price(ticker)
            if cp is None:
                continue

            entry = pos["entry_price"]
            pnl_pct = round((cp - entry) / entry * 100, 2)
            try:
                entry_dt = datetime.datetime.strptime(pos["entry_date"], "%Y-%m-%d")
                days_held = (datetime.datetime.now() - entry_dt).days
            except Exception:
                days_held = 0

            stop = pos.get("stop_loss")
            t1 = pos.get("target_1")
            dist_to_stop = round((cp - stop) / cp * 100, 2) if stop else ""
            dist_to_t1 = round((t1 - cp) / cp * 100, 2) if t1 else ""

            row = [
                today, ticker, pos.get("bot", ""),
                round(cp, 2), pnl_pct, days_held,
                dist_to_stop, dist_to_t1, pos.get("score", 0)
            ]
            _append_row(self.pnl_file, DAILY_HEADERS, row)
            count += 1

        print(f"  [tracker] Snapshot logged: {count} positions on {today}")

    def get_open_positions_summary(self):
        positions = self.load_open_positions()
        if not positions:
            return []

        results = []
        for ticker, pos in positions.items():
            cp = _get_current_price(ticker)
            if cp is None:
                continue
            entry = pos["entry_price"]
            pnl_pct = round((cp - entry) / entry * 100, 2)
            try:
                entry_dt = datetime.datetime.strptime(pos["entry_date"], "%Y-%m-%d")
                days_held = (datetime.datetime.now() - entry_dt).days
            except Exception:
                days_held = 0

            stop = pos.get("stop_loss")
            t1 = pos.get("target_1")
            t2 = pos.get("target_2")
            dist_to_stop = round((cp - stop) / cp * 100, 2) if stop else None
            dist_to_t1 = round((t1 - cp) / cp * 100, 2) if t1 else None

            results.append({
                "ticker": ticker,
                "bot": pos.get("bot", ""),
                "entry_price": entry,
                "current_price": round(cp, 2),
                "pnl_pct": pnl_pct,
                "days_held": days_held,
                "stop_loss": stop,
                "target_1": t1,
                "target_2": t2,
                "distance_to_stop_pct": dist_to_stop,
                "distance_to_target1_pct": dist_to_t1,
                "score": pos.get("score", 0),
                "sector": pos.get("sector", "Unknown"),
            })
        return results

    def get_closed_trades(self, bot=None, date_from=None, date_to=None):
        rows = _read_csv(self.trades_file)
        if not rows:
            return []

        if bot:
            rows = [r for r in rows if r.get("bot", "").lower() == bot.lower()]
        if date_from:
            rows = [r for r in rows if r.get("exit_date", "") >= date_from]
        if date_to:
            rows = [r for r in rows if r.get("exit_date", "") <= date_to]

        return rows

    def get_daily_pnl_history(self, ticker=None, days=30):
        rows = _read_csv(self.pnl_file)
        if not rows:
            return []

        if ticker:
            rows = [r for r in rows if r.get("ticker", "").upper() == ticker.upper()]

        cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        rows = [r for r in rows if r.get("date", "") >= cutoff]
        return rows


def backfill_current_positions():
    positions = [
        ("ZTS", "scion", "2026-07-08", 74.80, 71.86, 89.76, 104.72, 88, "Scion #1 pick, 54% off ATH, monopoly animal health, screwworm catalyst"),
        ("NVDA", "omaha", "2026-07-08", 196.05, 176.55, 235.26, 274.47, 0, "PEG 0.60, 85% rev growth, AI monopoly, chip sell-off entry"),
        ("GOOGL", "omaha", "2026-07-08", 361.42, 328.58, 433.70, 505.99, 68, "Omaha score 67.7, wide moat, 39% ROE, earnings Jul 23"),
        ("ADBE", "scion", "2026-07-08", 222.96, 193.41, 267.55, 312.14, 65, "Scion score 65, DCF 31% MoS, director bought $1.95M, 89% GM at 7.9x PE"),
        ("WFC", "omaha", "2026-07-08", 85.19, 79.66, 102.23, 119.27, 0, "10.9x fwd PE, yield curve tailwind, earnings Jul 14"),
        ("LNG", "omaha", "2026-07-08", 241.55, 232.35, 289.86, 338.17, 0, "13.1x fwd PE, 24% rev growth, Iran sanctions tailwind"),
        ("GD", "omaha", "2026-07-08", 371.26, 348.59, 445.51, 519.76, 25, "Defense surge, low beta 0.34, 1.7% yield, earnings Jul 29"),
        ("VRT", "scion", "2026-07-08", 330.28, 241.35, 396.34, 462.39, 15, "AI infra pick-and-shovel, 30% rev growth, earnings Jul 29"),
        ("APP", "omaha", "2026-07-08", 506.30, 407.00, 607.56, 708.82, 0, "59% rev growth, 88% GM, beta 2.48, earnings Aug 5"),
        ("AXON", "omaha", "2026-07-08", 552.92, 507.98, 663.50, 774.09, 0, "34% rev growth, law enforcement monopoly, earnings Aug 3"),
        ("BA", "scion", "2026-07-08", 238.52, 204.35, 286.22, 333.93, 5, "737 MAX ramp, defense tailwind, speculative turnaround, earnings Jul 28"),
        ("CBRS", "scion", "2026-07-08", 181.10, 168.52, 217.32, 253.54, 35, "AI chip IPO down 53% from ATH, 94% rev growth, 23.6% short interest"),
    ]

    tracker = Tracker()
    existing = tracker.load_open_positions()
    count = 0
    for ticker, bot, date, entry, stop, t1, t2, score, thesis in positions:
        if ticker not in existing:
            tracker.log_entry(
                ticker=ticker, bot=bot, entry_price=entry,
                stop_loss=stop, target1=t1, target2=t2,
                score=score, thesis=thesis, entry_date=date
            )
            count += 1
    print(f"\n  Backfill complete: {count} new positions added")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Trade Tracker")
    parser.add_argument("command", choices=["backfill", "snapshot", "status", "trades"])
    parser.add_argument("--ticker", type=str)
    parser.add_argument("--entry", type=float)
    parser.add_argument("--exit", type=float)
    parser.add_argument("--reason", type=str, default="manual")
    parser.add_argument("--stop", type=float)
    parser.add_argument("--t1", type=float)
    parser.add_argument("--t2", type=float)
    parser.add_argument("--score", type=int, default=0)
    parser.add_argument("--bot", type=str, default="scion")
    parser.add_argument("--thesis", type=str, default="")
    parser.add_argument("--date", type=str)

    args = parser.parse_args()
    t = Tracker()

    if args.command == "backfill":
        backfill_current_positions()
    elif args.command == "snapshot":
        t.log_daily_snapshot()
    elif args.command == "status":
        open_pos = t.get_open_positions_summary()
        if not open_pos:
            print("  No open positions.")
        else:
            print(f"\n  {'Ticker':<8} {'Bot':<8} {'Entry':>8} {'Current':>9} {'P&L%':>7} {'Days':>5} {'StopDist%':>10} {'T1Dist%':>9}")
            print("  " + "-" * 70)
            for p in open_pos:
                sd = f"{p['distance_to_stop_pct']:+.1f}%" if p['distance_to_stop_pct'] is not None else "N/A"
                td = f"{p['distance_to_target1_pct']:+.1f}%" if p['distance_to_target1_pct'] is not None else "N/A"
                print(f"  {p['ticker']:<8} {p['bot']:<8} ${p['entry_price']:<6.2f} ${p['current_price']:<7.2f} {p['pnl_pct']:+.2f}% {p['days_held']:>4}d {sd:>9} {td:>8}")
    elif args.command == "trades":
        closed = t.get_closed_trades()
        if not closed:
            print("  No closed trades yet.")
        else:
            print(f"\n  {'Ticker':<8} {'Bot':<8} {'Entry':>8} {'Exit':>8} {'P&L%':>7} {'Days':>5} {'Reason':<14}")
            print("  " + "-" * 60)
            for r in closed:
                print(f"  {r['ticker']:<8} {r['bot']:<8} ${r['entry_price']:<6.2f} ${r['exit_price']:<6.2f} {r['pnl_pct']:>6}% {r['days_held']:>4}d {r['exit_reason']:<14}")
