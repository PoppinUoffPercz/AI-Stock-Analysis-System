---
title: "Master Operating Manual — Dual-Agent Trading System"
date: 2026-07-07
tags:
  - docs
  - manual
  - reference
---

# Master Operating Manual

Everything you built, what it does, and how to use it. One document to rule them all.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [The Two Agents](#2-the-two-agents)
3. [Shared Modules](#3-shared-modules)
4. [CLI Quick Reference](#4-cli-quick-reference)
5. [Daily Workflow](#5-daily-workflow)
6. [Weekly Workflow](#6-weekly-workflow)
7. [Signals & Interpretation](#7-signals--interpretation)
8. [Technical Analysis (ta_lib)](#8-technical-analysis-talib)
9. [Smart Money Tracker](#9-smart-money-tracker)
10. [Credit Monitor](#10-credit-monitor)
11. [Earnings Calendar](#11-earnings-calendar)
12. [Performance Tracker](#12-performance-tracker)
13. [WhatsApp Alerts](#13-whatsapp-alerts)
14. [File Manifest](#14-file-manifest)

---

## 1. System Overview

Two Python paper-trading agents share the codebase at `./scion-omaha-bots\`. They see different parts of the market and balance each other.

| Agent | Persona | Strategy | Horizon | Portfolio Share |
| :--- | :--- | :--- | :--- | :--- |
| **Scion-Bot** (`main.py`) | Michael Burry | Swing-trade beaten-down "ick" stocks near 52W lows | Days to weeks | 30-40% |
| **Omaha-Bot** (`buffett_main.py`) | Warren Buffett | Buy quality compounders with moats, hold forever | Years to decades | 60-70% |

Plus shared infrastructure:

| Module | Purpose |
| :--- | :--- |
| `credit_monitor.py` | Bond market stress index → risk posture |
| `ta_lib.py` | 11 technical indicators for entry/exit timing |
| `smart_money.py` | Insider + institutional flow tracking |
| `earnings.py` | Earnings calendar integration |
| `performance_tracker.py` | CSV-based performance logging |
| `notify.py` | WhatsApp alert bridge |

---

## 2. The Two Agents

### 2A. Scion-Bot (Burry) — Swing Trading

**Philosophy:** Find "roadkill" — heavily shorted, hated stocks at 52W lows with strong balance sheets. Buy when pessimism peaks, sell into strength.

**Universe:** Stocks within 10-15% of 52W low, Current Ratio > 2.0, D/E < 0.5, FCF Yield > 6%.

**Position Rules:**
- Max 12-18 positions
- Max 8% per position
- Hard stop-loss at 52W low break
- Target 1: +20% → scale out 50%
- Target 2: +40% → liquidate rest
- Annual turnover 100-200%

**Files:**
| File | Purpose |
| :--- | :--- |
| `main.py` | CLI orchestrator — commands, watchlist, routing |
| `screener.py` | Market scanner — scores candidates (25+ threshold) |
| `analyzer.py` | Deep-dive — DCF + NCAV + technical levels + sentiment |
| `news_engine.py` | News catalyst scan — "ick" capitulation & reversal triggers |
| `portfolio.py` | Position tracking — stop-loss, profit targets, ATR dynamic stops |

### 2B. Omaha-Bot (Buffett) — Quality Compounding

**Philosophy:** Find wonderful businesses at fair prices. Four Filters: (1) Circle of Competence, (2) Durable Moat, (3) Honest Management, (4) Reasonable Price. Hold forever.

**Universe:** ROE > 15%, Gross Margins > 40%, D/E < 0.5, consistent earnings 5+ years.

**Position Rules:**
- Max 5-12 positions
- Max 25% per position
- No stop-losses — thesis break only
- Trim if overweight (rebalance, not exit)
- Annual turnover 5-15%

**Files:**
| File | Purpose |
| :--- | :--- |
| `buffett_main.py` | CLI orchestrator |
| `buffett_screener.py` | Quality compounder scanner (40+ threshold) |
| `buffett_analyzer.py` | Four Filters + Owner Earnings DCF |
| `buffett_news_engine.py` | Moat-threat news scanner (antitrust, competition, regulation) |
| `buffett_portfolio.py` | Long-term position tracker (no stop-losses) |

### 2C. Combined View

```
python buffett_main.py combined
```

Shows both portfolios side-by-side with total allocation:
- Omaha-Bot (hold forever): X%
- Scion-Bot (tactical swings): Y%
- Cash (strategic reserve): Z%

---

## 3. Shared Modules

### 3A. Technical Analysis — `ta_lib.py`

Pure numpy/pandas — no external TA libraries. 11 indicator functions consumed by both bots as **timing modifiers only** (±16 max for Scion, ±10 max for Buffett). Never overrides fundamentals.

**Available Functions:**

| Function | Returns | Used For |
| :--- | :--- | :--- |
| `compute_rsi(series)` | value + regime (oversold/neutral/overbought) | Entry on oversold (<30), exit on overbought (>70) |
| `compute_macd(series)` | line + signal + histogram + cross_signal | Bullish/bearish cross entries |
| `compute_sma(series, period)` | Single SMA value | Dynamic support/resistance |
| `compute_smas(series)` | Dict of SMA10/20/50/100/200 | Golden/death cross detection |
| `compute_ema(series, period)` | Single EMA value | Keltner middle line |
| `compute_bollinger(series)` | Upper/middle/lower + bandwidth + %B | Support/resistance bands |
| `compute_atr(df)` | ATR value + series | Dynamic stop-loss placement |
| `compute_keltner(df)` | Upper/middle/lower | TTM Squeeze base |
| `compute_ttm_squeeze(df)` | Squeeze on/off + bars count + histogram + color | Momentum readiness |
| `compute_volume_ratio(series)` | Ratio + regime (low/normal/high/surge) | Volume confirmation |
| `compute_all(df)` | Combined dict of everything above | Convenience wrapper |

**TTM Squeeze Colors (Carter-Fukusawa):**
- **Gray** — no squeeze
- **Lime** — squeeze fires, histogram up (first 2 bars)
- **Maroon** — squeeze fires, histogram down (first 2 bars)
- **Green** — ongoing squeeze, bullish
- **Red** — ongoing squeeze, bearish

**Integration Points:**
- Scion screener: ±16 timing modifier on score
- Buffett screener: ±10 trend quality modifier
- Both portfolios: ATR-based dynamic stop clamping
- Both premarkets: Technical Pulse section (RSI, MACD cross, squeeze status)

### 3B. Smart Money Tracker — `smart_money.py`

Tracks insider activity + institutional ownership to answer: *is smart money buying or selling?*

**Composite Score (0-100):**
- 60% Insider signal (transactions + purchases)
- 40% Institutional signal (holders adding/reducing)

**Key Functions:**

| Function | Returns | Use |
| :--- | :--- | :--- |
| `get_insider_signal(symbol)` | Net shares 6mo, buy %, signal (bullish/bearish/neutral), score -10/+10 | Insider flow direction |
| `get_institutional_signal(symbol)` | Holder count, net adding/reducing, signal, score -10/+10 | Institutional flow direction |
| `get_smart_money_score(symbol)` | Composite 0-100 + label | One-number decision signal |
| `get_smart_money_summary(symbol)` | One-liner string | Premarket pulse |

**Labels (composite score):**
- 80-100: Smart Money Accumulating
- 60-79: Mixed — Slight Accumulation
- 40-59: Neutral / No Clear Signal
- 20-39: Mixed — Slight Selling
- 0-19: Smart Money Selling Off

**Integration:** Both accept optional `ticker=` kwarg to share an existing yfinance Ticker instance across calls (avoids redundant HTTP).

### 3C. Credit Monitor — `credit_monitor.py`

Six weighted signals → Composite Credit Stress Index (0-100).

**Weights:**
| Weight | Signal | Source |
| :--- | :--- | :--- |
| 25% | Yield Curve (2s10s) | `^TNX` - SHY yield |
| 20% | 30Y Treasury Level | `^TYX` |
| 20% | HY Credit Spread | HYG yield - IEF yield |
| 15% | IG Credit Spread | LQD yield - IEF yield |
| 10% | SOFR Level | sofrrate.com scrape |
| 10% | Private Credit News | BDC tickers (KKR, ARCC, BX, etc.) |

**Scale:**
| Score | Label | Action Required |
| :--- | :--- | :--- |
| 0-20 | Benign | Normal operation |
| 20-40 | Elevated | Reduce margin; Scion max 5% per position |
| 40-60 | Stressed | Cash to 20%; pause new buys |
| 60-80 | Crisis | Cash to 35%+; exit Scion longs |
| 80-100 | Systemic | Cash to 50%+; capital preservation |

**Usage:**
```
python credit_monitor.py           # Full report → vault
python credit_monitor.py --pulse   # One-liner for premarket
```

### 3D. Earnings Calendar — `earnings.py`

Fetches earnings dates + consensus estimates via `yfinance.Ticker.calendar`.

**Key Functions:**

| Function | Returns |
| :--- | :--- |
| `get_upcoming_earnings(symbols)` | List of {symbol, date, eps_avg, rev_avg, days_away} |
| `format_earnings_brief(earnings_list)` | Formatted string for premarket |
| `format_earnings_warning(earnings_list, portfolio)` | Warning if portfolio holding reports within 14 days |
| `get_earnings_analysis(symbol)` | Single-ticker earnings data for deep-dive |

**Integration:** Both `run` commands (Step 5) and both `premarket` commands check earnings. Portfolio holdings reporting within 14 days trigger a warning.

### 3E. Performance Tracker — `performance_tracker.py`

Appends time-series data to CSVs automatically during `run` commands.

**Files Created:**
| File | Contents |
| :--- | :--- |
| `performance_log.csv` | All events: screener results, portfolio actions, cycle summaries |
| `performance_portfolio.csv` | Periodic portfolio snapshots at each cycle |

**Key Functions:**
| Function | When It's Called |
| :--- | :--- |
| `log_screener_result(agent, symbol, score, price)` | Each candidate in screener output |
| `log_portfolio_action(agent, symbol, action, price, reason)` | Stop-loss hit, target reached, position closed |
| `log_run_cycle(agent, top_symbol, top_score, pick_count)` | After each full `run` cycle |
| `snapshot_portfolio(agent, positions)` | At end of each `run` cycle |

---

## 4. CLI Quick Reference

### Scion-Bot (`python main.py`)

```
python main.py screener                # Scan for swing candidates
python main.py analyze SYMBOL          # Deep-dive (DCF + NCAV + tech)
python main.py news                    # Scan watchlist for catalysts
python main.py portfolio               # Show open positions + P&L
python main.py check                   # Check stop-losses + targets
python main.py add SYMBOL --score N    # Open a new position
python main.py premarket               # Pre-market briefing
python main.py run                     # Full cycle: check → screen → analyze → news → earnings → alert
```

### Omaha-Bot (`python buffett_main.py`)

```
python buffett_main.py screener         # Screen for quality compounders
python buffett_main.py analyze SYMBOL   # Four Filters + Owner Earnings DCF
python buffett_main.py news             # Scan for moat-threat news
python buffett_main.py portfolio        # Show long-term positions
python buffett_main.py check            # Review intrinsic values vs market
python buffett_main.py add SYMBOL       # Open a long-term position
python buffett_main.py trim SYMBOL --pct 25  # Trim overweight position
python buffett_main.py close SYMBOL     # Exit position (thesis break)
python buffett_main.py premarket        # Pre-market briefing
python buffett_main.py combined         # Unified dual-agent view
python buffett_main.py run              # Full cycle: review → screen → analyze → news → earnings → alert
```

### Global Flags (both bots)
```
--watchlist KO,PG    # Override default watchlist — must go BEFORE subcommand
--notify             # Send WhatsApp alerts
--recipient CHAT_ID  # WhatsApp recipient
```

### Credit Monitor
```
python credit_monitor.py          # Full report → vault
python credit_monitor.py --pulse  # Condensed one-liner
```

---

## 5. Daily Workflow

### Morning Routine (before open)

```powershell
# 1. Credit market pulse
python credit_monitor.py --pulse

# 2. Omaha-Bot premarket
python buffett_main.py premarket

# 3. Scion-Bot premarket
python main.py premarket

# 4. Combined allocation view
python buffett_main.py combined
```

This generates terminal output + vault files. The premarket briefs show:
- Market context (SPY, VIX, QQQ)
- Credit Stress score
- Technical Pulse (RSI, MACD, squeeze on top tickers)
- Smart Money Pulse (insider + institutional flow)
- Overnight news scan
- Screener pulse (top candidates right now)
- Earnings calendar (this week + upcoming)

### During the Day

```powershell
# Check positions
python main.py check
python buffett_main.py check

# Deep-dive a new ticker
python main.py analyze PFE
python buffett_main.py analyze KO

# News scan
python main.py news
python buffett_main.py news
```

---

## 6. Weekly Workflow

### Full Review Cycle

```powershell
# Omaha-Bot full cycle
python buffett_main.py run

# Scion-Bot full cycle
python main.py run

# Credit deep-dive
python credit_monitor.py

# Combined view
python buffett_main.py combined
```

Each `run` command:
1. Reviews open positions (stop-losses, targets, intrinsic values)
2. Runs the screener on the watchlist
3. Deep-dives the top candidate (if score >= 50 for Scion, >= 70 for Omaha)
4. Scans for news catalysts / moat threats
5. Checks earnings calendar for upcoming reports
6. Generates a consolidated summary (console + WhatsApp if `--notify`)
7. Logs performance to CSV

---

## 7. Signals & Interpretation

### When To Act

| Scenario | What To Do |
| :--- | :--- |
| Scion screener shows candidates with Score > 50 | Deep-dive (`analyze SYMBOL`) then consider adding |
| Credit Stress < 20 | Normal operation, full position sizes |
| Credit Stress 20-40 | Reduce Scion max to 5%, Omaha holds |
| Credit Stress 40-60 | Cash to 20%, pause new buys, top 5 Scion only |
| Credit Stress 60-80 | Exit all Scion longs, thesis review on Omaha |
| Credit Stress 80+ | Capital preservation mode |
| 30Y > 5.5% sustained | Full defensive posture |
| VIX > 30 | Omaha: time to deploy cash. Scion: tighten stops. |
| VIX < 15 | Both: slow down, don't chase |
| RSI > 70 on a position | Consider trimming or tighten stop |
| RSI < 30 on a candidate | Entry signal if fundamentals hold |
| MACD bullish cross + squeeze fire | Strong entry signal |
| Insider buying + institutional adding | Smart money confirms thesis |
| Insider selling + institutional reducing | Thesis challenge — re-evaluate |

### Scion Score Thresholds

| Score | Meaning |
| :--- | :--- |
| 25-40 | Weak candidate — watchlist only |
| 40-60 | Moderate — consider if thesis strong |
| 60-80 | Strong — likely add |
| 80+ | Conviction — heavy consideration for position |

### Timing Modifiers (Scion)

The screener's `analyze_technical_support()` adds a ±16 modifier to the raw score:

| Signal | Modifier |
| :--- | :--- |
| MACD bullish cross | +4 |
| RSI oversold (< 30) | +4 |
| Price near BB lower band | +2 |
| Squeeze on | +2 |
| Volume surge | +2 |
| Volume low | +2 |
| MACD bearish cross | -4 |
| RSI overbought (> 70) | -4 |
| Price near BB upper band | -2 |

### Timing Modifiers (Buffett)

The `buffett_screener.py` adds a ±10 trend quality modifier:

| Signal | Modifier |
| :--- | :--- |
| Golden cross (SMA50 > SMA200) | +5 |
| RSI pullback (30-45) | +3 |
| MACD bullish cross | +2 |
| Death cross (SMA50 < SMA200) | -5 |
| RSI froth (65+) | -3 |
| MACD bearish cross | -2 |

---

## 8. Technical Analysis (ta_lib)

### Full Indicator Set

All 11 indicators are pure numpy/pandas. No TA-Lib, no pandas-ta, no external dependencies.

```python
from ta_lib import compute_all, compute_ttm_squeeze, compute_atr
import yfinance as yf

df = yf.Ticker("AAPL").history(period="6mo")
ta = compute_all(df)

print(ta["rsi"]["value"])           # RSI value
print(ta["rsi"]["regime"])          # oversold / neutral / overbought
print(ta["macd"]["cross_signal"])   # bullish / bearish / None
print(ta["squeeze"]["squeeze_on"]) # True / False
print(ta["squeeze"]["histogram_color"])  # lime / maroon / green / red / gray
```

### ATR Dynamic Stops

The portfolio module uses ATR to clamp stop-losses:

```python
from ta_lib import compute_atr

atr = compute_atr(df)["value"]
# Stop clamped below (entry - 2 * ATR) AND below current price
# So the stop can only move up, never down
```

### TTM Squeeze

The Carter-Fukusawa TTM Squeeze is the most sophisticated signal. It measures:
1. Bollinger Bands contracting inside Keltner Channels → volatility squeeze
2. Linear regression of high/low over the period → histogram direction
3. Color coding: first 2 bars of squeeze use lime/maroon, subsequent use green/red

A squeeze firing (lime or maroon bar) after a period of compression often predicts an explosive move.

---

## 9. Smart Money Tracker

### Insider + Institutional Flow

```python
from smart_money import get_smart_money_score, get_smart_money_summary

# One number (0-100)
sm = get_smart_money_score("AAPL")
print(sm["composite_score"])  # e.g. 72
print(sm["label"])           # e.g. "Mixed - Slight Accumulation"

# One-liner for premarket
print(get_smart_money_summary("AAPL"))
# "Insiders bullish (net +12,345) | 15 holders, 8 adding / 3 reducing (score: 72/100)"
```

### Passing Existing Ticker Object

Both bots share a yfinance Ticker across multiple calls to avoid redundant HTTP requests:

```python
ticker = yf.Ticker("AAPL")
# Use the same ticker for both calls
insider = get_insider_signal("AAPL", ticker=ticker)
inst = get_institutional_signal("AAPL", ticker=ticker)
```

---

## 10. Credit Monitor

### Quick Pulse

```powershell
python credit_monitor.py --pulse
# Output: CREDIT STRESS: 34/100 - Elevated | Caution warranted | 10Y=4.30% | 30Y=5.04% | 2s10s=-0.18% (INV) | HY=320bps | IG=115bps | SOFR=4.33%
```

### Full Report

```powershell
python credit_monitor.py
```

Generates a full report with all six sub-scores, historical context, and saves to:
`Stock Research/Credit Monitor/YYYY-MM-DD Credit Report.md`

### Interpreting Private Credit News

The monitor scans BDC tickers (KKR, ARCC, FSK, BX, OBDC, MAIN) for:

| Keyword Category | Examples |
| :--- | :--- |
| PIK red flags | "payment in kind", "PIK toggle", "capitalized interest" |
| Default signals | "default", "non-accrual", "distressed", "restructuring" |
| BDC warnings | "maturity wall", "cov-lite", "private credit" |
| Systemic | "credit crunch", "liquidity crisis", "margin call", "contagion" |

---

## 11. Earnings Calendar

### Integration Points

The earnings module runs automatically inside:
- `run` command (both bots) — Step 5
- `premarket` command (both bots) — Upcoming earnings section

### Manual Usage

```python
from earnings import get_upcoming_earnings, format_earnings_brief

earnings = get_upcoming_earnings(["AAPL", "MSFT", "KO"])
print(format_earnings_brief(earnings))
```

### Portfolio Warnings

If a position you hold reports within the next 14 days, a warning is generated:

```
WARNING — portfolio holdings reporting soon:
  AAPL reports in 3 days
  KO reports in 8 days
```

---

## 12. Performance Tracker

### CSV Logging

The `performance_tracker.py` module appends to two CSV files automatically:

**performance_log.csv** — every screener result, portfolio action, and cycle summary.

```
timestamp,agent,event_type,symbol,score,price,action,reason,extra_json
```

**performance_portfolio.csv** — periodic snapshots of all open positions.

```
timestamp,agent,symbol,shares,cost_basis,current_price,unrealized_pnl_pct,position_pct
```

### Analyzing Performance

Import into any analysis tool (Excel, Python, R) to answer:
- Which screener picks actually moved?
- What's the win rate on +20% targets?
- Which stop-losses were hit vs which held?
- How does the composite portfolio perform over time?

---

## 13. WhatsApp Alerts

### Setup

Both agents send WhatsApp alerts via `zappy-mcp`. Configure the MCP separately.

### Usage

```powershell
python main.py --notify --recipient "CHAT_ID" run
python buffett_main.py --notify --recipient "CHAT_ID" run
```

### What Gets Sent

| Event | Content |
| :--- | :--- |
| Premarket (Scion) | SPY, VIX, candidate count |
| Screener results (both) | Top candidates with scores |
| Run cycle (both) | Position summary, top picks, warnings |
| Portfolio action (both) | Stop-loss hit, target reached, position closed |
| News catalyst (Scion) | Ick capitulation / reversal trigger |
| Moat threat (Omaha) | Thesis-breaking news alert |

---

## 14. File Manifest

### Core Agent Files

| File | Agent | Purpose |
| :--- | :--- | :--- |
| `main.py` | Scion | CLI orchestrator |
| `buffett_main.py` | Omaha | CLI orchestrator |

### Screening / Scanning

| File | Agent | Purpose |
| :--- | :--- | :--- |
| `screener.py` | Scion | Finds beaten-down stocks near 52W lows |
| `buffett_screener.py` | Omaha | Finds quality compounders (ROE, margins, moats) |

### Analysis

| File | Agent | Purpose |
| :--- | :--- | :--- |
| `analyzer.py` | Scion | DCF + NCAV + technical levels + sentiment |
| `buffett_analyzer.py` | Omaha | Four Filters + Owner Earnings DCF |

### News Monitoring

| File | Agent | Keywords Tracked |
| :--- | :--- | :--- |
| `news_engine.py` | Scion | ICK (miss, plunge, downgrade) + REVERSAL (buyback, upgrade, beat) |
| `buffett_news_engine.py` | Omaha | MOAT_THREAT (antitrust, competition) + MANAGEMENT + REGULATORY + THESIS_BREAKING |

### Portfolio Tracking

| File | Agent | Features |
| :--- | :--- | :--- |
| `portfolio.py` | Scion | Stop-loss at 52W low, profit targets at +20%/+40%, ATR dynamic stops |
| `buffett_portfolio.py` | Omaha | No stop-losses, trim/close commands, intrinsic value tracking |

### Shared Modules

| File | Purpose | Key Functions |
| :--- | :--- | :--- |
| `ta_lib.py` | 11 technical indicators | `compute_all()`, `compute_ttm_squeeze()`, `compute_atr()` |
| `smart_money.py` | Insider + institutional tracking | `get_smart_money_score()`, `get_smart_money_summary()` |
| `credit_monitor.py` | Credit stress index (0-100) | `generate_report()`, `quick_pulse()` |
| `earnings.py` | Earnings calendar | `get_upcoming_earnings()`, `format_earnings_brief()` |
| `performance_tracker.py` | CSV performance logging | `log_run_cycle()`, `snapshot_portfolio()` |
| `notify.py` | WhatsApp bridge | `send_alert()` |

### State Files (JSON, auto-generated)

| File | Agent | Contents |
| :--- | :--- | :--- |
| `portfolio.json` | Scion | Open positions, cost basis, stop-loss, targets |
| `buffett_portfolio.json` | Omaha | Long-term positions, cost basis, intrinsic value |
| `news_state.json` | Scion | Seen article titles (dedup) |
| `buffett_news_state.json` | Omaha | Seen moat-news titles (dedup) |
| `credit_state.json` | Both | Seen private credit headlines |

### Performance Data (CSV, auto-generated)

| File | Contents |
| :--- | :--- |
| `performance_log.csv` | All events: screener results, actions, cycle summaries |
| `performance_portfolio.csv` | Periodic portfolio snapshots |

### Agent Profiles

| File | Purpose |
| :--- | :--- |
| `frameworks/agents/Scion-Bot Agent Profile.md` | Michael Burry persona — swing trading ruleset |
| `frameworks/agents/Omaha-Bot Agent Profile.md` | Warren Buffett persona — quality compounding ruleset |

---

## Quick Start for New Users

If you're sitting down fresh and want to understand the market in 10 minutes:

```powershell
# Step 1: Credit health check
python ./scion-omaha-bots\credit_monitor.py --pulse

# Step 2: Market pulse (Omaha-Bot premarket)
python ./scion-omaha-bots\buffett_main.py premarket

# Step 3: Swing candidates (Scion-Bot premarket)
python ./scion-omaha-bots\main.py premarket

# Step 4: Combined portfolio
python ./scion-omaha-bots\buffett_main.py combined
```

Then deep-dive anything interesting:
```powershell
python ./scion-omaha-bots\main.py analyze PFE
python ./scion-omaha-bots\buffett_main.py analyze KO
```

---
*Generated 2026-07-07. See 00-INDEX for the rest of the System Guide.*
