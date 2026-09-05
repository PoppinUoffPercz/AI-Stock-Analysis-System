"""
Debate Engine — Bull vs Bear vs Judge

Dispatches subagent roles (Bull, Bear, Judge) that argue over a ticker's prospects.
Each agent reads the same pre-fetched data but writes from their assigned perspective.
The Judge critiques both sides and produces a consensus with a debate score (0-100).
The debate score feeds into position scoring as a modifier (-20 to +20).

Usage:
  python debate.py AAPL                   # Full flow: prep -> wait for agents -> compile
  python debate.py prepare AAPL            # Step 1: fetch data, write JSON, print prompts
  python debate.py compile AAPL            # Step 3: read agent files, write vault report

Agent files (written by subagents):
  debate_data_{TICKER}.json     — structured data
  debate_bull_{TICKER}.md       — Bull case
  debate_bear_{TICKER}.md       — Bear case
  debate_judge_{TICKER}.md      — Judge critique + consensus

Vault output:
  Stock Research/Daily Briefs/YYYY-MM-DD {TICKER} Debate.md
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yfinance as yf
from smart_money import get_smart_money_score
from ta_lib import compute_atr, compute_macd, compute_rsi, compute_smas

VAULT_DIR = os.path.join(os.path.expanduser("~"),
    "OneDrive", "Documents", "Obsidian Vault",
    "Stock Research", "Debates")

DEBATE_DIR = os.path.dirname(os.path.abspath(__file__))

DEBATE_SCORES_FILE = os.path.join(DEBATE_DIR, "debate_scores.json")


def _ensure_vault_dir():
    os.makedirs(VAULT_DIR, exist_ok=True)
    return VAULT_DIR


def _fmt(val, style="float"):
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
        return f"{v:.2f}"
    except (ValueError, TypeError):
        return str(val)


def fetch_debate_data(ticker):
    """Fetch all relevant data for a debate using existing pipelines."""
    result = {"ticker": ticker.upper(), "fetched_at": datetime.datetime.now().isoformat()}
    t = yf.Ticker(ticker)

    # Company info
    try:
        info = t.info
        result["company_name"] = info.get("longName", ticker)
        result["sector"] = info.get("sector", "Unknown")
        result["industry"] = info.get("industry", "Unknown")
        result["market_cap"] = info.get("marketCap")
        result["beta"] = info.get("beta")
    except Exception:
        result["company_name"] = ticker

    # Price data
    try:
        hist = t.history(period="1y")
        if not hist.empty:
            cp = float(hist["Close"].iloc[-1])
            low_52w = float(hist["Close"].min())
            high_52w = float(hist["Close"].max())
            result["current_price"] = round(cp, 2)
            result["low_52w"] = round(low_52w, 2)
            result["high_52w"] = round(high_52w, 2)
            result["pct_from_low"] = round((cp - low_52w) / low_52w * 100, 1) if low_52w > 0 else None
            result["pct_from_high"] = round((cp - high_52w) / high_52w * 100, 1) if high_52w > 0 else None
    except Exception:
        hist = None

    # Technical indicators
    if hist is not None and not hist.empty and len(hist) >= 60:
        rsi = compute_rsi(hist["Close"])
        macd = compute_macd(hist["Close"])
        smas = compute_smas(hist["Close"], periods=[20, 50, 200])
        atr = compute_atr(hist)
        result["rsi"] = rsi.get("value")
        result["rsi_regime"] = rsi.get("regime", "neutral")
        result["macd_cross"] = macd.get("cross_signal")
        result["sma20"] = round(smas.get(20, 0), 2) if smas.get(20) else None
        result["sma50"] = round(smas.get(50, 0), 2) if smas.get(50) else None
        result["sma200"] = round(smas.get(200, 0), 2) if smas.get(200) else None
        result["atr"] = round(atr.get("value", 0), 2) if atr.get("value") else None

    # Financials
    try:
        result["pe_ratio"] = info.get("trailingPE")
        result["forward_pe"] = info.get("forwardPE")
        result["peg_ratio"] = info.get("pegRatio")
        result["price_to_book"] = info.get("priceToBook")
        result["roe"] = info.get("returnOnEquity")
        result["roa"] = info.get("returnOnAssets")
        result["gross_margins"] = info.get("grossMargins")
        result["operating_margins"] = info.get("operatingMargins")
        result["profit_margins"] = info.get("profitMargins")
        result["debt_to_equity"] = info.get("debtToEquity")
        result["current_ratio"] = info.get("currentRatio")
        result["total_revenue"] = info.get("totalRevenue")
        result["revenue_growth"] = info.get("revenueGrowth")
        result["earnings_growth"] = info.get("earningsGrowth")
        result["fcf"] = info.get("freeCashflow")
        result["total_cash"] = info.get("totalCash")
        result["total_debt"] = info.get("totalDebt")
        result["dividend_yield"] = info.get("dividendYield")
        result["shares_outstanding"] = info.get("sharesOutstanding")
        result["insider_pct"] = info.get("heldPercentInsiders")
        result["institutional_pct"] = info.get("heldPercentInstitutions")
    except Exception:
        pass

    # FCF yield
    if result.get("fcf") and result.get("market_cap"):
        result["fcf_yield"] = result["fcf"] / result["market_cap"]

    # Smart money
    try:
        sm = get_smart_money_score(ticker, ticker=t)
        result["smart_money_score"] = sm.get("composite_score")
        result["smart_money_label"] = sm.get("label")
    except Exception:
        pass

    # News (top 5 headlines)
    try:
        news = t.news
        headlines = []
        for item in (news or [])[:5]:
            content = item.get("content", item)
            headlines.append(content.get("title", ""))
        result["headlines"] = headlines
    except Exception:
        result["headlines"] = []

    return result


def get_data_summary(data):
    """Return human-readable markdown summary of the data."""
    lines = [f"## {data.get('company_name', data['ticker'])} ({data['ticker']})"]
    lines.append(f"**Sector:** {data.get('sector', 'N/A')} | **Industry:** {data.get('industry', 'N/A')}")
    lines.append("")
    lines.append("### Price & Technicals")
    lines.append("| Metric | Value |")
    lines.append("| :--- | :--- |")
    lines.append(f"| Current Price | {_fmt(data.get('current_price'), 'dollar')} |")
    lines.append(f"| 52W Range | {_fmt(data.get('low_52w'), 'dollar')} — {_fmt(data.get('high_52w'), 'dollar')} |")
    lines.append(f"| From 52W Low | {_fmt(data.get('pct_from_low'), 'pct')} |")
    lines.append(f"| From 52W High | {_fmt(data.get('pct_from_high'), 'pct')} |")
    lines.append(f"| RSI (14) | {_fmt(data.get('rsi'), 'int')} ({data.get('rsi_regime', 'N/A')}) |")
    lines.append(f"| MACD | {data.get('macd_cross', 'N/A')} |")
    lines.append(f"| SMA50 | {_fmt(data.get('sma50'), 'dollar')} |")
    lines.append(f"| SMA200 | {_fmt(data.get('sma200'), 'dollar')} |")
    lines.append(f"| ATR | {_fmt(data.get('atr'), 'dollar')} |")
    lines.append(f"| Beta | {_fmt(data.get('beta'))} |")
    lines.append("")
    lines.append("### Fundamentals")
    lines.append("| Metric | Value |")
    lines.append("| :--- | :--- |")
    lines.append(f"| Market Cap | {_fmt(data.get('market_cap'), 'dollar')} |")
    lines.append(f"| P/E | {_fmt(data.get('pe_ratio'))}x |")
    lines.append(f"| Forward P/E | {_fmt(data.get('forward_pe'))}x |")
    lines.append(f"| PEG | {_fmt(data.get('peg_ratio'))} |")
    lines.append(f"| P/B | {_fmt(data.get('price_to_book'))} |")
    lines.append(f"| ROE | {_fmt(data.get('roe'), 'pct')} |")
    lines.append(f"| Gross Margin | {_fmt(data.get('gross_margins'), 'pct')} |")
    lines.append(f"| Operating Margin | {_fmt(data.get('operating_margins'), 'pct')} |")
    lines.append(f"| Profit Margin | {_fmt(data.get('profit_margins'), 'pct')} |")
    lines.append(f"| D/E | {_fmt(data.get('debt_to_equity'))} |")
    lines.append(f"| Current Ratio | {_fmt(data.get('current_ratio'))} |")
    lines.append(f"| Revenue Growth | {_fmt(data.get('revenue_growth'), 'pct')} |")
    lines.append(f"| Earnings Growth | {_fmt(data.get('earnings_growth'), 'pct')} |")
    lines.append(f"| FCF Yield | {_fmt(data.get('fcf_yield'), 'pct')} |")
    lines.append(f"| Dividend Yield | {_fmt(data.get('dividend_yield'), 'pct')} |")
    lines.append(f"| Insider Ownership | {_fmt(data.get('insider_pct'), 'pct')} |")
    lines.append("")
    lines.append("### Smart Money")
    lines.append(f"**Score:** {_fmt(data.get('smart_money_score'), 'int')}/100 ({data.get('smart_money_label', 'N/A')})")
    lines.append("")
    if data.get("headlines"):
        lines.append("### Recent Headlines")
        for h in data["headlines"]:
            lines.append(f"- {h}")
        lines.append("")
    return "\n".join(lines)


def get_bull_prompt(data):
    """Prompt for the Bull subagent."""
    return f"""You are a BULLISH analyst. Your job: build the strongest possible bull case for {data.get('company_name', data['ticker'])} ({data['ticker']}).

You have the following data. Do NOT do any math or fetch any additional data. Only use what's provided below.

{get_data_summary(data)}

Write a 2-4 paragraph bull case. Be specific, reference the data, and tell a compelling story about why this stock is a buy. Focus on:
- What's undervalued or misunderstood
- Growth catalysts and competitive advantages
- Why the bears are wrong
- Entry timing (if now is the right time)

Save your response to: debate_bull_{data['ticker']}.md"""


def get_bear_prompt(data):
    """Prompt for the Bear subagent."""
    return f"""You are a BEARISH analyst. Your job: build the strongest possible bear case for {data.get('company_name', data['ticker'])} ({data['ticker']}).

You have the following data. Do NOT do any math or fetch any additional data. Only use what's provided below.

{get_data_summary(data)}

Write a 2-4 paragraph bear case. Be specific, reference the data, and tell a compelling story about why this stock should be avoided or sold. Focus on:
- What's overvalued or deteriorating
- Risks and headwinds being ignored
- Why the bulls are wrong
- Why now is a bad time to enter

Save your response to: debate_bear_{data['ticker']}.md"""


def get_judge_prompt(data):
    """Prompt for the Judge subagent."""
    return f"""You are the JUDGE. Your role: read both the Bull and Bear cases for {data.get('company_name', data['ticker'])} ({data['ticker']}), find flaws in EACH argument, then write a balanced Base Consensus.

Here is the underlying data:

{get_data_summary(data)}

Read the files debate_bull_{data['ticker']}.md and debate_bear_{data['ticker']}.md.

Write a markdown file called debate_judge_{data['ticker']}.md with these sections:

### Flaws in the Bull Case
- List 2-3 specific weaknesses or logical gaps in the bull argument

### Flaws in the Bear Case
- List 2-3 specific weaknesses or logical gaps in the bear argument

### Base Consensus
- 1-2 paragraphs synthesizing the strongest arguments from both sides
- A clear recommendation (Buy / Overweight / Hold / Underweight / Sell)
- A DEBATE SCORE from 0-100 (how bullish is the consensus? 0=strongest sell, 100=strongest buy)

The last line of your file MUST be exactly: DEBATE_SCORE: <number>
So the Judge can extract the score programmatically."""


def save_debate_score(ticker, score):
    """Persist the debate score for use by portfolio/daily check."""
    scores = {}
    if os.path.exists(DEBATE_SCORES_FILE):
        with open(DEBATE_SCORES_FILE, "r") as f:
            scores = json.load(f)
    scores[ticker.upper()] = {"score": score, "updated": datetime.datetime.now().isoformat()}
    with open(DEBATE_SCORES_FILE, "w") as f:
        json.dump(scores, f, indent=2)


def get_debate_score(ticker):
    """Retrieve the stored debate score for a ticker."""
    if not os.path.exists(DEBATE_SCORES_FILE):
        return None
    with open(DEBATE_SCORES_FILE, "r") as f:
        scores = json.load(f)
    entry = scores.get(ticker.upper())
    return entry["score"] if entry else None


def score_modifier(debate_score):
    """Map a debate score (0-100) to a -20 to +20 modifier on the base score."""
    if debate_score is None:
        return 0
    # 50 = neutral -> 0 modifier
    # 100 = max bullish -> +20
    # 0 = max bearish -> -20
    raw = (debate_score - 50) / 50 * 20
    return round(max(-20, min(20, raw)))


def compile_report(ticker, wait=False):
    """Read agent files and compile the final vault report."""
    ticker = ticker.upper()
    bull_file = os.path.join(DEBATE_DIR, f"debate_bull_{ticker}.md")
    bear_file = os.path.join(DEBATE_DIR, f"debate_bear_{ticker}.md")
    judge_file = os.path.join(DEBATE_DIR, f"debate_judge_{ticker}.md")
    data_file = os.path.join(DEBATE_DIR, f"debate_data_{ticker}.json")

    bull_text = ""
    bear_text = ""
    judge_text = ""

    if os.path.exists(bull_file):
        with open(bull_file, "r") as f:
            bull_text = f.read().strip()

    if os.path.exists(bear_file):
        with open(bear_file, "r") as f:
            bear_text = f.read().strip()

    judge_score = None
    if os.path.exists(judge_file):
        with open(judge_file, "r") as f:
            judge_text = f.read().strip()
        for line in judge_text.split("\n"):
            if line.startswith("DEBATE_SCORE:"):
                try:
                    judge_score = int(line.split(":")[1].strip())
                except (ValueError, IndexError):
                    pass

    data = {}
    if os.path.exists(data_file):
        with open(data_file, "r") as f:
            data = json.load(f)

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    name = data.get("company_name", ticker)
    mod = score_modifier(judge_score)

    lines = []
    lines.append("---")
    lines.append(f'title: "Debate — {ticker}"')
    lines.append(f"date: {today}")
    lines.append("tags:")
    lines.append("  - debate")
    lines.append("---")
    lines.append("")
    lines.append(f"# Debate: {name} ({ticker})")
    lines.append(f"> **Generated:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    if bull_text:
        lines.append("## Bull Case")
        lines.append("")
        lines.append(bull_text)
        lines.append("")

    if bear_text:
        lines.append("## Bear Case")
        lines.append("")
        lines.append(bear_text)
        lines.append("")

    if judge_text:
        lines.append("## Judge's Verdict")
        lines.append("")
        lines.append(judge_text)
        lines.append("")

    lines.append("## Score Impact")
    lines.append("")
    if judge_score is not None:
        save_debate_score(ticker, judge_score)
        lines.append("| Component | Value |")
        lines.append("| :--- | :--- |")
        lines.append(f"| **Debate Score** | {judge_score}/100 |")
        lines.append(f"| **Score Modifier** | {mod:+d} |")
        lines.append(f"| **Direction** | {'Bullish' if mod > 5 else 'Bearish' if mod < -5 else 'Neutral'} |")
    else:
        lines.append("_Judge has not yet delivered a verdict._")
    lines.append("")

    # Underlying data
    lines.append("## Underlying Data")
    lines.append("")
    lines.append(get_data_summary(data))
    lines.append("")
    lines.append("---")
    lines.append(f"*Debate concluded at {datetime.datetime.now().strftime('%H:%M')}*")
    lines.append("")

    report = "\n".join(lines)
    filepath = os.path.join(_ensure_vault_dir(), f"{today} {ticker} Debate.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  Debate report saved: {filepath}")
    return report


def cmd_prepare(ticker):
    """Step 1: fetch data, save JSON, print agent prompts."""
    ticker = ticker.upper()
    print(f"\n{'='*60}")
    print(f"  DEBATE PREP: {ticker}")
    print(f"{'='*60}\n")

    data = fetch_debate_data(ticker)

    data_file = os.path.join(DEBATE_DIR, f"debate_data_{ticker}.json")
    with open(data_file, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Data saved: {data_file}")
    print()

    print(get_data_summary(data))
    print()

    print("=" * 60)
    print("  BULL AGENT PROMPT")
    print("=" * 60)
    print()
    print(get_bull_prompt(data))
    print()

    print("=" * 60)
    print("  BEAR AGENT PROMPT")
    print("=" * 60)
    print()
    print(get_bear_prompt(data))
    print()

    print("=" * 60)
    print("  JUDGE AGENT PROMPT")
    print("=" * 60)
    print()
    print(get_judge_prompt(data))
    print()

    print("=" * 60)
    print("  READY FOR SUBAGENTS")
    print("=" * 60)
    print(f"  1. Dispatch Bull agent -> writes debate_bull_{ticker}.md")
    print(f"  2. Dispatch Bear agent -> writes debate_bear_{ticker}.md")
    print(f"  3. Dispatch Judge agent -> writes debate_judge_{ticker}.md")
    print(f"  4. Run: python debate.py compile {ticker}")
    print()


def cmd_compile(ticker):
    """Step 3: compile agent outputs into vault report."""
    ticker = ticker.upper()
    compile_report(ticker)

    # Clean up agent files
    for fname in [f"debate_data_{ticker}.json", f"debate_bull_{ticker}.md",
                  f"debate_bear_{ticker}.md", f"debate_judge_{ticker}.md"]:
        fpath = os.path.join(DEBATE_DIR, fname)
        if os.path.exists(fpath):
            os.remove(fpath)

    score = get_debate_score(ticker)
    mod = score_modifier(score)
    print(f"  Debate Score: {score}/100 | Modifier: {mod:+d}")


def cmd_debate(ticker):
    """Full flow: prepare, print prompts, then compile after subagents."""
    cmd_prepare(ticker)
    print("  [Subagents dispatched externally — run debate compile when done]")
    print(f"  python debate.py compile {ticker}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Bull/Bear/Judge Debate Engine")
    parser.add_argument("command", choices=["prepare", "compile", "debate"],
                        help="prepare=fetch data, compile=build report, debate=full flow")
    parser.add_argument("ticker", type=str, help="Stock ticker")

    args = parser.parse_args()
    if args.command == "prepare":
        cmd_prepare(args.ticker)
    elif args.command == "compile":
        cmd_compile(args.ticker)
    elif args.command == "debate":
        cmd_debate(args.ticker)
