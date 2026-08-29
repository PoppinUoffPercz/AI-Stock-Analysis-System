---
title: "Debate Engine"
date: 2026-07-08
tags:
  - docs
  - debate
---

# Debate Engine

Bull/Bear/Judge subagent framework that debates a ticker's prospects and produces a score modifier (-20 to +20) for position scoring.

## Architecture

```
debate.py ──► fetch_debate_data() ──► debate_data_{TICKER}.json
     │
     ├──► Bull subagent ──► debate_bull_{TICKER}.md
     ├──► Bear subagent ──► debate_bear_{TICKER}.md
     └──► Judge subagent ──► debate_judge_{TICKER}.md
                                   │
                           compile_report()
                                   │
                                   ▼
        Stock Research/Debates/YYYY-MM-DD {TICKER} Debate.md
                                   │
                                   ▼
                         debate_scores.json ◄── score_modifier()
```

## Concepts

| Concept | Description |
| :--- | :--- |
| **Bull** | Argues the buy case — undervalued assets, growth catalysts, competitive advantages |
| **Bear** | Argues the sell case — overvaluation, deterioration, ignored risks |
| **Judge** | Reads both arguments, finds flaws in each, writes balanced consensus with 0-100 score |
| **Debate Score** | 0-100 from Judge. 50 = neutral, 100 = max bullish, 0 = max bearish |
| **Score Modifier** | Mapped via `score_modifier()`: -20 to +20, applied to base screener score |
| **Consensus** | Buy / Overweight / Hold / Underweight / Sell |

## Usage

### Full flow (prep + subagent dispatch + compile)

```
python debate.py debate AAPL
# 1. Fetches data, prints prompts
# 2. Dispatch 3 subagents to write debate files
# 3. Run: python debate.py compile AAPL
```

### Step by step

```
# Step 1: fetch data + print agent prompts
python debate.py prepare AAPL

# Step 2: dispatch subagents externally — each writes a file:
#   debate_bull_AAPL.md
#   debate_bear_AAPL.md
#   debate_judge_AAPL.md

# Step 3: compile report and clean up agent files
python debate.py compile AAPL
```

### CLI integration

```
python main.py debate AAPL          # Scion-Bot debate command
python buffett_main.py debate AAPL  # Omaha-Bot debate command
```

## Data Pipeline

Debates use **pre-fetched data only** — subagents never compute math or fetch live data. The pipeline pulls from existing modules:

| Data Source | Module |
| :--- | :--- |
| Price & 52W range | yfinance |
| RSI, MACD, SMA, ATR | `ta_lib.py` |
| Fundamentals (P/E, ROE, margins, D/E, etc.) | yfinance `info` |
| Smart Money score | `smart_money.py` |
| Headlines | yfinance `news` |

## Files

| File | Purpose |
| :--- | :--- |
| `debate.py` | Engine — data fetcher, prompt builder, report compiler, score persistence |
| `debate_scores.json` | Stored scores keyed by ticker, read by `daily_check.py` |
| `Stock Research/Debates/` | Compiled vault reports |

## Score Integration

The debate modifier flows into position scoring through `daily_check.py`:

```
Ticker  Entry  Current  P&L%  Days  Stop  Dist%  T1  Dist%  Score  Debate
AAPL    $200   $215    +7.5%  12d   $185  +16%   $240  -10%   75     75+2→77
```

The quick-view terminal output also shows the modifier.