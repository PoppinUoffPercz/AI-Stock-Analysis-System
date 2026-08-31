---
title: "File Manifest"
date: 2026-07-07
tags:
  - docs
  - manifest
---

# File Manifest

Every file in `./scion-omaha-bots\` and what it does.

## Core Agent Files

| File | Agent | Purpose | Key Functions |
| :--- | :--- | :--- | :--- |
| `main.py` | Scion | CLI orchestrator. Routes commands, loads watchlist, calls modules. | `cmd_screener`, `cmd_analyze`, `cmd_news`, `cmd_premarket`, `cmd_run` |
| `buffett_main.py` | Omaha | CLI orchestrator. Same pattern as main.py. | `cmd_screener`, `cmd_analyze`, `cmd_news`, `cmd_premarket`, `cmd_combined`, `cmd_run` |

## Screening / Scanning

| File | Agent | Purpose | Key Classes/Functions |
| :--- | :--- | :--- | :--- |
| `screener.py` | Scion | Finds stocks near 52W lows with strong balance sheets. | `ScionScreener.run_screener()` |
| `buffett_screener.py` | Omaha | Finds quality compounders (ROE > 15%, moats, FCF yield). | `BuffettScreener.run_screener()` |

## Analysis

| File | Agent | Purpose |
| :--- | :--- | :--- | :--- |
| `analyzer.py` | Scion | DCF valuation, NCAV (net current asset value), technical levels, sentiment check. |
| `buffett_analyzer.py` | Omaha | Buffett's Four Filters (moat, ROE, margins, value), Owner Earnings DCF. |

## News Monitoring

| File | Agent | Keywords Tracked | Classes |
| :--- | :--- | :--- | :--- |
| `news_engine.py` | Scion | ICK: miss, plunge, downgrade, crisis, lawsuit, crash, bankruptcy. REVERSAL: buyback, insider purchase, upgrade, beat, contract, approval. | `NewsEngine` — scan_watchlist(), get_new_news(), generate_alert_text() |
| `buffett_news_engine.py` | Omaha | MOAT_THREAT: antitrust, competition, market share loss. MANAGEMENT: CEO departures, accounting issues. REGULATORY: SEC, investigation, lawsuit. THESIS_BREAKING: moat destroyed. | `BuffettNewsEngine` — same interface. |

## Portfolio Tracking

| File | Agent | Features |
| :--- | :--- | :--- |
| `portfolio.py` | Scion | Add/remove positions, stop-loss at 52W low, profit targets at +20%/+40%, check command. |
| `buffett_portfolio.py` | Omaha | Add/remove positions, trim overweight, no stop-losses, intrinsic value tracking. |

## Debate Engine

| File | Purpose | Key Functions |
| :--- | :--- | :--- |
| `debate.py` | Bull/Bear/Judge debate framework. Fetches data, prints subagent prompts, compiles vault report, persists scores. | `fetch_debate_data()`, `compile_report()`, `score_modifier()`, `cmd_prepare()`, `cmd_compile()`, `cmd_debate()` |
| `debate_scores.json` | Stored debate scores keyed by ticker — read by `daily_check.py` for score modifier display |

## Performance Tracking & Feedback Loop

| File | Purpose | Key Functions |
| :--- | :--- | :--- |
| `tracker.py` | Trade logger. Entry/exit logging, daily snapshots, CSV persistence, backfill helper. | `Tracker.log_entry()`, `Tracker.log_exit()`, `Tracker.log_daily_snapshot()`, `Tracker.get_open_positions_summary()`, `backfill_current_positions()` |
| `report_card.py` | Performance dashboard. Reads tracker CSVs, computes win rate, R:R, score buckets, sector perf → vault markdown. Also computes alpha vs SPY benchmark. | `cmd_report()`, `compute_alpha_for_trade()` |
| `feedback.py` | Strategy rule engine. Runs 6 checks against closed trades, interactive approval before modifying portfolio configs. | `cmd_feedback()` — interactive prompts for TARGET_LOWER, STOP_WIDTH, POSITION_CAP, REGIME_PAUSE, SECTOR_AVOID, OMAHA_PULLBACK |
| `daily_check.py` | Position monitor. Fetches live prices, logs snapshot, checks alert zones, displays debate score modifier, writes vault brief. | `cmd_check()`, `generate_daily_brief()` |
| `reflection.py` | Decision reflection log. Auto-generates structured reflections on trade exit, formats context for screener pre-run. | `ReflectionLog` — `load()`, `save()`, `append()`, `format_for_screener()` |
| `reflection_log.json` | Stored trade reflections — auto-appended on every `log_exit()` |

## Shared / Cross-Cutting

| File | Purpose |
| :--- | :--- |
| `credit_monitor.py` | Credit market stress index. Six signals → composite 0-100. |
| `notify.py` | WhatsApp alert bridge (via `zappy-mcp`). |

## State Files (JSON, auto-generated)

| File | Agent | Contents |
| :--- | :--- | :--- |
| `portfolio.json` | Scion | Open positions: symbol, shares, cost basis, stop-loss, targets |
| `buffett_portfolio.json` | Omaha | Long-term positions: symbol, shares, cost basis, intrinsic value |
| `news_state.json` | Scion | Seen article titles by symbol (prevents duplicate alerts) |
| `buffett_news_state.json` | Omaha | Seen moat-news titles by symbol |
| `credit_state.json` | Both | Seen private credit headlines |
| `open_positions.json` | Tracker | Entry/exit tracker source of truth — tickers, prices, scores, status |
| `trades.csv` | Tracker | Closed trades log — used by report_card.py and feedback.py |
| `daily_pnl.csv` | Tracker | Daily P&L snapshots — equity curve tracking |
| `debate_scores.json` | Debate | Stored debate scores per ticker — read by daily_check.py for modifier |

## Skill Definitions

| Path | Purpose |
| :--- | :--- |
| `.opencode/skills/credit-monitor/SKILL.md` | Teaches the opencode agent how to interpret credit signals and adjust risk posture. |

## Agent Profiles

| File | Purpose |
| :--- | :--- |
| `frameworks/agents/Scion-Bot Agent Profile.md` | Michael Burry persona: swing trading rules, "ick" philosophy, conviction sizing. |
| `frameworks/agents/Omaha-Bot Agent Profile.md` | Warren Buffett persona: quality compounding, circle of competence, moat focus. |

## Support Files

| File | Purpose |
| :--- | :--- |
| `requirements.txt` | Python dependencies: yfinance, pandas, numpy, tabulate, websockets, openbb, openbb-mcp-server |
| `README.md` | Old README — less comprehensive than this System Guide |
| `anchored_context_summary.md` | (in vault Summaries/) — session state tracking |
