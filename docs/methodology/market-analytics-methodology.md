# Market Analytics Methodology

## Scope

This document defines the calculations implemented by the offline analytics
core. It describes what the fixture can prove and what the metrics do not
claim. A result is only useful with its input quality and provenance.

## Result labels

Every scalar is returned as a `MetricResult` with a value or `None` plus
metadata. The metadata records the UTC observation time, provider, dataset,
venue scope, freshness, status, quality score, methodology, and one of these
provenance labels:

- `observed`: supplied directly by the provider, such as an explicit trade
  side or provider IV;
- `derived_from_observed`: calculated from observed inputs, such as OBI or
  CVD;
- `modeled`: dependent on an explicit model assumption, such as GEX/DEX;
- `approximate`: calculated from lower-resolution or simplified inputs;
- `unavailable`: the required input or model is missing.

`ok`, `degraded`, `stale`, and `unavailable` are status values. `None` means
the number is not available; it is not a hidden zero.

## DOM and displayed liquidity

For the best `N` normalized price levels, let `B_N` be displayed bid depth and
`A_N` be displayed ask depth. Order-book imbalance is:

```text
OBI_N = (B_N - A_N) / (B_N + A_N)
```

OBI is dimensionless and is reported for N = 1, 3, 5, and 10 by default. It is
bounded to `[-1, 1]`. A valid empty book returns `0` with degraded quality and
an explicit zero-denominator reason; an invalid book returns unavailable.

The midpoint and spread are:

```text
midpoint = (best_bid + best_ask) / 2
spread = best_ask - best_bid
spread_bps = spread / midpoint * 10,000
```

Spread is in price units and spread bps is dimensionless basis points. The
queue-size weighted microprice is:

```text
microprice = (best_ask * bid_size + best_bid * ask_size)
             / (bid_size + ask_size)
```

It is in price units and is emitted only for a valid, non-locked,
non-crossed top of book with a nonzero queue-size denominator. Its distance
from midpoint is reported in bps. Depth slope, concentration, depth ratio,
distance-weighted imbalance, add/cancel velocity, queue depletion, and
replenishment are derived from the normalized book levels and bounded activity
history.

Displayed-liquidity walls are not spoofing detection. A candidate must pass
size normalization, distance, persistence, repeated appearances, replenishment,
executed-volume, cancellation, and reliability thresholds. The reliability
score combines those configured components and is labelled derived from
observed displayed liquidity.

The heatmap keeps a bounded recent observation buffer. It can render absolute
depth, signed depth, normalized depth, persistent levels, and add/cancel
activity. Retention is bounded by both observation count and time window.

## Trade flow and footprint

An explicit provider aggressor side is observed. If it is absent, a trade at or
through the observed ask is classified as a buy and a trade at or through the
observed bid as a sell, with lower confidence. A trade between quote bounds
remains unknown. Unknown volume stays in total volume but does not change
delta, and lowers flow quality.

For each normalized bar and price row:

```text
delta = ask_aggressor_volume - bid_aggressor_volume
CVD_t = CVD_(t-1) + bar_delta_t
```

Delta, CVD, bid volume, ask volume, and total volume use the instrument's
trade-size units (for example, shares or contracts). Footprints also report
horizontal, diagonal, and stacked volume imbalances. A ratio compares the
dominant side with its configured opposing reference; diagonal mode compares
the adjacent price row. Zero references are explicit rather than silently
treated as infinite volume.

Flow exhaustion combines configured normalized price slope, CVD slope, delta
slope, price-per-absolute-delta efficiency, divergence, and absorption inputs.
It clips the weighted score to `[0, 1]`. A flow-delta flip requires a configured
delta or CVD-slope sign change and confirmation; it records before/after values
and the pre-flip exhaustion score. Flow exhaustion and flips describe trade
flow. In particular, flow delta is not dealer DEX.
flow delta exhaustion is not dealer hedge saturation.

## Session VWAP

The default session clock is America/New_York regular trading hours, 09:30 to
16:00, with extended hours disabled. Session accumulators reset on a session
change.

With exact trades, session VWAP is:

```text
VWAP = sum(price_i * volume_i) / sum(volume_i)
```

VWAP is in price units. Weighted price dispersion is:

```text
variance = sum(price_i^2 * volume_i) / sum(volume_i) - VWAP^2
stddev = sqrt(max(variance, 0))
```

Configured bands are `VWAP +/- multiplier * stddev`. Current distance is
`(current_price - VWAP) / VWAP * 10,000` bps, and the z-score is distance in
price units divided by `stddev`. The slope is the linear slope of recent VWAP
samples per accumulated observation.

If only bars are available, the representative price is:

```text
bar_price = (high + low + close) / 3
```

That calculation and every result containing bar observations are labelled
approximate. No volume produces unavailable VWAP metrics.

## TPO and volume profiles

TPO uses configurable time brackets and price rows. Each bar contributes one
occurrence to each normalized row between its low and high during its bracket;
repeated observations in one bracket count once.
TPO POC counts time-price occurrences. TPO POC ties resolve by highest count, closest distance to the
profile midpoint, then the lower row.

The TPO value area expands from POC until the configured cumulative percentage
is reached. At each step it chooses the higher-count adjacent row, then the row
closer to the profile midpoint, then the lower row. TPO also reports VAH, VAL,
midpoint, counts above/below POC, and initial balance from the first configured
brackets.

A single-print row has one bracket occurrence and qualifying neighbors. It is
developing before session finalization and confirmed only after finalization;
filled and retest fields remain explicit.

Exact volume-at-price bins trade volume at normalized trade prices.
volume POC counts traded volume, not time. With candles, volume is assigned to the
representative `(high + low + close) / 3` row.
candle-derived volume profile is approximate. Value-area and high/low-volume classifications use configured
thresholds. Completed session histograms are kept in a bounded deque, and the
14, 30, 60, 90, and 120-session defaults update through running histogram
addition/subtraction. Cross-window clusters use tick- and configured distance
tolerances.

## Option normalization and IV

The normalizer validates underlying, expiration, strike, multiplier, quote
spread, prices, volume, OI, timestamps, adjustments, and source fields. Invalid
records are rejected with a reason and do not enter analytics. OI and quote
freshness are checked at calculation time.

Provider IV and Greeks are observed when present. If the configured model is
enabled and a provider IV is available, the European Black-Scholes model can
calculate fallback Greeks. If IV is absent, the model can solve for IV by
bisection within configured bounds from a usable option price. These results
are approximate: early exercise, dividends beyond the configured yield, and
provider-specific surface construction are not inferred.

The IV surface reports by-strike values, ATM IV, skew, slope, curvature,
anomaly scores, changes, liquidity quality, and expiration-by-strike heatmap
values. Empty or unsolvable surfaces are unavailable, not zero.

## Shared volatility state

The shared volatility engine keeps options as one input to stock analysis. It
reports per-expiration ATM IV, target-horizon IV, completed-session historical
IV context, close-to-close realized volatility, IV/RV spread and ratio, term
structure, a short-versus-long event-premium heuristic, and 25-delta put/call
skew. It does not turn any of these state labels into a trade instruction.

Target-horizon IV uses linear interpolation of total variance
`IV^2 * time_to_expiry` and only runs when two expirations bracket the target.
There is no extrapolation. IV time uses actual elapsed calendar seconds over a
365-day year. Realized-volatility windows use completed session closes, sample
standard deviation of log returns, and `sqrt(252)` annualization. The current
IV observation is added to history only when its own session is finalized, and
session finalization is idempotent.

Historical percentile is the percentage of prior observations strictly below
the current value. Historical rank is the current value's clipped position
between the prior low and high. A zero-range or short history is unavailable,
not a fabricated neutral score. The 25-delta risk reversal is call IV minus put
IV; butterfly is the average of those wings minus ATM IV.

## Statistical levels and confluence

Implied and realized bands use `spot * annualized_volatility * sqrt(T)` and
carry explicit `calendar_days` or `trading_sessions` units. Session VWAP,
profile, dealer-positioning, displayed-liquidity, and flow-structure outputs
are converted to the same `Level` contract. A level's structural strength is
separate from confidence, which is inherited from `MetricMetadata.quality_score`.

Nearby levels are clustered using the maximum of tick, spot-basis-point, and
optional ATR tolerances. Zone scoring caps each source family before rewarding
family diversity, source quality, and structural strength. Credit stress is
context only and cannot add a price level or inflate confluence.

## Credit context and flat features

`CreditStressEngine` preserves the six-factor credit model: 2s10s slope, 30Y
Treasury level, HY and IG proxy spreads, SOFR, and active private-credit alerts.
Missing factors are unavailable. If enough configured weight remains, available
weights are renormalized and the composite is marked degraded; below the
coverage threshold it is unavailable. ETF yield differences are labelled
proxies, not option-adjusted spreads. Alert activity is determined from
publication timestamps at the requested `as_of`.

`CreditVolatilityEngine` summarizes IV rank and IV/RV ratio across the configured
credit-ETF states after excluding states later than the requested cutoff.
`CreditRegimeEngine` keeps stress, volatility, and their relationship separate.
The legacy credit monitor has an adapter at the typed boundary; its fallback
scores are not copied, and untimestamped news remains unavailable.

Each pipeline snapshot also exposes a `FeatureRecord`. It contains stable flat
numeric keys such as `atm_iv_30d`, `iv_percentile_252d`, `rv_20d`, `iv_rv_ratio_30d`,
term spreads, skew, event state, distances to IV bands, and nearest confluence.
Every key retains its source metadata. RND distance fields are explicitly
unavailable until an arbitrage-clean surface and smoothing design is approved.

## Modeled positioning

public option OI does not disclose dealer inventory. The implementation therefore
requires a declared model and labels every GEX/DEX output `modeled`.

The default classic OI proxy uses call sign `+1` and put sign `-1`:

```text
GEX_contract = position_sign * gamma * open_interest
               * contract_multiplier * spot^2 * 0.01

DEX_contract = position_sign * delta * open_interest
               * contract_multiplier * spot
```

GEX is in scaled spot-dollar gamma exposure and DEX is in spot-dollar delta
exposure under this convention. Contributions aggregate by strike,
expiration, and full chain. The separate unsigned-exposure model uses positive
magnitudes and absolute Greeks; it is not interchangeable with the classic
proxy.

Gamma and dealer-DEX flips evaluate the selected exposure on the configured
spot grid. Each contract's IV is sticky by strike while hypothetical Greeks are
repriced through the configured European Black-Scholes model when possible.
Sign-change intervals are interpolated and the residual is re-evaluated. Only
roots inside the residual tolerance are returned; all qualifying roots and the
nearest root are exposed, and no-root cases remain no-root cases.

Conventional call and put walls are available only for the classic OI proxy and
select the highest-OI strike per side. Dealer hedge saturation is a separate
normalized heuristic using high-absolute-delta OI fraction, absolute DEX,
absolute GEX, and local DEX slope. It is labelled modeled and heuristic. Flow
delta is not dealer DEX.

## Defaults and limitations

The main defaults are five-second DOM freshness, sixty-second activity
velocity, fifteen-minute heatmap retention, one-minute flow bars, a 3.0
imbalance ratio, 30-minute TPO brackets, 70% TPO value area, the five rolling
profile windows above, a 20%/81-point positioning root grid, zero risk-free and
dividend yields, and two days of option quote freshness.

When inputs are missing, stale, invalid, locked, crossed, or incomplete, the
affected metric reports an explicit status, provenance, quality, and reason.
The fixture and replay path are offline only. Live market adapters, persistence,
API/UI surfaces, screener/confluence logic, forward research, and production
deployment checks are intentionally deferred until this methodology is tested
against real provider contracts.
