# bollinger_breakout hypothesis

**Hypothesis**: A breakout above the upper Bollinger Band (20-day SMA + 2σ)
captures the leading edge of a volatility expansion — when realized vol
transitions from low to high, returns a small positive expected value on US
equity daily bars, and exits quickly at the middle band to avoid mean
reversion drag.

Expected behavior:
- Low-vol regime -> few signals (the bands rarely get crossed); strategy
  sits flat or has minimal exposure. Captures right-tail events when vol
  expansion begins.
- High-vol regime -> frequent signals; risk of being whipsawed between
  upper and middle bands. Realistic costs (us_equity_pershare) materially
  damage edge if std_dev is tight (lots of touch events).

Risk we want to rule out via M6 validation:
- **Look-ahead**: entry/exit derived from bars that are *currently closed*;
  fills occur at next bar open in both adapters. Audit with `.shift(-1)` scan.
- **Whipsaw cost dominance**: param sweep on `(period, std_dev)` with realistic
  costs to find the region where Sharpe stays positive.
- **Overfit band widths**: stability heatmap across `(period ∈ {10,15,20,30,40},
  std_dev ∈ {1.5, 2.0, 2.5, 3.0})` should be plateau-shaped, not a single
  spike.

Failure modes:
- Strategy only profitable in 2020-2022 regime (vol expansion era); do not
  deploy without regime filter.
- Cost-adjusted Sharpe < 0.5 -> abandon; the alpha is commission, not signal.
