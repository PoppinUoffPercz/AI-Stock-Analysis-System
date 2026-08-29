"""
Earnings Calendar

Fetches upcoming earnings dates and consensus estimates for any list of tickers.
Uses yfinance's built-in calendar data (no lxml dependency needed).

Integrated into premarket briefings and deep-dive analysis.
"""
import datetime
import yfinance as yf


def get_upcoming_earnings(symbols, max_days=45):
    """
    Scan symbols for earnings dates within the next max_days.
    Returns list of dicts: {symbol, date, eps_avg, eps_high, eps_low,
                              rev_avg, is_this_week, days_away}
    """
    today = datetime.date.today()
    results = []

    for sym in symbols:
        try:
            t = yf.Ticker(sym)
            cal = t.calendar
            if not cal or "Earnings Date" not in cal:
                continue

            raw_dates = cal["Earnings Date"]
            if not raw_dates:
                continue

            earnings_date = raw_dates[0] if isinstance(raw_dates, list) else raw_dates
            if isinstance(earnings_date, datetime.datetime):
                earnings_date = earnings_date.date()

            delta = (earnings_date - today).days
            if delta < 0 or delta > max_days:
                continue

            results.append({
                "symbol": sym,
                "date": earnings_date,
                "eps_avg": cal.get("Earnings Average"),
                "eps_high": cal.get("Earnings High"),
                "eps_low": cal.get("Earnings Low"),
                "rev_avg": cal.get("Revenue Average"),
                "is_this_week": delta <= 7,
                "days_away": delta,
            })
        except Exception:
            continue

    results.sort(key=lambda r: r["days_away"])
    return results


def earnings_in_range(earnings_list, max_days=7):
    """Filter earnings list to those within max_days."""
    return [e for e in earnings_list if e["days_away"] <= max_days]


def format_earnings_brief(earnings_list):
    """Return a compact string for premarket / embed use."""
    if not earnings_list:
        return None

    lines = []
    near = earnings_in_range(earnings_list, 7)
    further = [e for e in earnings_list if e["days_away"] > 7]

    if near:
        lines.append("  THIS WEEK:")
        for e in near:
            eps = f" (est ${e['eps_avg']:.2f})" if e["eps_avg"] else ""
            lines.append(f"    {e['symbol']}: {e['date']}{eps}")
    if further:
        lines.append("  UPCOMING (next 45d):")
        for e in further[:8]:
            eps = f" (est ${e['eps_avg']:.2f})" if e["eps_avg"] else ""
            lines.append(f"    {e['symbol']}: {e['date']}{eps}")

    return "\n".join(lines)


def format_earnings_warning(earnings_list, portfolio_symbols=None):
    """
    Generate a warning if any portfolio holdings report within the window.
    Returns None or a short string.
    """
    if not earnings_list or not portfolio_symbols:
        return None

    portfolio_set = set(s.upper() for s in portfolio_symbols)
    conflicts = [e for e in earnings_list if e["symbol"] in portfolio_set and e["days_away"] <= 14]

    if not conflicts:
        return None

    lines = ["  WARNING — portfolio holdings reporting soon:"]
    for e in conflicts:
        d = e["days_away"]
        label = "TOMORROW" if d == 0 else f"in {d} days"
        lines.append(f"    {e['symbol']} reports {label}")
    return "\n".join(lines)


def get_earnings_analysis(symbol):
    """Return earnings data for a single ticker for deep-dive analysis."""
    try:
        t = yf.Ticker(symbol)
        cal = t.calendar
        if not cal:
            return None
        return {
            "next_date": cal.get("Earnings Date", [None])[0] if cal.get("Earnings Date") else None,
            "eps_avg": cal.get("Earnings Average"),
            "eps_high": cal.get("Earnings High"),
            "eps_low": cal.get("Earnings Low"),
            "rev_avg": cal.get("Revenue Average"),
        }
    except Exception:
        return None
