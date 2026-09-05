---
title: "Dual-Agent Trading System"
date: 2026-07-07
tags:
  - docs
  - architecture
---

# Dual-Agent Trading System

Two Python agents sharing the same codebase at `./scion-omaha-bots\`, designed to complement each other.

The canonical entry point is `stock-analysis`. The historical bot scripts remain
compatibility entry points.

```text
stock-analysis scion --watchlist LULU,PFE screener
stock-analysis omaha --watchlist KO,PG run
stock-analysis portfolio combined
```

## Architecture Philosophy

```
scion-bot/
├── main.py              # Scion-Bot orchestrator (Burry)
├── buffett_main.py      # Omaha-Bot orchestrator (Buffett)
│
├── screener.py          # Scion: finds beaten-down stocks
├── buffett_screener.py  # Omaha: finds quality compounders
│
├── analyzer.py          # Scion: DCF + NCAV deep-dive
├── buffett_analyzer.py  # Omaha: Four Filters + Owner Earnings
│
├── news_engine.py       # Scion: news catalyst scanner (ick/reversal)
├── buffett_news_engine.py # Omaha: moat-threat scanner
│
├── portfolio.py         # Scion: position tracking (stop-losses/targets)
├── buffett_portfolio.py # Omaha: position tracking (no stop-losses)
│
├── credit_monitor.py    # Shared: credit market stress tracker
├── notify.py            # Shared: WhatsApp bridge
│
└── .opencode/skills/    # Agent skill definitions
    └── credit-monitor/  # Credit analysis skill
```

## Why Two Agents?

They see different opportunities and balance each other:

| Dimension | Scion-Bot | Omaha-Bot |
| :--- | :--- | :--- |
| **Inspiration** | Michael Burry | Warren Buffett |
| **Horizon** | Days to weeks | Years to decades |
| **Universe** | Stocks near 52W low, hated, distressed | Quality moats, predictable earnings |
| **Entry** | Price near 52W low + support holds | Fair price for wonderful business |
| **Exit** | +20% scale, +40% full | Never (unless thesis breaks) |
| **Max Position** | 8% of portfolio | 25% of portfolio |
| **Positions Held** | 12-18 | 5-12 |
| **Stop-Loss** | Hard stop on 52W low break | None — thesis break only |
| **Annual Turnover** | 100-200% | 5-15% |
| **Portfolio Share** | 30-40% | 60-70% |

## Cash Management

Cash is a strategic asset. Combined view via:
```
stock-analysis portfolio combined
```

This reads both `buffett_portfolio.json` and `portfolio.json` and shows the unified allocation.
Use `python buffett_main.py combined` as the compatibility form.

## Commissioning Note

For any new feature or bot, follow the established pattern:
1. One Python module per concern (screener, analyzer, news, portfolio)
2. One orchestrator `main.py` that ties them together
3. Add CLI subcommand in the orchestrator
4. Add help text that matches the existing style
5. Tag vault output with date and agent name

## State Files

All state is local JSON. These are NOT gitignored — treat them as the source of truth.

| File | Agent | Purpose |
| :--- | :--- | :--- |
| `portfolio.json` | Scion | Open positions, cost basis, stop-losses |
| `buffett_portfolio.json` | Omaha | Long-term positions |
| `news_state.json` | Scion | Seen article titles (dedup) |
| `buffett_news_state.json` | Omaha | Seen moat-news titles (dedup) |
| `credit_state.json` | Both | Seen private credit alerts |
