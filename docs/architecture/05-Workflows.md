---
title: "Daily Workflows"
date: 2026-07-07
tags:
  - docs
  - workflows
---

# Daily Workflows

## Morning Routine (before open)

```
# 1. Credit market pulse
python credit_monitor.py --pulse

# 2. Omaha-Bot premarket (quality compounder scan)
python buffett_main.py --watchlist KO,PG premarket

# 3. Scion-Bot premarket (swing trade scan)
python main.py --watchlist LULU,PFE premarket

# 4. Combined allocation view
python buffett_main.py combined
```

This generates four outputs (one terminal + three vault files). Skim the premarket briefs before the open.

## Full Review Cycle (weekly)

```
# Omaha-Bot full cycle
python buffett_main.py --watchlist KO,PG run

# Scion-Bot full cycle
python main.py --watchlist LULU,PFE run
```

Each `run` command:
1. Reviews open positions (stop-losses, targets, intrinsic values)
2. Runs the screener on the watchlist
3. Deep-dives the top candidate
4. Scans for news catalysts / moat threats
5. Generates a consolidated summary

## Credit Deep-Dive (weekly or on market stress)

```
python credit_monitor.py
```

Reads the saved report from `Stock Research/Credit Monitor/`.

## Daily Position Check (post-close)

```
# Log today's P&L snapshot and check stops/targets
python daily_check.py
```

Generates:
- Snapshot appended to `daily_pnl.csv` (for equity curve tracking)
- Alert if any position is within 3% of stop or target
- Vault brief at `Stock Research/Daily Briefs/YYYY-MM-DD Position Check.md`

## Performance Review (weekly)

```
# Generate performance dashboard
python report_card.py

# Run feedback loop (interactive — prompts before applying changes)
python feedback.py
```

Both write to `Stock Research/Performance/`. The feedback report also shows whether rules were applied or skipped.

## End-of-Month

1. Review closed trades: `python tracker.py trades`
2. Run performance report: `python report_card.py`
3. Run feedback loop: `python feedback.py`
4. Check if any rules were auto-applied (review portfolio configs)

## When To Run What

| Situation | Run This |
| :--- | :--- |
| Normal day, before open | `premarket` on both bots |
| Post-close check | `daily-check` on either bot |
| Weekly review | `run` on both bots |
| Weekly performance | `report` + `feedback` |
| Portfolio check | `portfolio` on either bot |
| Credit stress rising | `credit_monitor.py` |
| Combined view | `combined` on Omaha-Bot |
| New ticker interest | `analyze SYMBOL` on relevant bot |
| Thesis break fear | `news` on relevant bot |
| Log a new trade | `log-entry SYMBOL --entry ...` on either bot |
| Close a trade | `log-exit SYMBOL --exit ... --reason ...` |
| Quick tracker status | `tracker` on either bot |

## Interpretation Quick Reference

| Signal | Scion-Bot Reaction | Omaha-Bot Reaction |
| :--- | :--- | :--- |
| Credit Stress < 20 | Normal trading, 8% max positions | Normal buying |
| Credit Stress 20-40 | Reduce to 5% max positions | Hold, no change |
| Credit Stress 40-60 | Cash to 20%, top 5 only | Pause new buys |
| Credit Stress 60-80 | Exit all longs | Thesis review on everything |
| Credit Stress 80+ | Capital preservation | Cash to 50%+ |
| HY spread > 500 bps | Immediate defensive posture | Review all positions |
| ARCC dividend cut | Reduce equity exposure | Increase cash |
| 30Y > 5.5% sustained | Full defensive | Systemic mode |
