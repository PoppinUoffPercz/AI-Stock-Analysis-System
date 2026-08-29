# rsi_reversion hypothesis

**Hypothesis**: Mean-reversion on the 14-period RSI — enter long equity when
RSI falls below 30 (oversold), exit when RSI returns above 50 (mean) — should
add a small left-tail-limited positive expected value per trade in US equities
where daily return serial autocorrelation is mildly negative (overnight
reversion).

Expected behavior:
- Sharp down-moves that close below RSI 30 are typically followed by a reversal
  in the next session. Entry at the close of the trigger bar, fill at next open.
- Exit at the mean (RSI 50) rather than waiting for overbought, to capture
  the bulk of the reversion without giving back gains.

Risk we want to rule out via M6 validation:
- **Survivorship**: on free yfinance data, only currently-listed names are
  sampled. Strategies that *would* have chosen delisted bankrupt names win
  in backtest only. Mitigate universe membership with explicit list/delist dates.
- **Thin trades**: RSI < 30 happens rarely; n_trades per year may be < 10,
  triggering the bias audit's "thin trades" flag. Accept this if OOS stitched
  equity on 5 IS/OOS pairs is positive AND permutation p-value < 0.05.
- **Slippage domination**: trades last 1-3 bars; slippage on entry+exit must
  fit in the gap between RSI 30 and RSI 50. Sensitivity sweep on `base_bps` in
  cost model + walk-forward WFE is the gate.

Failure modes:
- Strategy performs well only in high-volatility regimes (2020, 2022).
  -> tag as `regime-dependent`, do not deploy without regime filter.
- Random-entry permutation produces 30%+ variants beating the real strategy
  -> strategy edges out to noise; abandon.
