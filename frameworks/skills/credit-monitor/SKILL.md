# Credit Market Monitor

Analyze US credit market health using the `credit_monitor.py` module. This skill tells both the Scion-Bot (Burry) and Omaha-Bot (Buffett) how to interpret credit signals and factor them into risk management.

## Quick Reference

```bash
python credit_monitor.py              # Full report with breakdown
python credit_monitor.py --pulse      # Condensed one-liner for premarket
```

## Composite Credit Stress Index (0-100)

**Higher = worse.** A weighted blend of six sub-scores:

| Weight | Signal | What it measures |
| :--- | :--- | :--- |
| 25% | Yield Curve Slope (2s10s) | Inversion = stress; bear steepening = fiscal fear |
| 20% | 30Y Treasury Level | Absolute yield vs 1Y history; >5% = 2007 territory |
| 20% | HY Credit Spread | HYG yield minus IEF yield; widening = risk-off |
| 15% | IG Credit Spread | LQD yield minus IEF yield; first warning before HY |
| 10% | SOFR Level | Overnight borrowing cost; rising = tightening liquidity |
| 10% | Private Credit News | PIK/deafult/BDC keyword alerts |

## Scale & Risk Posture

| Score | Label | Agent Action |
| :--- | :--- | :--- |
| 0-20 | **Benign** | Normal operation. Both agents proceed normally. |
| 20-40 | **Elevated** | Reduce margin. Scion trims to 5% max position. Omaha holds. |
| 40-60 | **Stressed** | Cash to 20%. Scion holds only top 5 highest-conviction plays. Omaha pauses new buys. |
| 60-80 | **Crisis** | Cash to 35%+. Scion exits all longs. Omaha reviews thesis on every position. |
| 80-100 | **Systemic** | Cash to 50%+. Both agents in capital preservation mode only. |

## Interpretation Guide

### 1. Yield Curve (25% weight)
- **Inverted** (2s10s < 0): Historically predicts recession within 12-18 months. Recession = credit defaults rise.
- **Bear steepening** (long rates rising faster than short): Signals fiscal/inflation concerns, not growth optimism.
- **Current context:** The 2026 environment is a bear steepening. The 30Y at 5%+ is driven by supply/deficit fears, not strong growth — a different signal than a normal steepening.

### 2. 30Y Treasury (20% weight)
- The "trust check" on US fiscal solvency. When it rises above 5%, the market is demanding a risk premium for holding US debt long-term.
- **Important:** If 30Y rises while stocks are also rising, it's a "good" signal (growth optimism). If 30Y rises while stocks fall, it's a "bad" signal (liquidity/solvency fear).

### 3. Credit Spreads (35% combined)
- **IG spreads** (<100 bps = tight, >200 bps = stressed). IG is the canary — investment grade companies are the first to see funding pressure.
- **HY spreads** (<350 bps = normal, >500 bps = stressed). HY is the confirmation.
- **Widening divergence** (IG tight, HY widening) = sector-specific stress. Both widening = systemic.

### 4. SOFR (10% weight)
- The plumbing rate. Above 5% = tight conditions (like 2023). Below 4% = accommodative.
- **Spikes** above normal range signal repo market stress (like Sept 2019).

### 5. Private Credit (10% weight)
- Hardest to measure in real-time. Relies on news keyword matching.
- Keywords signal severity: "PIK toggle" > "non-accrual" > "maturity wall"
- The $85B BDC maturity wall (2026-2029) is a slow-burn risk, not a sudden crisis.

## When to Override

1. **Fed pivot:** If the Fed cuts rates aggressively, reduce stress score interpretation by one level (Stressed -> Elevated).
2. **Fiscal crisis:** If US credit rating is downgraded or Treasury auction fails, increase stress by one level regardless of score.
3. **Banking stress:** If a major bank (GS, JPM, BAC) CDS spreads blow out, treat as Crisis regardless of composite score.
