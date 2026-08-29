---
title: "Credit Monitor"
date: 2026-07-07
tags:
  - docs
  - credit
---

# Credit Monitor

Predicts credit market stress using six weighted signals. Built as both a Python module (`credit_monitor.py`) and an opencode skill (`.opencode/skills/credit-monitor/SKILL.md`).

## Composite Credit Stress Index (0-100)

**Higher = worse.** Weighted blend:

| Weight | Signal | Source | What It Measures |
| :--- | :--- | :--- | :--- |
| 25% | Yield Curve (2s10s) | `^TNX` - SHY yield | Inversion = recession risk; bear steepening = fiscal fear |
| 20% | 30Y Treasury Level | `^TYX` | "Trust check" on US fiscal solvency. >5% = 2007 territory |
| 20% | HY Credit Spread | HYG yield - IEF yield | Risk appetite of credit markets. Widening = risk-off |
| 15% | IG Credit Spread | LQD yield - IEF yield | First warning before HY spreads blow out |
| 10% | SOFR Level | sofrrate.com scrape | Overnight borrowing cost. Above 5% = tight |
| 10% | Private Credit News | BDC ticker keywords | PIK/default/BDC signal from news scanning |

## Scale

| Score | Label | Agent Action |
| :--- | :--- | :--- |
| 0-20 | Benign | Normal operation |
| 20-40 | Elevated | Reduce margin. Scion max position 5%. Omaha holds. |
| 40-60 | Stressed | Cash to 20%. Scion top 5 only. Omaha pauses new buys. |
| 60-80 | Crisis | Cash to 35%+. Scion exits longs. Omaha thesis review. |
| 80-100 | Systemic | Cash to 50%+. Capital preservation only. |

## How To Use

```bash
# Full report (saves to vault)
python credit_monitor.py

# Premarket one-liner
python credit_monitor.py --pulse
```

## Private Credit Keywords Scanned

The news engine monitors BDC tickers (KKR, ARCC, FSK, BX, OBDC, MAIN) for:

| Category | Keywords |
| :--- | :--- |
| PIK | payment in kind, PIK toggle, capitalized interest, deferral |
| Default | default, non-accrual, distressed, restructuring, Chapter 11 |
| BDC | BDC, maturity wall, cov-lite, private credit, direct lending |
| Warning | credit crunch, liquidity crisis, margin call, forced selling, contagion |

## State

Seen articles are tracked in `credit_state.json` for dedup across runs.

## The Core Thesis

Credit spreads (HY at ~200bps) and Treasury yields (30Y at 5%+) are pricing two different realities. One is wrong. The monitor catches the moment they converge.

Reference: Credit Cycle Tipping Point Analysis
