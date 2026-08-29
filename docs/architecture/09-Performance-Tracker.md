---
title: "Performance Tracker & Feedback Loop"
date: 2026-07-08
tags:
  - docs
  - tracker
  - performance
---

# Performance Tracker & Feedback Loop

Three modules that log, report, and auto-improve strategy rules.

## Architecture

```
tracker.py  ──► trades.csv + daily_pnl.csv  ──► report_card.py ──► vault report
     │                                                │
     ▼                                                ▼
 open_positions.json                          feedback.py ──► vault report + rule changes
```

All three can be called through either agent's CLI or run standalone.

## Tracker (`tracker.py`)

Logs every entry and exit, snapshots open positions daily, persists to CSV.

### State Files

| File | Format | Purpose |
| :--- | :--- | :--- |
| `open_positions.json` | JSON | Active positions — source of truth for open state |
| `trades.csv` | CSV | Closed trades history — used by report_card and feedback |
| `daily_pnl.csv` | CSV | Daily P&L snapshots — for equity curve tracking |

### Standalone Usage

```
python tracker.py backfill       # Batch-load initial 12 positions
python tracker.py snapshot       # Log today's P&L for all open positions
python tracker.py status         # Table: ticker, entry, price, P&L%, days held, stop/target distance
python tracker.py trades         # Show all closed trades
```

### CLI Integration (both bots)

```
python main.py tracker                          # Same as tracker.py status
python main.py log-entry AAPL --entry 200 ...   # Log a new trade
python main.py log-exit AAPL --exit 215...      # Close a trade
```

### `log-entry` Options

| Flag | Required | Description |
| :--- | :--- | :--- |
| `symbol` | Yes | Ticker |
| `--entry` | Yes | Entry price |
| `--stop` | No | Stop-loss price |
| `--t1` | No | Target 1 price |
| `--t2` | No | Target 2 price |
| `--score` | No | Scion/Buffett score (0-100) |
| `--thesis` | No | Thesis summary string |

### `log-exit` Options

| Flag | Required | Description |
| :--- | :--- | :--- |
| `symbol` | Yes | Ticker |
| `--exit` | No | Exit price (defaults to current market price) |
| `--reason` | No | `stop_loss`, `target`, `manual`, `thesis_break`, etc. |

## Report Card (`report_card.py`)

Reads the tracker CSVs and writes a performance dashboard to vault.

### Usage

```
python report_card.py                    # Full report
python report_card.py --bot scion        # Filter by bot
python main.py report                    # Same via CLI
python buffett_main.py report --bot omaha
```

### Report Sections

1. **Summary stats**: win rate, total P&L, avg R:R, avg hold time
2. **Score bucket analysis**: win rate by score range (70+, 50-69, etc.)
3. **Best/worst trades**
4. **Sector performance**
5. **Open positions snapshot**
6. **Recommendations**: derived from win-rate by score bucket

### Output

Saved to `Stock Research/Performance/YYYY-MM-DD Performance Report.md`

## Feedback Loop (`feedback.py`)

Runs strategy rules against closed trade data and recommends parameter changes.

### Rules

| Rule | Trigger | Action |
| :--- | :--- | :--- |
| **TARGET_LOWER** | < 50% of closed trades hit T1 | Proposes lowering next T1 by 5% |
| **STOP_WIDTH** | Avg stop distance on winners > 12% | Proposes tightening stops on next entries |
| **POSITION_CAP** | Max drawdown exceeds cap × 1.2 | Proposes reducing position cap in portfolio config |
| **REGIME_PAUSE** | Win rate < 20% in current regime | Proposes pausing the affected bot |
| **SECTOR_AVOID** | 2+ losers in same sector | Adds sector to avoid list |
| **OMAHA_PULLBACK** | 2+ closed losers with entry > 50MA | Proposes requiring 10% pullback from 50MA before entry |
| **THESIS_CAP** | Any closed trade < -6% (loss cap breach) | Flags thesis-break discipline breach for review |

### Usage

```
python feedback.py                          # Interactive mode — prompts before applying
python feedback.py --no-interactive         # Auto-apply (writes vault report but skips prompts)
python main.py feedback                     # Via Scion CLI
python buffett_main.py feedback             # Via Omaha CLI
```

### Interactive Workflow

```
$ python feedback.py

  [feedback] Analyzing 8 closed trades...
  [TARGET_LOWER] Only 4/8 (50%) trades hit T1.
    → Current T1: +20%
    → Proposed: +15%
  Apply? (y/n): y
    ✓ portfolio.py: target_pct changed from 0.20 to 0.15

  [STOP_WIDTH] No issue found (avg stop distance: 7.2%)
  [POSITION_CAP] No drawdown data yet.
  [SECTOR_AVOID] No issue found.
  [OMAHA_PULLBACK] No issue found.
```

### Output

Each run saves a report to `Stock Research/Performance/YYYY-MM-DD Feedback Report.md`
tracking which rules flagged, whether applied, and the before/after values.

### Alpha Tracking (`report_card.py`)

Each closed trade is benchmarked against SPY (same holding period). `compute_alpha_for_trade()` returns the difference between trade return and SPY total return. The performance report now includes:

- **Alpha column** in closed trades table
- **Cumulative alpha** summary line at the bottom

### Portfolio VaR Guard (`portfolio.py`)

The `open_position()` function checks `_portfolio_drawdown_at_stops()` before accepting a new position. If the total drawdown at all stop-losses exceeds `max_drawdown_pct=0.15` (15% of portfolio), the position is rejected. This prevents over-concentration of risk.

### Thesis-Break Loss Cap (`portfolio.py`)

`check_position()` enforces a hard loss cap (`thesis_break_cap_pct`, default 0.06) in addition to the configured stop. Any position at or below -6% from entry is closed with reason `THESIS-BREAK CAP` regardless of stop width — stops stay as-is; the cap is the thesis-break discipline (decision 2026-08-05). `daily_check.py` flags the -5% review zone; `feedback.py`'s `THESIS_CAP` rule audits closed trades for cap breaches.

### Decision Reflection Log (`reflection.py`)

Every closed trade auto-creates a structured reflection via `tracker.log_exit()`. Reflections include:

- **Lesson text** (auto-generated from trade data — entry/exit prices, hold time, reason)
- **Alpha** (vs SPY)
- **Entry/exit prices, reason, days held**

Reflections are persisted in `reflection_log.json` and injected into `screener.py` / `buffett_screener.py` at the start of each `run_screener()` run, providing recent-decision context to the screening process.

## Debate Engine (`debate.py`)

Bull/Bear/Judge subagent framework that debates a ticker's prospects. See 11-Debate-Engine for full documentation.

### Score Integration

The Judge's debate score (0-100) is mapped via `score_modifier()` to a -20 to +20 modifier on the base score.

### Display (`daily_check.py`)

The position table shows both the base Score and the Debate-adjusted score:

```
| Ticker | Score | Debate |
| :--- | :--- | :--- |
| AAPL | 75 | 75+2→77 |
| KO | 60 | 60-3→57 |
```

The terminal quick-view also shows `DebateMod` as a signed integer.

## Daily Check (`daily_check.py`)

Position monitor that logs a snapshot, fetches live prices, compares to stops/targets, generates alerts, displays debate score modifiers, and writes a vault brief.

```
python daily_check.py                    # Standalone
python main.py daily-check               # Via CLI
python buffett_main.py daily-check       # Via Omaha CLI
```

### Alert Zones

- ⚠ **Stop is near**: price within 3% of stop-loss
- 🎯 **Target within reach**: price within 3% of T1
- 🔴 **Thesis-break review**: position down ≥ 5% — close now if thesis broke; hard exit cap is -6% (rule 2026-08-05, see 2026-08-05 Stop Discipline Decision)

### Output

- Snapshot logged to `daily_pnl.csv`
- Brief saved to `Stock Research/Daily Briefs/YYYY-MM-DD Position Check.md`
- Terminal table with P&L%, days held, stop/target distance, debate modifier

## Data Flow Summary

```
Entry ──► tracker.log_entry() ──► open_positions.json
   │
   ├──► tracker.log_daily_snapshot() ──► daily_pnl.csv
   │
   └──► tracker.log_exit() ──► trades.csv
            │                        │
            ▼                        ├──► report_card.py (alpha vs SPY)
      reflection.py                  │
      (auto-lesson + alpha)          └──► feedback.py
            │
            ▼
      reflection_log.json
      (read by screener for context)

Portfolio:
  open_position() ──► _portfolio_drawdown_at_stops() ──► reject if > 15%

Debate:
  debate.py ──► debate_scores.json ──► daily_check.py (modifier display)
```
