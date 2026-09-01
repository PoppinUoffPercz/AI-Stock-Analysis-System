"""
OMAHA-BOT: Warren Buffett Long-Horizon Quality Compounder Agent - Main Orchestrator

Ties together:
  1. Screener (buffett_screener.py) — finds wonderful businesses at fair prices
  2. Analyzer (buffett_analyzer.py) — deep-dive Four Filters + Owner Earnings DCF
  3. Portfolio Manager (buffett_portfolio.py) — long-term position tracker
  4. Notifier (notify.py) — sends WhatsApp alerts via zappy-mcp

Usage:
  python buffett_main.py screener            # Screen for quality compounders
  python buffett_main.py analyze KO          # Deep-dive a specific ticker
  python buffett_main.py portfolio            # Show portfolio summary
  python buffett_main.py check               # Review all positions (intrinsic value check)
  python buffett_main.py add KO              # Manually add a position
  python buffett_main.py trim KO --pct 25    # Trim an overweight position
  python buffett_main.py close KO            # Close a position (thesis break)
  python buffett_main.py run                 # Full automated review cycle
"""

import argparse
import datetime
import os
import sys
from collections.abc import Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULT_WATCHLIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "BRK-B", "JPM", "V", "MA",
    "JNJ", "PG", "KO", "PEP", "WMT", "COST", "MCD", "DIS", "BAC",
    "AXP", "UNH", "ABBV", "LLY", "HD", "NKE", "TXN", "CSCO",
    "NEE", "DHR", "BMY", "PFE", "MRK", "T", "VZ", "UPS", "CAT"
]


def cmd_screener(args):
    """Run the Buffett quality compounder screener."""
    from buffett_screener import BuffettScreener
    from notify import ScionNotifier

    watchlist = args.watchlist.split(",") if args.watchlist else None
    if watchlist:
        watchlist = [t.strip().upper() for t in watchlist]

    print(f"\n{'=' * 60}")
    print("  OMAHA-BOT SCREENER — Quality Compounder Scan")
    print(f"{'=' * 60}\n")

    screener = BuffettScreener(tickers=watchlist)
    results = screener.run_screener()

    if results.empty:
        print("\nNo quality compounders met the 40-point Buffett threshold today.")
        return

    print(f"\n{'=' * 60}")
    print(f"  {len(results)} QUALITY COMPOUNDERS FOUND (Score >= 40)")
    print(f"{'=' * 60}\n")

    pd = __import__("pandas")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 1200)
    display_cols = ["Symbol", "Price", "ROE", "Gross Margin", "D/E", "FCF Yield", "P/E", "PEG", "Buffett Score"]
    print(results[display_cols].to_string(index=False))
    print(f"\nFull report saved to: buffett_screener_output.md")

    if args.notify:
        notifier = ScionNotifier(recipient_id=args.recipient)
        top3 = results.head(3)
        lines = [f"OMAHA-BOT SCREENER ({len(results)} quality compounders found)"]
        for _, row in top3.iterrows():
            lines.append(f"  [{row['Symbol']}] Score:{row['Buffett Score']} | ${row['Price']} | ROE:{row['ROE']} | P/E:{row['P/E']}")
        notifier.send_alert("OMAHA-BOT SCREENER RESULTS", "\n".join(lines))

    top = results.iloc[0]
    print(f"\n>>> TOP QUALITY COMPOUNDER: {top['Symbol']} (Score: {top['Buffett Score']})")
    print(f">>> Run deep-dive: python buffett_main.py analyze {top['Symbol']}")


def cmd_analyze(args):
    """Run the Four Filters deep-dive analysis."""
    from buffett_analyzer import BuffettAnalyzer
    from notify import ScionNotifier

    analyzer = BuffettAnalyzer(args.symbol)
    report = analyzer.generate_full_report()

    if args.notify:
        notifier = ScionNotifier(recipient_id=args.recipient)
        notifier.send_alert(
            f"OMAHA-BOT ANALYSIS: {args.symbol}",
            f"Buffett Four Filters report saved to buffett_report_{args.symbol}.md"
        )


def cmd_portfolio(args):
    """Display portfolio summary."""
    from buffett_portfolio import BuffettPortfolioManager
    from notify import ScionNotifier

    pm = BuffettPortfolioManager()
    summary = pm.get_portfolio_summary()
    print(summary)

    if args.notify:
        notifier = ScionNotifier(recipient_id=args.recipient)
        notifier.send_alert("OMAHA-BOT PORTFOLIO UPDATE", summary)


def cmd_check(args):
    """Review all positions — intrinsic value checks, no stop-losses."""
    from buffett_portfolio import BuffettPortfolioManager
    from notify import ScionNotifier

    pm = BuffettPortfolioManager()
    print("\n[Portfolio] Reviewing all holdings (Buffett-style)...")
    actions = pm.check_all_positions()

    if not actions:
        print("No warnings. All positions within normal parameters.")
        print("(Buffett says: 'Our favorite holding period is forever.')")
        return

    print(f"\n{len(actions)} action(s) flagged:\n")
    for a in actions:
        if a["action"] == "WARNING":
            print(f"  [OVERVAULATION WARNING] {a['symbol']}:")
            print(f"    Current:   ${a['current_price']}")
            print(f"    Intrinsic: ${a['intrinsic_value']}")
            print(f"    Premium:   {a['premium_pct']}% above intrinsic value")
            print(f"    Message:   {a['message']}")
        else:
            print(f"  [{a['action']}] {a.get('symbol', '')}: {a.get('message', '')}")
        print()

    if args.notify:
        notifier = ScionNotifier(recipient_id=args.recipient)
        alert_lines = [f"{a['symbol']}: {a['message']}" for a in actions]
        notifier.send_alert("OMAHA-BOT POSITION WARNING", "\n".join(alert_lines))


def cmd_add(args):
    """Manually add a long-term compounder position."""
    from buffett_portfolio import BuffettPortfolioManager
    from notify import ScionNotifier

    pm = BuffettPortfolioManager()

    import yfinance as yf
    t = yf.Ticker(args.symbol)
    hist = t.history(period="6mo")
    if hist.empty:
        print(f"Could not fetch data for {args.symbol}")
        return

    info = t.info
    entry = float(hist["Close"].iloc[-1])

    # Quick intrinsic estimate
    fcf = info.get("freeCashflow")
    shares = info.get("sharesOutstanding")
    intrinsic = None
    margin = None
    if fcf and shares and fcf > 0:
        oe_per_share = fcf / shares
        growth = 0.08
        discount = 0.10
        terminal = 0.03
        projected = []
        temp = fcf
        for year in range(1, 11):
            temp *= (1 + growth)
            projected.append(temp)
        pv = [oe / ((1 + discount) ** year) for year, oe in zip(range(1, 11), projected)]
        total_debt = info.get("totalDebt") or 0
        total_cash = info.get("totalCash") or 0
        intrinsic_equity = sum(pv) + (projected[-1] * (1 + terminal) / (discount - terminal)) / ((1 + discount) ** 10) + total_cash - total_debt
        intrinsic = round(intrinsic_equity / shares, 2)
        margin = round((intrinsic - entry) / intrinsic * 100, 1)

    result = pm.open_position(
        symbol=args.symbol.upper(),
        entry_price=entry,
        intrinsic_value=intrinsic,
        buffett_score=args.score if args.score else 0,
        reasons=args.reasons if args.reasons else f"Manual entry at ${entry}" + (f" — Margin of Safety: {margin}%" if margin else "")
    )
    print(f"\nPosition opened: {result}")
    if intrinsic:
        print(f"Estimated intrinsic value: ${intrinsic} | Margin of Safety: {margin}%")
    print(f"\n{pm.get_portfolio_summary()}")

    if args.notify:
        notifier = ScionNotifier(recipient_id=args.recipient)
        body = f"Bought {result['shares']} shares of {args.symbol} @ ${entry}"
        if intrinsic:
            body += f"\nIntrinsic: ${intrinsic} | MoS: {margin}%"
        notifier.send_alert("OMAHA-BOT POSITION OPENED", body)


def cmd_trim(args):
    """Trim an overweight position (rebalance, not exit)."""
    from buffett_portfolio import BuffettPortfolioManager
    from notify import ScionNotifier

    pm = BuffettPortfolioManager()
    if args.symbol not in pm.positions:
        print(f"{args.symbol} is not in the portfolio.")
        return

    price = pm.get_current_price(args.symbol)
    if not price:
        print(f"Could not get current price for {args.symbol}")
        return

    result = pm.trim_position(args.symbol, price, pct_to_sell=args.pct / 100.0,
                               reason=args.reason or "Portfolio rebalancing")
    print(f"\nPosition trimmed: {result}")
    print(f"\n{pm.get_portfolio_summary()}")

    if args.notify:
        notifier = ScionNotifier(recipient_id=args.recipient)
        notifier.send_alert("OMAHA-BOT POSITION TRIMMED",
                            f"Trimmed {result['shares_sold']} shares of {args.symbol} @ ${price}")


def cmd_close(args):
    """Close a position (thesis break or strategic exit)."""
    from buffett_portfolio import BuffettPortfolioManager
    from notify import ScionNotifier

    pm = BuffettPortfolioManager()
    if args.symbol not in pm.positions:
        print(f"{args.symbol} is not in the portfolio.")
        return

    price = pm.get_current_price(args.symbol)
    if not price:
        print(f"Could not get current price. Using last known entry.")
        price = pm.positions[args.symbol]["entry_price"]

    reason = args.reason or "Thesis review — exit requested"
    result = pm.close_position(args.symbol, price, reason=reason)
    print(f"\nPosition closed: {result}")
    print(f"\n{pm.get_portfolio_summary()}")

    if args.notify:
        notifier = ScionNotifier(recipient_id=args.recipient)
        notifier.send_alert("OMAHA-BOT POSITION CLOSED",
                            f"Closed {args.symbol}: {result['realized_pnl']} ({result['realized_pct']})\nReason: {reason}")


def cmd_news(args):
    """Scan the Buffett watchlist for moat-threatening news."""
    from buffett_news_engine import BuffettNewsEngine
    from notify import ScionNotifier

    watchlist = args.watchlist.split(",") if args.watchlist else DEFAULT_WATCHLIST
    watchlist = [t.strip().upper() for t in watchlist]

    print("\n[BuffettNewsEngine] Scanning quality compounders for moat threats...")
    engine = BuffettNewsEngine(watchlist=watchlist)
    results = engine.scan_watchlist()
    alert_text = engine.generate_alert_text(results)

    if alert_text:
        print("\n" + alert_text)
        if args.notify:
            notifier = ScionNotifier(recipient_id=args.recipient)
            notifier.send_alert("OMAHA-BOT MOAT ALERT", alert_text)
    else:
        print("\nNo new significant moat-related news detected.")


def cmd_log_entry(args):
    from tracker import Tracker
    t = Tracker()
    t.log_entry(ticker=args.symbol, bot="omaha", entry_price=args.entry,
                 stop_loss=args.stop, target1=args.t1, target2=args.t2,
                 score=args.score, thesis=args.thesis)


def cmd_log_exit(args):
    from tracker import Tracker
    t = Tracker()
    t.log_exit(ticker=args.symbol, exit_price=args.exit, exit_reason=args.reason)


def cmd_report(args):
    from report_card import cmd_report as rc
    rc(bot=args.bot)


def cmd_feedback(args):
    from feedback import cmd_feedback as fb
    fb(interactive=not args.no_interactive)


def cmd_daily_check(args):
    from daily_check import cmd_check as dc
    dc()


def cmd_tracker(args):
    from tracker import Tracker
    t = Tracker()
    open_pos = t.get_open_positions_summary()
    if not open_pos:
        print("  No open positions.")
        return
    print(f"\n  {'Ticker':<8} {'Bot':<8} {'Entry':>8} {'Current':>9} {'P&L%':>7} {'Days':>5} {'StopDist%':>10} {'T1Dist%':>9} {'Score':>5}")
    print("  " + "-" * 75)
    for p in open_pos:
        sd = f"{p['distance_to_stop_pct']:+.1f}%" if p['distance_to_stop_pct'] is not None else "N/A"
        td = f"{p['distance_to_target1_pct']:+.1f}%" if p['distance_to_target1_pct'] is not None else "N/A"
        print(f"  {p['ticker']:<8} {p['bot']:<8} ${p['entry_price']:<6.2f} ${p['current_price']:<7.2f} {p['pnl_pct']:+.2f}% {p['days_held']:>4}d {sd:>9} {td:>8} {p['score']:>5}")


def _fmt_val(val, style="float"):
    """Format a value safely, handling None/NaN/string."""
    if val is None:
        return "N/A"
    try:
        v = float(val)
        if style == "dollar":
            return f"${v:.2f}"
        elif style == "pct":
            return f"{v:.1f}%"
        elif style == "int":
            return str(int(v))
        elif style == "float2":
            return f"{v:.2f}"
        else:
            return f"{v:.1f}"
    except (ValueError, TypeError):
        return str(val)


def cmd_premarket(args):
    """Generate a pre-market briefing and watchlist for today's open."""
    from buffett_news_engine import BuffettNewsEngine
    from buffett_screener import BuffettScreener
    from earnings import format_earnings_brief, get_upcoming_earnings

    print("\n" + "=" * 60)
    print("  OMAHA-BOT: PRE-MARKET BRIEFING")
    print(f"  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    import yfinance as yf

    market = {}
    print("\n--- Market Context ---")
    try:
        spy = yf.Ticker("SPY")
        spy_hist = spy.history(period="5d")
        if not spy_hist.empty:
            market["spy_close"] = round(float(spy_hist["Close"].iloc[-1]), 2)
            spy_change = (spy_hist["Close"].iloc[-1] - spy_hist["Close"].iloc[-2]) / spy_hist["Close"].iloc[-2] * 100
            spy_52w_high = spy_hist["Close"].max()
            print(f"  SPY: ${market['spy_close']:.2f} ({spy_change:+.2f}%) | 52W High: ${spy_52w_high:.2f}")

        vix = yf.Ticker("^VIX")
        vix_hist = vix.history(period="5d")
        if not vix_hist.empty:
            market["vix_close"] = round(float(vix_hist["Close"].iloc[-1]), 2)
            market["vix_regime"] = "HIGH (caution)" if market["vix_close"] > 20 else "LOW (risk-on)" if market["vix_close"] < 15 else "NORMAL"
            print(f"  VIX: {market['vix_close']:.2f} — {market['vix_regime']}")

        qqq = yf.Ticker("QQQ")
        qqq_hist = qqq.history(period="5d")
        if not qqq_hist.empty:
            market["qqq_close"] = round(float(qqq_hist["Close"].iloc[-1]), 2)
            print(f"  QQQ: ${market['qqq_close']:.2f}")
    except Exception as e:
        print(f"  (Could not fetch market data: {e})")

    try:
        from credit_monitor import CreditMonitor
        credit_pulse, credit_score, credit_label, _ = CreditMonitor().quick_pulse()
        print(f"\n--- Credit Stress: {credit_score:.0f}/100 ({credit_label}) ---")
        print(f"  {credit_pulse}")
    except Exception:
        pass

    print("\n--- Overnight Watchlist Scan ---")
    engine = BuffettNewsEngine(watchlist=DEFAULT_WATCHLIST)
    results = engine.scan_watchlist()
    alert_text = engine.generate_alert_text(results)
    if alert_text:
        significant = [l for l in alert_text.split("\n") if l.startswith("  [")]
        if significant:
            print("  Overnight news on quality compounders:")
            for line in significant:
                print(f"    {line}")
        else:
            print("  No significant overnight moat-related news.")
    else:
        print("  No significant overnight moat-related news.")

    try:
        earnings_list = get_upcoming_earnings(DEFAULT_WATCHLIST)
        brief = format_earnings_brief(earnings_list)
        if brief:
            print("\n--- Upcoming Earnings ---")
            print(brief)
    except Exception:
        pass

    try:
        from ta_lib import compute_all as compute_ta
        print("\n--- Technical Pulse ---")
        for t in DEFAULT_WATCHLIST[:6]:
            try:
                h = yf.Ticker(t).history(period="6mo")
                if not h.empty and len(h) >= 50:
                    ta = compute_ta(h)
                    rsi_str = f"RSI {ta['rsi']['value']:.0f} ({ta['rsi']['regime']})"
                    macd_str = f"MACD {ta['macd']['cross_signal'] or 'neutral'}"
                    sqz_str = "Squeeze ON" if ta['squeeze']['squeeze_on'] else "Squeeze OFF"
                    print(f"  {t:6s}:  {rsi_str:22s} | {macd_str:16s} | {sqz_str}")
            except Exception:
                print(f"  {t:6s}:  N/A")
    except Exception:
        pass

    try:
        from smart_money import get_smart_money_summary
        print("\n--- Smart Money Pulse ---")
        for t in DEFAULT_WATCHLIST[:4]:
            try:
                print(f"  {t:6s}:  {get_smart_money_summary(t)}")
            except Exception:
                print(f"  {t:6s}:  N/A")
    except Exception:
        pass

    print("\n--- Screener Pulse (Top Candidates Now) ---")
    screener = BuffettScreener()
    results = screener.run_screener()
    if not results.empty:
        top5 = results.head(5)
        pd = __import__("pandas")
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 1200)
        display_cols = ["Symbol", "Price", "ROE", "Gross Margin", "FCF Yield", "P/E", "PEG", "Buffett Score"]
        print(top5[display_cols].to_string(index=False))
        print(f"\n  Full screener: python buffett_main.py screener")
    else:
        print("  No quality compounders above 40-point threshold.")

    print("\n--- Pre-Market Action Plan ---")
    print("  [1] Run screener:  python buffett_main.py screener")
    print("  [2] Run full cycle: python buffett_main.py run")
    print("  [3] Check portfolio: python buffett_main.py portfolio")
    print("  [4] Combined view:  python buffett_main.py combined")
    print()

    report_path = os.path.join(os.path.dirname(__file__), "..",
        "OneDrive", "Documents", "Obsidian Vault", "Stock Research", "Stock Analysis",
        f"{datetime.datetime.now().strftime('%Y-%m-%d')} Pre-Market Brief.md")
    report_path = os.path.abspath(report_path)
    try:
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        lines = [
            f"---",
            f"title: \"Pre-Market Brief — {datetime.datetime.now().strftime('%Y-%m-%d')}\"",
            f"date: {datetime.datetime.now().strftime('%Y-%m-%d')}",
            f"tags:",
            f"  - premarket",
            f"  - daily-brief",
            f"---",
            f"",
            f"# Pre-Market Brief — {datetime.datetime.now().strftime('%Y-%m-%d')}",
            f"",
            f"*Auto-generated by Omaha-Bot*",
            f"",
        ]
        with open(report_path, "w") as f:
            f.write("\n".join(lines))

        with open(report_path, "a") as f:
            sc = market.get("spy_close")
            vc = market.get("vix_close")
            vr = market.get("vix_regime", "N/A")
            spy_str = f"\n**SPY:** ${sc:.2f}" if sc is not None else "\n**SPY:** N/A"
            f.write(spy_str)
            if vc is not None:
                f.write(f" | **VIX:** {vc:.2f} ({vr})")
            f.write(f" | **Date:** {datetime.datetime.now().strftime('%Y-%m-%d')}\n\n")
            try:
                from credit_monitor import CreditMonitor
                cp, cs, cl, _ = CreditMonitor().quick_pulse()
                f.write(f"**Credit Stress:** {cs:.0f}/100 ({cl})  \n")
                f.write(f"{cp}\n\n")
            except Exception:
                pass
            if not results.empty:
                fmt = _fmt_val
                f.write("## Top Screener Candidates\n\n")
                f.write("| Symbol | Price | ROE | Gross Margin | FCF Yield | P/E | PEG | Score |\n")
                f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
                for _, row in top5.iterrows():
                    p = fmt(row.get("Price"), "dollar")
                    roe = fmt(row.get("ROE"), "pct")
                    gm = fmt(row.get("Gross Margin"), "pct")
                    fy = fmt(row.get("FCF Yield"), "pct")
                    pe = fmt(row.get("P/E"), "float")
                    peg = fmt(row.get("PEG"), "float2")
                    sc2 = fmt(row.get("Buffett Score"), "int")
                    f.write(f"| {row['Symbol']} | {p} | {roe} | {gm} | {fy} | {pe}x | {peg}x | {sc2} |\n")
            f.write(f"\n---\n*Briefing generated at {datetime.datetime.now().strftime('%H:%M')}*")

        print(f"  Pre-market brief saved to:\n  {report_path}")
    except Exception as e:
        print(f"  (Could not save report file: {e})")


def cmd_combined(args):
    """Show combined portfolio view (Omaha-Bot + Scion-Bot)."""
    import json

    from buffett_portfolio import BuffettPortfolioManager
    from notify import ScionNotifier

    print("\n" + "=" * 60)
    print("  COMBINED DUAL-AGENT PORTFOLIO VIEW")
    print("=" * 60)

    omaha_file = os.path.join(os.path.dirname(__file__), "buffett_portfolio.json")
    scion_file = os.path.join(os.path.dirname(__file__), "portfolio.json")

    omaha_positions = {}
    scion_positions = {}
    omaha_capital = 100000.0
    omaha_cash = 100000.0
    scion_capital = 100000.0
    scion_cash = 100000.0

    if os.path.exists(omaha_file):
        try:
            with open(omaha_file, "r") as f:
                data = json.load(f)
            omaha_positions = data.get("positions", {})
            omaha_capital = data.get("capital", omaha_capital)
            omaha_cash = data.get("cash", omaha_cash)
        except Exception:
            pass

    if os.path.exists(scion_file):
        try:
            with open(scion_file, "r") as f:
                data = json.load(f)
            scion_positions = data.get("positions", {})
            scion_capital = data.get("capital", scion_capital)
            scion_cash = data.get("cash", scion_cash)
        except Exception:
            pass

    total_capital = omaha_capital + scion_capital
    total_cash = omaha_cash + scion_cash

    print(f"\n  {'Agent':<20} {'Capital':>12} {'Cash':>12} {'Positions':>10}")
    print(f"  {'-'*54}")
    print(f"  {'Omaha-Bot (Buffett)':<20} ${omaha_capital:>8,.0f} ${omaha_cash:>8,.0f} {len(omaha_positions):>4}")
    print(f"  {'Scion-Bot (Burry)':<20} ${scion_capital:>8,.0f} ${scion_cash:>8,.0f} {len(scion_positions):>4}")
    print(f"  {'TOTAL':<20} ${total_capital:>8,.0f} ${total_cash:>8,.0f} {len(omaha_positions) + len(scion_positions):>4}")

    omaha_alloc = (total_capital - total_cash) / total_capital * 100 if omaha_positions else 0
    scion_alloc = total_capital * 100 if scion_positions else 0
    cash_pct = total_cash / total_capital * 100

    invested = total_capital - total_cash
    omaha_invested = omaha_capital - omaha_cash
    scion_invested = scion_capital - scion_cash
    omaha_pct = omaha_invested / total_capital * 100 if total_capital > 0 else 0
    scion_pct = scion_invested / total_capital * 100 if total_capital > 0 else 0

    print(f"\n  Allocation:")
    print(f"    Omaha-Bot (hold forever):   {omaha_pct:5.1f}%")
    print(f"    Scion-Bot (tactical swings): {scion_pct:5.1f}%")
    print(f"    Cash (strategic reserve):    {cash_pct:5.1f}%")

    if omaha_positions:
        print(f"\n  Omaha-Bot Holdings:")
        pm = BuffettPortfolioManager()
        for sym, pos in sorted(omaha_positions.items()):
            cp = pm.get_current_price(sym)
            if cp:
                pnl = (cp - pos["entry_price"]) / pos["entry_price"] * 100
                val = pos["shares"] * cp
                print(f"    {sym:<8} {pos['shares']:>4}sh @ ${cp:<8.2f} ({pnl:+.1f}%) ${val:>8,.0f}")
            else:
                print(f"    {sym:<8} {pos['shares']:>4}sh @ ${pos['entry_price']:<8.2f} (N/A)")

    if scion_positions:
        print(f"\n  Scion-Bot Holdings:")
        spm = __import__("portfolio", fromlist=["ScionPortfolioManager"]).ScionPortfolioManager()
        for sym, pos in sorted(scion_positions.items()):
            cp = spm.get_current_price(sym)
            if cp:
                pnl = (cp - pos["entry_price"]) / pos["entry_price"] * 100
                val = pos["shares"] * cp
                sl = pos.get("stop_loss", "N/A")
                print(f"    {sym:<8} {pos['shares']:>4}sh @ ${cp:<8.2f} ({pnl:+.1f}%) ${val:>8,.0f} SL:${sl}")
            else:
                print(f"    {sym:<8} {pos['shares']:>4}sh @ ${pos['entry_price']:<8.2f} (N/A)")

    print("=" * 60)

    if args.notify:
        notifier = ScionNotifier(recipient_id=args.recipient)
        notifier.send_alert("COMBINED PORTFOLIO",
            f"Omaha: {len(omaha_positions)} pos, ${omaha_cash:,.0f} cash | "
            f"Scion: {len(scion_positions)} pos, ${scion_cash:,.0f} cash | "
            f"Total: {len(omaha_positions) + len(scion_positions)} pos, {cash_pct:.0f}% cash")


def cmd_run(args):
    """
    Full automated review cycle (Buffett-style):
      1. Review existing portfolio holdings
      2. Run the quality compounder screener
      3. Deep-dive the top new candidate (if score > 70)
      4. Scan news for moat threats
      5. Send consolidated WhatsApp alert
    """
    import yfinance as yf
    from buffett_analyzer import BuffettAnalyzer
    from buffett_news_engine import BuffettNewsEngine
    from buffett_portfolio import BuffettPortfolioManager
    from buffett_screener import BuffettScreener
    from earnings import (
        format_earnings_brief,
        format_earnings_warning,
        get_upcoming_earnings,
    )
    from notify import ScionNotifier
    from performance_tracker import (
        log_run_cycle,
        log_screener_result,
        snapshot_portfolio,
    )

    print("\n" + "=" * 60)
    print("  OMAHA-BOT: FULL AUTOMATED REVIEW CYCLE")
    print(f"  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    print("\n--- STEP 1: Portfolio Review ---")
    pm = BuffettPortfolioManager()
    if pm.positions:
        print(f"  Holdings: {len(pm.positions)}/{pm.max_positions} positions")
        print(f"  Cash: ${pm.cash:,.0f} ({pm.get_cash_position_pct():.1f}%)")
        actions = pm.check_all_positions()
        if actions:
            print(f"  {len(actions)} valuation warning(s):")
            for a in actions:
                print(f"    [{a.get('action', 'FLAG')}] {a.get('symbol', '')}")
        else:
            print("  All positions within normal parameters. No action needed.")
    else:
        print("  No open positions. Cash: ${:,.0f} ({:.1f}%) — waiting for fat pitches.".format(
            pm.cash, pm.get_cash_position_pct()))

    print("\n--- STEP 2: Quality Compounder Screener ---")
    screener = BuffettScreener()
    results = screener.run_screener()
    top_symbol = None
    top_score = 0
    if not results.empty:
        top_symbol = results.iloc[0]["Symbol"]
        top_score = results.iloc[0]["Buffett Score"]
        print(f"\n  Top candidate: {top_symbol} (Score: {top_score})")
        for _, row in results.iterrows():
            log_screener_result("omaha", row["Symbol"], row["Buffett Score"], row["Price"])
    else:
        print("\n  No candidates met the 40-point threshold.")

    print("\n--- STEP 3: Deep-Dive Analysis ---")
    if top_symbol and top_score >= 70:
        from earnings import get_earnings_analysis
        ea = get_earnings_analysis(top_symbol)
        if ea and ea.get("next_date"):
            print(f"  Next earnings: {ea['next_date']}")
            if ea.get("eps_avg"):
                print(f"  EPS est: ${ea['eps_avg']:.2f}")
        analyzer = BuffettAnalyzer(top_symbol)
        analyzer.generate_full_report()
        print(f"  Deep-dive report saved to buffett_report_{top_symbol}.md")
    elif top_symbol:
        print(f"  {top_symbol} scored {top_score} — below 70 for deep-dive. Add to watchlist.")
    else:
        print("  No candidate to analyze.")

    print("\n--- STEP 4: Moat News Scan ---")
    engine = BuffettNewsEngine(watchlist=DEFAULT_WATCHLIST)
    for sym in pm.positions:
        engine.add_to_watchlist(sym)
    scan = engine.scan_watchlist()
    alert_text = engine.generate_alert_text(scan)
    if alert_text:
        print(alert_text)
    else:
        print("  No new significant moat-related news.")

    print("\n--- STEP 5: Earnings Calendar Check ---")
    try:
        watchlist_for_earnings = DEFAULT_WATCHLIST + list(pm.positions.keys())
        earnings_list = get_upcoming_earnings(watchlist_for_earnings)
        brief = format_earnings_brief(earnings_list)
        if brief:
            print(brief)
        warning = format_earnings_warning(earnings_list, list(pm.positions.keys()))
        if warning:
            print(warning)
    except Exception:
        print("  (Could not fetch earnings data)")

    print("\n--- STEP 6: Consolidated Summary ---")
    notifier = ScionNotifier(recipient_id=args.recipient)
    alert_parts = []
    alert_parts.append(f"OMAHA-BOT REVIEW [{datetime.datetime.now().strftime('%m/%d %H:%M')}]\n")

    if pm.positions:
        lines = [f"Holdings: {len(pm.positions)}/{pm.max_positions} | Cash: ${pm.cash:,.0f} ({pm.get_cash_position_pct():.1f}%)"]
        for sym, pos in pm.positions.items():
            cp = pm.get_current_price(sym)
            if cp:
                pnl = (cp - pos["entry_price"]) / pos["entry_price"] * 100
                lines.append(f"  {sym}: {pos['shares']}sh @ ${cp} ({pnl:+.1f}%)")
        alert_parts.append("\n".join(lines))
    else:
        alert_parts.append("No open positions — 100% cash")

    if not results.empty:
        top3 = results.head(3)
        alert_parts.append("\nTOP SCREENER RESULTS:")
        for _, row in top3.iterrows():
            alert_parts.append(f"  [{row['Symbol']}] {row['Buffett Score']}/100 | ${row['Price']}")

    consolidated = "\n".join(alert_parts)

    if args.notify:
        notifier.send_alert("OMAHA-BOT REVIEW CYCLE", consolidated)
    else:
        print(consolidated)

    if pm.positions:
        print(f"\n{pm.get_portfolio_summary()}")

    import yfinance as yf
    positions_snapshot = []
    for sym, pos in pm.positions.items():
        try:
            cp = yf.Ticker(sym).history(period="1d")["Close"].iloc[-1]
            cp = float(cp)
        except Exception:
            cp = 0
        entry = pos.get("entry_price", 0)
        pnl = round((cp - entry) / entry * 100, 1) if cp and entry else 0
        positions_snapshot.append({
            "symbol": sym,
            "shares": pos.get("shares", 0),
            "cost_basis": entry,
            "current_price": cp,
            "unrealized_pnl_pct": pnl,
            "position_pct": pos.get("position_pct", 0),
        })
    snapshot_portfolio("omaha", positions_snapshot)
    if top_symbol:
        log_run_cycle("omaha", top_symbol, top_score, len(results))

    print("\n" + "=" * 60)
    print("  REVIEW CYCLE COMPLETE — performance logged")
    print("=" * 60)


def build_parser():
    parser = argparse.ArgumentParser(description="Omaha-Bot: Warren Buffett Quality Compounder Agent")
    parser.add_argument("--notify", action="store_true", help="Send alerts via WhatsApp")
    parser.add_argument("--recipient", type=str, default=None, help="WhatsApp chat ID")
    parser.add_argument("--watchlist", type=str, default=None, help="Comma-separated ticker list")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("screener", help="Run the quality compounder screener")
    subparsers.add_parser("analyze", help="Deep-dive a ticker (Four Filters)").add_argument("symbol", type=str)
    subparsers.add_parser("portfolio", help="Show portfolio summary")
    subparsers.add_parser("check", help="Review all positions (intrinsic value checks)")

    add_p = subparsers.add_parser("add", help="Manually add a long-term position")
    add_p.add_argument("symbol", type=str)
    add_p.add_argument("--score", type=int, default=0)
    add_p.add_argument("--reasons", type=str, default="")

    trim_p = subparsers.add_parser("trim", help="Trim an overweight position")
    trim_p.add_argument("symbol", type=str)
    trim_p.add_argument("--pct", type=float, default=25.0, help="Percentage of position to trim (default: 25)")
    trim_p.add_argument("--reason", type=str, default=None)

    close_p = subparsers.add_parser("close", help="Close a position (thesis break)")
    close_p.add_argument("symbol", type=str)
    close_p.add_argument("--reason", type=str, default=None)

    subparsers.add_parser("news", help="Scan watchlist for moat-threat news")
    subparsers.add_parser("premarket", help="Generate pre-market briefing")
    subparsers.add_parser("combined", help="Combined dual-agent portfolio view")
    subparsers.add_parser("run", help="Full automated review cycle")

    # --- Performance tracking commands ---
    log_entry_p = subparsers.add_parser("log-entry", help="Log a trade entry to tracker")
    log_entry_p.add_argument("symbol", type=str)
    log_entry_p.add_argument("--entry", type=float, required=True)
    log_entry_p.add_argument("--stop", type=float)
    log_entry_p.add_argument("--t1", type=float)
    log_entry_p.add_argument("--t2", type=float)
    log_entry_p.add_argument("--score", type=int, default=0)
    log_entry_p.add_argument("--thesis", type=str, default="")

    log_exit_p = subparsers.add_parser("log-exit", help="Log a trade exit to tracker")
    log_exit_p.add_argument("symbol", type=str)
    log_exit_p.add_argument("--exit", type=float)
    log_exit_p.add_argument("--reason", type=str, default="manual")

    report_p = subparsers.add_parser("report", help="Generate performance report")
    report_p.add_argument("--bot", type=str, help="Filter by bot (scion, omaha)")

    feedback_p = subparsers.add_parser("feedback", help="Generate strategy feedback")
    feedback_p.add_argument("--no-interactive", action="store_true", help="Skip prompts")

    subparsers.add_parser("daily-check", help="Daily position monitor")

    tracker_p = subparsers.add_parser("tracker", help="Show open positions from tracker")

    debate_p = subparsers.add_parser("debate", help="Run Bull/Bear/Judge debate on a ticker")
    debate_p.add_argument("symbol", type=str)
    debate_p.add_argument("--compile", action="store_true", help="Skip prepare, just compile from existing agent files")

    return parser


def _result_code(result):
    return result if isinstance(result, int) else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "screener":
        return _result_code(cmd_screener(args))
    elif args.command == "analyze":
        return _result_code(cmd_analyze(args))
    elif args.command == "portfolio":
        return _result_code(cmd_portfolio(args))
    elif args.command == "check":
        return _result_code(cmd_check(args))
    elif args.command == "add":
        return _result_code(cmd_add(args))
    elif args.command == "trim":
        return _result_code(cmd_trim(args))
    elif args.command == "close":
        return _result_code(cmd_close(args))
    elif args.command == "news":
        return _result_code(cmd_news(args))
    elif args.command == "premarket":
        return _result_code(cmd_premarket(args))
    elif args.command == "combined":
        return _result_code(cmd_combined(args))
    elif args.command == "run":
        return _result_code(cmd_run(args))
    elif args.command == "log-entry":
        return _result_code(cmd_log_entry(args))
    elif args.command == "log-exit":
        return _result_code(cmd_log_exit(args))
    elif args.command == "report":
        return _result_code(cmd_report(args))
    elif args.command == "feedback":
        return _result_code(cmd_feedback(args))
    elif args.command == "daily-check":
        return _result_code(cmd_daily_check(args))
    elif args.command == "debate":
        from debate import cmd_compile, cmd_debate, cmd_prepare
        if args.compile:
            result = cmd_compile(args.symbol)
        else:
            result = cmd_debate(args.symbol)
        return _result_code(result)
    elif args.command == "tracker":
        return _result_code(cmd_tracker(args))
    else:
        parser.print_help()
        print("\nExample usage:")
        print("  python buffett_main.py screener             # Screen for quality compounders")
        print("  python buffett_main.py analyze KO           # Deep-dive Coca-Cola")
        print("  python buffett_main.py portfolio             # View positions")
        print("  python buffett_main.py check                # Review intrinsic values")
        print("  python buffett_main.py news                 # Scan for moat threats")
        print("  python buffett_main.py premarket             # Pre-market briefing")
        print("  python buffett_main.py combined              # Combined dual-agent portfolio")
        print("  python buffett_main.py add KO               # Open a position")
        print("  python buffett_main.py trim KO --pct 25     # Trim overweight position")
        print("  python buffett_main.py close KO              # Exit position")
        print("  python buffett_main.py run                  # Full review cycle")
        print("  python buffett_main.py log-entry AAPL ...   # Log a trade to tracker")
        print("  python buffett_main.py log-exit AAPL ...    # Log a trade exit")
        print("  python buffett_main.py report               # Performance report")
        print("  python buffett_main.py feedback             # Strategy feedback")
        print("  python buffett_main.py daily-check          # Daily position monitor")
        print("  python buffett_main.py tracker              # Show open positions")
        print("  python buffett_main.py debate AAPL          # Bull/Bear/Judge debate on a ticker")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
