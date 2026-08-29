# sma_cross hypothesis

**Hypothesis**: A short-horizon trend-following signal — long equity when the
fast simple moving average (10-day) crosses above the slow SMA (30-day), exit
when it crosses below — captures a slower trend component of US equity
returns consistently enough to beat buy-and-hold on a **risk-adjusted** basis.

Expected behavior:
- Trend regimes -> active long exposure captures most of the up-move.
- Choppy / range-bound regimes -> frequent entries/exits, modest drag from
  churn + slippage. Realistic commission + linear-impact slippage (default
  `us_equity_pershare` cost preset) must not destroy edge in trend regimes.

Risk we want to rule out via M6 validation:
- **Look-ahead**: fill at next-bar open only (VBT: `freq=1D`, `init_cash` set;
  Backtrader: `set_coc(False)`).
- **Overfitting**: walk-forward with 5y IS / 1y OOS, stitched OOS equity,
  WFE >= 50%. Permutation test vs random-entry H0 with p-value < 0.05.
- **Parameter spike**: stability heatmap should show a plateau around the
  chosen 10/30 window — not a single-cell spike.

Failure modes:
- Strategy works in 2010-2020 bull but produces negative OOS in 2022 regime
  shift -> tag with `regime_dependent` and do *not* deploy.
- Sharpe > 1.5 triggers bias-audit flag on synthetic or in-sample data ->
  suspect look-ahead; review signal factory.
