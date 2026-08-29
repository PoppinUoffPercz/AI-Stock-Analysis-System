---
title: "CLI Reference"
date: 2026-07-07
tags:
  - docs
  - cli
---

# CLI Reference

## Scion-Bot (`python main.py`)

| Command | Description |
| :--- | :--- |
| `screener` | Scan for swing candidates near 52W lows |
| `analyze SYMBOL` | Deep-dive (DCF + NCAV + technical) |
| `news` | Scan watchlist for ick/reversal catalysts |
| `portfolio` | Show open positions + P&L |
| `check` | Check stop-losses and profit targets |
| `add SYMBOL --score N` | Open a new position |
| `premarket` | Pre-market briefing with credit snapshot |
| `debate SYMBOL` | Run Bull/Bear/Judge debate (full flow: prep → wait → compile) |
| `debate SYMBOL --compile` | Compile pre-existing agent files into vault report |
| `run` | Full cycle: portfolio → screener → analyze top pick → generate report |

**Global flags:**
| Flag | Description |
| :--- | :--- |
| `--watchlist AAPL,MSFT` | Override default watchlist (goes BEFORE subcommand) |
| `--notify` | Send WhatsApp alerts |
| `--recipient CHAT_ID` | WhatsApp recipient |

## Omaha-Bot (`python buffett_main.py`)

| Command | Description |
| :--- | :--- |
| `screener` | Screen for quality compounders (Buffett filters) |
| `analyze SYMBOL` | Four Filters + Owner Earnings DCF |
| `news` | Scan for moat-threat news |
| `portfolio` | Show long-term positions |
| `check` | Review intrinsic values vs market |
| `add SYMBOL` | Open a long-term position |
| `trim SYMBOL --pct 25` | Trim an overweight position |
| `close SYMBOL` | Exit (thesis broken) |
| `premarket` | Pre-market briefing with credit + moat news |
| `combined` | Unified dual-agent portfolio view |
| `debate SYMBOL` | Run Bull/Bear/Judge debate (full flow: prep → wait → compile) |
| `debate SYMBOL --compile` | Compile pre-existing agent files into vault report |
| `run` | Full cycle: portfolio → screener → deep-dive → moat news → summary |

### Tracking Commands (both bots)

| Command | Description |
| :--- | :--- |
| `log-entry SYMBOL --entry N --stop N --t1 N --t2 N --score N` | Log a trade to the tracker |
| `log-exit SYMBOL --exit N --reason stop_loss` | Close a trade in the tracker |
| `report` | Generate performance report → vault |
| `feedback` | Run strategy feedback loop (interactive) |
| `daily-check` | Position monitor: snapshot + alerts + vault brief |
| `tracker` | Table of all open positions with P&L/distances |

### log-entry Options

```
python main.py log-entry AAPL --entry 200 --stop 185 --t1 240 --t2 280 --score 75 --thesis "AI tailwind"
```

| Flag | Description |
| :--- | :--- |
| `--entry` | Entry price (required) |
| `--stop` | Stop-loss price |
| `--t1` | Target 1 price |
| `--t2` | Target 2 price |
| `--score` | Scion/Buffett score (0-100) |
| `--thesis` | Thesis summary |

### log-exit Options

```
python main.py log-exit AAPL --exit 235 --reason target
```

| Flag | Description |
| :--- | :--- |
| `--exit` | Exit price (defaults to live market price) |
| `--reason` | `stop_loss`, `target`, `manual`, `thesis_break` |

### Standalone Tracker Usage

```
python tracker.py backfill       # Batch-load initial positions
python tracker.py snapshot       # Daily P&L snapshot
python tracker.py status         # Open positions table
python tracker.py trades         # Closed trade history
```

## Credit Monitor (`python credit_monitor.py`)

| Command | Description |
| :--- | :--- |
| *(no subcommand)* | Full credit market report → vault |
| `--pulse` | Condensed one-liner for premarket embedding |

## OpenBB MCP (`opencode.jsonc` integration)

| Config Key | Description |
| :--- | :--- |
| `mcp.openbb` | OpenBB local MCP server in `~/.config/opencode/opencode.jsonc` |
| `--default-categories equity,news` | Active tool categories (lean context) |
| `--tool-discovery` | Agent can activate more categories on demand |

See 10-OpenBB-Integration for full details.

## File Paths (all relative to `~/scion-bot/`)

All should be run from `./scion-omaha-bots\`. The `--watchlist` flag is a **global argument** on both `main.py` and `buffett_main.py` — it must come before the subcommand:

```
# CORRECT:
python main.py --watchlist LULU,PFE premarket
python buffett_main.py --watchlist KO,PG run

# WRONG:
python main.py premarket --watchlist LULU,PFE
```

## Typical Daily Run

```
# Quick market pulse
python credit_monitor.py --pulse

# Omaha-Bot full review
python buffett_main.py --watchlist KO,PG run

# Scion-Bot full review
python main.py --watchlist LULU,PFE run

# Combined view
python buffett_main.py combined
```
