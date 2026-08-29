"""
SCION-BOT: Michael Burry Swing Trading Agent - Main Orchestrator

This is the main entry point that ties together:
  1. Screener (screener.py) - finds roadkill/ick swing candidates
  2. Analyzer (analyzer.py) - deep-dive fundamental + technical analysis
  3. News Engine (news_engine.py) - monitors for catalysts and sentiment shifts
  4. Portfolio Manager (portfolio.py) - tracks positions, enforces stop-loss/targets
  5. Notifier (notify.py) - sends WhatsApp alerts via zappy-mcp

Usage:
  python main.py screener          # Run the screener
  python main.py analyze PFE       # Deep-dive a specific ticker
  python main.py news              # Scan watchlist for new catalysts
  python main.py portfolio          # Show portfolio summary
  python main.py check              # Check all positions for stop-loss/target triggers
  python main.py run               # Full automated cycle: screen -> analyze top -> check -> news -> alert
  python main.py add PFE           # Manually add a position to the portfolio
"""
import sys
import os
import datetime
import argparse

# Ensure local imports work regardless of CWD
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from screener import ScionScreener
from analyzer import ScionAnalyzer
from news_engine import NewsEngine
from portfolio import ScionPortfolioManager
from notify import ScionNotifier, format_screener_alert, format_portfolio_alert
from performance_tracker import log_screener_result, log_run_cycle, log_portfolio_action, snapshot_portfolio
from earnings import get_upcoming_earnings, format_earnings_brief, format_earnings_warning


DEFAULT_WATCHLIST = [
    "EL", "LULU", "MELI", "REGN", "MOH",
    "INTC", "CVS", "PFE", "DIS", "T", "F", "GM", "KSS",
    "M", "XOM", "CVX", "DAL", "UAL", "AAL", "LMT", "GD", "NOC",
    "FCX", "NEM", "WBA"  # Note: WBA may be delisted - removed at runtime
]


def cmd_screener(args):
    """Run the screener on the default or custom watchlist."""
    watchlist = args.watchlist.split(",") if args.watchlist else None
    if watchlist:
        watchlist = [t.strip().upper() for t in watchlist]

    print(f"\n{'='*60}")
    print("  SCION SWING SCREENER - Launching Market Scan")
    print(f"{'='*60}\n")

    screener = ScionScreener(tickers=watchlist)
    results = screener.run_screener()

    if results.empty:
        print("\nNo candidates met the 25-point Scion threshold today.")
        return

    print(f"\n{'='*60}")
    print(f"  {len(results)} CANDIDATES FOUND (Score >= 25)")
    print(f"{'='*60}\n")

    pd = __import__('pandas')
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1200)
    display_cols = ["Symbol", "Price", "Dist from Low", "Current Ratio",
                    "Debt/Equity", "FCF Yield", "Sentiment", "Scion Score"]
    print(results[display_cols].to_string(index=False))
    print(f"\nFull report saved to: screener_output.md")

    # Send WhatsApp alert if enabled
    if args.notify:
        notifier = ScionNotifier(recipient_id=args.recipient)
        alert_body = format_screener_alert(results, top_n=5)
        if alert_body:
            notifier.send_alert("SCION SCREENER RESULTS", alert_body)

    # Show top candidate for deep-dive suggestion
    top = results.iloc[0]
    print(f"\n>>> TOP CANDIDATE: {top['Symbol']} (Score: {top['Scion Score']})")
    print(f">>> Run deep-dive: python main.py analyze {top['Symbol']}")


def cmd_analyze(args):
    """Run the deep-dive analyzer on a specific ticker."""
    analyzer = ScionAnalyzer(args.symbol)
    report = analyzer.generate_full_report()

    if args.notify:
        notifier = ScionNotifier(recipient_id=args.recipient)
        notifier.send_alert(
            f"SCION DEEP-DIVE: {args.symbol}",
            f"Report saved to scion_report_{args.symbol}.md. Run 'python main.py add {args.symbol}' to open position."
        )


def cmd_news(args):
    """Scan the watchlist for new news catalysts."""
    watchlist = args.watchlist.split(",") if args.watchlist else DEFAULT_WATCHLIST
    watchlist = [t.strip().upper() for t in watchlist]

    print("\n[NewsEngine] Scanning watchlist for new catalysts...")
    engine = NewsEngine(watchlist=watchlist)
    results = engine.scan_watchlist()
    alert_text = engine.generate_alert_text(results)

    if alert_text:
        print("\n" + alert_text)
        if args.notify:
            notifier = ScionNotifier(recipient_id=args.recipient)
            notifier.send_alert("SCION NEWS CATALYST ALERT", alert_text)
    else:
        print("\nNo new significant news catalysts detected.")


def cmd_portfolio(args):
    """Display portfolio summary."""
    pm = ScionPortfolioManager()
    summary = pm.get_portfolio_summary()
    print(summary)

    if args.notify:
        notifier = ScionNotifier(recipient_id=args.recipient)
        notifier.send_alert("SCION PORTFOLIO UPDATE", summary)


def cmd_check(args):
    """Check all open positions for stop-loss and target triggers."""
    pm = ScionPortfolioManager()
    print("\n[Portfolio] Checking all open positions for action triggers...")
    actions = pm.check_all_positions()

    if not actions:
        print("No actions triggered. All positions within normal parameters.")
        return

    print(f"\n{len(actions)} action(s) triggered:\n")
    alert_lines = []
    for a in actions:
        msg = f"  [{a['action']}] {a.get('symbol', 'N/A')}: "
        if a["action"] == "CLOSED":
            msg += f"Shares: {a['shares']} | Price: ${a['price']} | PnL: ${a['realized_pnl']} ({a['realized_pct']}) | Reason: {a['reason']}"
        elif a["action"] == "SCALED_OUT":
            msg += f"Sold: {a['shares_sold']} @ ${a['price']} | Remaining: {a['shares_remaining']} | Reason: {a['reason']}"
        else:
            msg += str(a)
        print(msg)
        alert_lines.append(msg)

    if args.notify:
        notifier = ScionNotifier(recipient_id=args.recipient)
        notifier.send_alert("SCION PORTFOLIO ACTION TRIGGERED", "\n".join(alert_lines))


def cmd_add(args):
    """Manually add a position to the portfolio."""
    pm = ScionPortfolioManager()

    # Try to get technical levels from yfinance
    import yfinance as yf
    t = yf.Ticker(args.symbol)
    hist = t.history(period="6mo")
    if hist.empty:
        print(f"Could not fetch data for {args.symbol}")
        return

    entry = float(hist["Close"].iloc[-1])
    low_52w = float(hist["Close"].min())
    stop_loss = round(low_52w * 0.97, 2)
    target_1 = round(entry * 1.20, 2)
    target_2 = round(entry * 1.40, 2)

    result = pm.open_position(
        symbol=args.symbol.upper(),
        entry_price=entry,
        stop_loss=stop_loss,
        target_1=target_1,
        target_2=target_2,
        score=args.score if args.score else 0,
        reasons=args.reasons if args.reasons else "Manual entry"
    )
    print(f"\nPosition opened: {result}")
    print(f"\n{pm.get_portfolio_summary()}")

    if args.notify:
        notifier = ScionNotifier(recipient_id=args.recipient)
        body = f"Opened {result['shares']} shares of {args.symbol} @ ${entry}\nStop: ${stop_loss} | T1: ${target_1} | T2: ${target_2}"
        notifier.send_alert("SCION POSITION OPENED", body)


def cmd_run(args):
    """
    Full automated cycle:
      1. Screen the market for candidates
      2. Deep-dive the top candidate
      3. Check existing positions for stop-loss/targets
      4. Scan news on watchlist
      5. Send consolidated WhatsApp alert
    """
    print("\n" + "=" * 60)
    print("  SCION-BOT: FULL AUTOMATED CYCLE")
    print(f"  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Step 1: Check existing portfolio positions
    print("\n--- STEP 1: Portfolio Position Check ---")
    pm = ScionPortfolioManager()
    if pm.positions:
        actions = pm.check_all_positions()
        if actions:
            print(f"  {len(actions)} action(s) triggered!")
            for a in actions:
                print(f"    [{a['action']}] {a.get('symbol', '')}: {a.get('reason', '')}")
                log_portfolio_action("scion", a.get("symbol", ""), a["action"],
                                      a.get("price", 0), a.get("reason", ""))
        else:
            print("  All positions within normal parameters.")
    else:
        print("  No open positions to check.")

    # Step 2: Run the screener
    print("\n--- STEP 2: Market Screener ---")
    screener = ScionScreener()
    results = screener.run_screener()
    if not results.empty:
        top_symbol = results.iloc[0]["Symbol"]
        top_score = results.iloc[0]["Scion Score"]
        print(f"\n  Top candidate: {top_symbol} (Score: {top_score})")
        for _, row in results.iterrows():
            log_screener_result("scion", row["Symbol"], row["Scion Score"], row["Price"])
    else:
        top_symbol = None
        print("\n  No candidates met threshold.")

    # Step 3: Deep-dive the top candidate
    if top_symbol and top_score >= 50:
        print(f"\n--- STEP 3: Deep-Dive Analysis of {top_symbol} ---")
        from earnings import get_earnings_analysis
        ea = get_earnings_analysis(top_symbol)
        if ea and ea.get("next_date"):
            print(f"  Next earnings: {ea['next_date']}")
            if ea.get("eps_avg"):
                print(f"  EPS est: ${ea['eps_avg']:.2f}")
        analyzer = ScionAnalyzer(top_symbol)
        analyzer.generate_full_report()
        print(f"  Report saved to scion_report_{top_symbol}.md")

    # Step 4: News scan
    print("\n--- STEP 4: News Catalyst Scan ---")
    engine = NewsEngine(watchlist=DEFAULT_WATCHLIST)
    # Add open position symbols to watchlist
    for sym in pm.positions:
        engine.add_to_watchlist(sym)
    scan = engine.scan_watchlist()
    alert_text = engine.generate_alert_text(scan)
    if alert_text:
        print(alert_text)
    else:
        print("  No new significant news catalysts.")

    # Step 5: Earnings check + Consolidated alert
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

    print("\n--- STEP 6: Consolidated Alert ---")
    notifier = ScionNotifier(recipient_id=args.recipient)

    alert_parts = []
    alert_parts.append(f"SCION-BOT DAILY CYCLE [{datetime.datetime.now().strftime('%m/%d %H:%M')}]\n")

    if pm.positions:
        alert_parts.append(f"PORTFOLIO: {len(pm.positions)}/18 positions open")
        alert_parts.append(f"Cash: ${pm.cash:,.0f}")
    else:
        alert_parts.append("PORTFOLIO: No open positions")

    if not results.empty:
        top3 = results.head(3)
        alert_parts.append("\nTOP SCREENER CANDIDATES:")
        for _, row in top3.iterrows():
            alert_parts.append(f"  [{row['Symbol']}] Score:{row['Scion Score']} | ${row['Price']} | {row['Dist from Low']} | Sentiment:{row['Sentiment']}")

    if alert_text:
        for line in alert_text.split("\n"):
            if line.startswith("  [") or line.startswith("*") and "ALERT" not in line:
                alert_parts.append(line)

    consolidated = "\n".join(alert_parts)

    if args.notify:
        notifier.send_alert("SCION-BOT DAILY CYCLE", consolidated)
    else:
        print(consolidated)

    # Log performance
    if not results.empty:
        positions_snapshot = []
        for sym, pos in pm.positions.items():
            try:
                cp = yf.Ticker(sym).history(period="1d")["Close"].iloc[-1]
            except Exception:
                cp = 0
            positions_snapshot.append({
                "symbol": sym,
                "shares": pos.get("shares", 0),
                "cost_basis": pos.get("entry_price", 0),
                "current_price": float(cp) if cp else 0,
                "unrealized_pnl_pct": round((float(cp) - pos.get("entry_price", 0)) / pos.get("entry_price", 1) * 100, 1) if cp else 0,
                "position_pct": pos.get("position_pct", 0),
            })
        snapshot_portfolio("scion", positions_snapshot)
        log_run_cycle("scion", top_symbol or "", top_score or 0, len(results))

    print("\n" + "=" * 60)
    print("  CYCLE COMPLETE — performance logged")
    print("=" * 60)


def cmd_premarket(args):
    """Generate a pre-market briefing for Scion-Bot swing trading."""
    print("\n" + "=" * 60)
    print("  SCION-BOT: PRE-MARKET BRIEFING")
    print(f"  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    import yfinance as yf

    print("\n--- Market Context ---")
    spy_close = None
    vix_close = None
    try:
        spy = yf.Ticker("SPY")
        spy_hist = spy.history(period="5d")
        if not spy_hist.empty:
            spy_close = spy_hist["Close"].iloc[-1]
            spy_change = (spy_hist["Close"].iloc[-1] - spy_hist["Close"].iloc[-2]) / spy_hist["Close"].iloc[-2] * 100
            spy_52w_low = spy_hist["Close"].min()
            print(f"  SPY: ${spy_close:.2f} ({spy_change:+.2f}%) | 52W Low: ${spy_52w_low:.2f}")

        vix = yf.Ticker("^VIX")
        vix_hist = vix.history(period="5d")
        if not vix_hist.empty:
            vix_close = vix_hist["Close"].iloc[-1]
            vix_regime = "HIGH (caution)" if vix_close > 20 else "LOW (risk-on)" if vix_close < 15 else "NORMAL"
            print(f"  VIX: {vix_close:.2f} — {vix_regime}")
    except Exception as e:
        print(f"  (Could not fetch market data: {e})")

    try:
        from credit_monitor import CreditMonitor
        credit_pulse, credit_score, credit_label, _ = CreditMonitor().quick_pulse()
        print(f"\n--- Credit Stress: {credit_score:.0f}/100 ({credit_label}) ---")
        print(f"  {credit_pulse}")
    except Exception:
        pass

    try:
        watchlist_earnings = args.watchlist.split(",") if args.watchlist else DEFAULT_WATCHLIST
        watchlist_earnings = [t.strip().upper() for t in watchlist_earnings]
        earnings_list = get_upcoming_earnings(watchlist_earnings)
        brief = format_earnings_brief(earnings_list)
        if brief:
            print("\n--- Upcoming Earnings ---")
            print(brief)
    except Exception:
        pass

    try:
        from ta_lib import compute_all as compute_ta
        pulse_tickers = [t.strip().upper() for t in (args.watchlist.split(",") if args.watchlist else DEFAULT_WATCHLIST[:6])]
        print("\n--- Technical Pulse ---")
        for t in pulse_tickers:
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
        sm_tickers = [t.strip().upper() for t in (args.watchlist.split(",") if args.watchlist else DEFAULT_WATCHLIST[:4])]
        print("\n--- Smart Money Pulse ---")
        for t in sm_tickers:
            try:
                print(f"  {t:6s}:  {get_smart_money_summary(t)}")
            except Exception:
                print(f"  {t:6s}:  N/A")
    except Exception:
        pass

    print("\n--- Overnight News Scan ---")
    engine = NewsEngine(watchlist=DEFAULT_WATCHLIST)
    results = engine.scan_watchlist()
    alert_text = engine.generate_alert_text(results)
    if alert_text:
        significant = [l for l in alert_text.split("\n") if l.startswith("  [")]
        if significant:
            print("  Overnight news on swing candidates:")
            for line in significant:
                print(f"    {line}")
        else:
            print("  No significant overnight news.")
    else:
        print("  No significant overnight news.")

    print("\n--- Screener Pulse (Top Swing Candidates Now) ---")
    watchlist = args.watchlist.split(",") if args.watchlist else None
    if watchlist:
        watchlist = [t.strip().upper() for t in watchlist]
    screener = ScionScreener(tickers=watchlist)
    results = screener.run_screener()
    if not results.empty:
        top5 = results.head(5)
        pd = __import__("pandas")
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 1200)
        display_cols = ["Symbol", "Price", "Dist from Low", "Current Ratio", "Debt/Equity", "FCF Yield", "Sentiment", "Scion Score"]
        print(top5[display_cols].to_string(index=False))
        print(f"\n  Full screener: python main.py screener")
    else:
        print("  No swing candidates above 25-point threshold.")

    print("\n--- Pre-Market Action Plan ---")
    print("  [1] Run screener:   python main.py screener")
    print("  [2] Run full cycle:  python main.py run")
    print("  [3] Check portfolio: python main.py portfolio")
    print("  [4] Combined view:   python buffett_main.py combined")
    print()

    if args.notify:
        notifier = ScionNotifier(recipient_id=args.recipient)
        parts = []
        if spy_close is not None:
            parts.append(f"SPY ${spy_close:.2f}")
        if vix_close is not None:
            parts.append(f"VIX {vix_close:.2f}")
        parts.append(f"{len(results)} candidates")
        notifier.send_alert("SCION PRE-MARKET", " | ".join(parts))


def cmd_log_entry(args):
    """Log a trade entry to the performance tracker."""
    from tracker import Tracker
    t = Tracker()
    t.log_entry(
        ticker=args.symbol, bot="scion", entry_price=args.entry,
        stop_loss=args.stop, target1=args.t1, target2=args.t2,
        score=args.score, thesis=args.thesis
    )


def cmd_log_exit(args):
    """Log a trade exit to the performance tracker."""
    from tracker import Tracker
    t = Tracker()
    t.log_exit(ticker=args.symbol, exit_price=args.exit, exit_reason=args.reason)


def cmd_report(args):
    """Generate performance report and save to vault."""
    from report_card import cmd_report as rc
    rc(bot=args.bot)


def cmd_feedback(args):
    """Generate strategy feedback with interactive apply."""
    from feedback import cmd_feedback as fb
    fb(interactive=not args.no_interactive)


def cmd_daily_check(args):
    """Daily position monitor — logs snapshot and writes vault brief."""
    from daily_check import cmd_check as dc
    dc()


def cmd_tracker(args):
    """Tracker status: show all open positions."""
    from tracker import Tracker
    t = Tracker()
    open_pos = t.get_open_positions_summary()
    if not open_pos:
        print("  No open positions.")
        return
    print(f"\n  {'Ticker':<8} {'Bot':<8} {'Entry':>8} {'Current':>9} {'P&L%':>7} {'Days':>5} {'StopDist%':>10} {'T1Dist%':>9} {'Score':>5}")
    print("  " + "-" * 75)
    for p in open_pos:
        sd = f"{p['distance_to_stop_pct']:+.1f}%" if p["distance_to_stop_pct"] is not None else "N/A"
        td = f"{p['distance_to_target1_pct']:+.1f}%" if p["distance_to_target1_pct"] is not None else "N/A"
        print(f"  {p['ticker']:<8} {p['bot']:<8} ${p['entry_price']:<6.2f} ${p['current_price']:<7.2f} {p['pnl_pct']:+.2f}% {p['days_held']:>4}d {sd:>9} {td:>8} {p['score']:>5}")


def main():
    parser = argparse.ArgumentParser(description="Scion-Bot: Michael Burry Swing Trading Agent")
    parser.add_argument("--notify", action="store_true", help="Send alerts via WhatsApp")
    parser.add_argument("--recipient", type=str, default=None, help="WhatsApp chat ID")
    parser.add_argument("--watchlist", type=str, default=None, help="Comma-separated ticker list")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("screener", help="Run the market screener")
    subparsers.add_parser("analyze", help="Deep-dive a ticker").add_argument("symbol", type=str)
    subparsers.add_parser("news", help="Scan watchlist for news catalysts")
    subparsers.add_parser("portfolio", help="Show portfolio summary")
    subparsers.add_parser("check", help="Check positions for stop-loss/targets")

    add_p = subparsers.add_parser("add", help="Manually add a position")
    add_p.add_argument("symbol", type=str)
    add_p.add_argument("--score", type=int, default=0)
    add_p.add_argument("--reasons", type=str, default="")

    subparsers.add_parser("premarket", help="Pre-market briefing")
    subparsers.add_parser("run", help="Full automated cycle")

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

    args = parser.parse_args()

    if args.command == "screener":
        cmd_screener(args)
    elif args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "news":
        cmd_news(args)
    elif args.command == "portfolio":
        cmd_portfolio(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "add":
        cmd_add(args)
    elif args.command == "premarket":
        cmd_premarket(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "log-entry":
        cmd_log_entry(args)
    elif args.command == "log-exit":
        cmd_log_exit(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "feedback":
        cmd_feedback(args)
    elif args.command == "daily-check":
        cmd_daily_check(args)
    elif args.command == "debate":
        from debate import cmd_debate, cmd_prepare, cmd_compile
        if args.compile:
            cmd_compile(args.symbol)
        else:
            cmd_debate(args.symbol)
    elif args.command == "tracker":
        cmd_tracker(args)
    else:
        parser.print_help()
        print("\nExample usage:")
        print("  python main.py screener           # Scan the market")
        print("  python main.py analyze PFE        # Deep-dive PFE")
        print("  python main.py news               # Check for catalysts")
        print("  python main.py portfolio           # View positions")
        print("  python main.py check              # Check stop-losses/targets")
        print("  python main.py premarket           # Pre-market briefing")
        print("  python main.py add PFE             # Open a position")
        print("  python main.py run                 # Full automated cycle")
        print("  python main.py log-entry AAPL ...  # Log a trade to tracker")
        print("  python main.py log-exit AAPL ...   # Log a trade exit")
        print("  python main.py report              # Performance report")
        print("  python main.py feedback            # Strategy feedback")
        print("  python main.py daily-check         # Daily position monitor")
        print("  python main.py tracker             # Show open positions")
        print("  python main.py debate AAPL         # Bull/Bear/Judge debate on a ticker")


if __name__ == "__main__":
    main()
