# Market Analytics Core Design

**Date:** 2026-09-01  
**Status:** Approved in conversation  
**Scope:** Offline-first analytics core for deterministic fixtures and replay

## Goal

Add a complete, provider-neutral market microstructure and options-positioning
analytics core that can be exercised without credentials or network access.
The same event pipeline will be used by fixture replay now and by future live
providers later. The first milestone proves the definitions, state handling,
provenance, and failure behavior before adding streaming infrastructure.

## Non-goals for this milestone

The following are deliberately not implemented or exposed as partial features:

- live L2, MBO, OPRA, or other provider adapters;
- FastAPI, WebSocket, React, or dashboard views;
- database or raw-feed persistence;
- broad/deep screener ranking, confluence scoring, or structural-level UI;
- forward-event evaluation and production deployment observability.

Provider protocols may define these future boundaries, but no live capability
will be claimed by the fixture implementation.

## Package boundary

Create `stock_analysis.market_analytics` as an independent package under the
existing root package. Existing bot and backtest modules remain unchanged.
The core uses standard-library dataclasses, enums, protocols, `datetime`,
`math`, and bounded collections. No new provider SDK or runtime dependency is
needed for the offline milestone.

Planned modules:

- `models.py` — immutable events, instrument metadata, result metadata, and
  generic metric results;
- `config.py` — typed defaults and validation for sessions, windows,
  thresholds, root grids, and retention;
- `providers.py` — provider protocols and capability registry;
- `replay.py` — deterministic fixture provider and event replay;
- `dom.py` — order-book state, metrics, displayed-liquidity reliability, and
  bounded heatmap observations;
- `order_flow.py` — trade classification, footprints, CVD, VI, exhaustion,
  and flow-delta flips;
- `vwap.py` — exact and explicitly approximate session VWAP;
- `profiles.py` — TPO, single prints, exact/approximate volume profiles,
  rolling windows, and level clusters;
- `options.py` — normalized option contracts, validation, IV-by-strike
  analytics, and heatmap data;
- `positioning.py` — dealer-position models, GEX/DEX, flips, walls, and
  dealer hedge saturation;
- `pipeline.py` — one event-to-snapshot analytics pipeline;
- `fixtures.py` — small deterministic demonstrations shared by the offline
  CLI and integration tests.

Add an `analytics demo` namespace to the existing root CLI. It will run the
checked-in deterministic fixture through the pipeline and emit JSON-safe
results without importing live-data libraries.

## Data contracts and provenance

Use `typing.Protocol` for:

- `MarketDataProvider`;
- `DepthDataProvider`;
- `HistoricalTradesProvider`;
- `OptionsDataProvider`;
- `CorporateActionsProvider`.

`CapabilityRegistry` reports independent support for L2, MBO, trade side,
historical ticks, option chains, Greeks, IV, OI, auctions, and corporate
actions. A fixture can intentionally disable any capability.

Events are immutable and timezone-aware: quote, trade, book snapshot, book
update, bar, option-chain snapshot, session transition, and corporate action.
An `InstrumentSpec` provides symbol, venue, tick size, precision, and option
multiplier. Price-level comparisons use normalized ticks rather than raw
floating-point equality.

Every public computed value is a `MetricResult` containing its value or `None`
and `MetricMetadata`:

- `as_of`, provider, dataset, and venue scope;
- calculation version and freshness;
- status (`ok`, `degraded`, `stale`, or `unavailable`);
- methodology and quality score;
- provenance (`observed`, `derived_from_observed`, `modeled`, or
  `approximate`).

Missing analytics are never represented by a meaningful-looking zero. A valid
empty book is the one documented exception: its zero-denominator OBI is `0`
with degraded quality and an explicit reason.

## Replay and pipeline

`ReplayProvider` accepts a deterministic ordered event list, exposes its
capabilities, and supports incomplete/stale/gap fixtures. `ReplayEngine` feeds
events to `AnalyticsPipeline`; it does not use a second implementation of any
formula. Stable event ordering is preserved for equal timestamps.

The pipeline owns session context and routes each event to the relevant state:

```text
event -> session context
      -> order book / DOM state
      -> trade classification / footprint / CVD
      -> VWAP / TPO / volume-profile state
      -> latest option-chain positioning state
      -> provenance-aware analytics snapshot
```

## DOM semantics

The order-book state machine handles snapshots, add/modify/cancel updates,
trades, sequence numbers, gaps, stale data, resnapshot recovery, locked or
crossed books, and session transitions. A sequence gap invalidates derived DOM
metrics until a later valid snapshot resets the expected sequence.

For N levels, OBI is `(bid_depth - ask_depth) / (bid_depth + ask_depth)` at
N = 1, 3, 5, and 10. The implementation clamps only for numerical safety and
tests the result in `[-1, 1]`. Microprice uses queue sizes and is returned only
for valid non-crossed top-of-book data. The snapshot also reports midpoint,
spread, bps fields, depth slope, ratios, concentration, distance-weighted
imbalance, add/cancel velocity, queue depletion, and replenishment.

Displayed-liquidity walls require size normalization, persistence,
replenishment, cancellation behavior, executed volume, distance, and repeated
appearance. They are labelled displayed-liquidity reliability; the code does
not claim spoofing detection. Heatmaps use a bounded rolling observation buffer
with absolute, signed, normalized, persistent, and activity views.

## Flow and footprint semantics

Explicit aggressor side is observed. If absent, quote context classifies trades
at or through the ask/bid with lower confidence. Unclassifiable trades remain
unclassified and reduce data quality rather than changing delta.

Footprints aggregate bid-aggressor volume, ask-aggressor volume, total volume,
and `delta = ask_volume - bid_volume` by configurable bar duration and price
bucket. CVD is the cumulative bar delta.

VI supports horizontal and diagonal comparisons, with diagonal as the default,
configurable ratio, minimum stack length, and explicit zero-reference handling.
Zones include time, price range, direction, ratio, level count, volume, age,
retest state, and failure state.

Flow exhaustion combines configurable price/CVD/delta slopes, efficiency,
divergence, and absorption features. Flow-delta flips are separate events
requiring a configured sign change plus optional confirmation. Neither is
mixed with dealer DEX or dealer hedge saturation.

## VWAP and profiles

VWAP uses exact transaction prices and volume when trades exist. Bar-only mode
uses the configured representative price and is explicitly approximate. The
session clock defaults to America/New_York RTH 09:30–16:00, with extended-hours
behavior configurable. Bands use volume-weighted dispersion.

TPO is independent of volume profile. It uses configurable brackets and rows,
counts one TPO per bracket/row, and calculates POC, value area, midpoint,
above/below counts, and initial balance. POC ties resolve by highest count,
closest to profile midpoint, then lower row. Single prints are confirmed only
after the profile is finalized and remain available while unfilled.

Exact volume profiles aggregate trade volume at normalized prices. Bar-only
profiles are approximate. Completed session histograms are retained in a
bounded deque; 14, 30, 60, 90, and 120-session windows are maintained through
addition/subtraction rather than reprocessing all historical trades. HVN/LVN
and cross-window clusters use configured thresholds and tick/ATR-aware
distance.

## Options and positioning semantics

Option contracts are normalized with expiration, strike, call/put, multiplier,
quotes, trades, volume, OI, IV, Greeks, timestamps, and source fields.
Validation rejects invalid spreads, negative OI/volume, invalid expirations or
multipliers, stale underlying context, unreasonable prices, and unsupported
adjustments with explicit reasons.

IV analytics report by-strike IV, ATM IV, skew, slope, curvature, anomaly
scores, changes, liquidity quality, and expiration-by-strike heatmap values.
Provider Greeks/IV are observed when supplied. A pluggable European
Black–Scholes fallback is marked approximate because US equity/ETF early
exercise effects are not represented.

Public OI does not reveal dealer inventory. `CLASSIC_OI_PROXY` centralizes the
declared call/put sign convention; `UNSIGNED_EXPOSURE` is a separate declared
model. Every GEX/DEX result is labelled modeled and includes the model
description.

GEX uses:

```text
position_sign * gamma * open_interest * multiplier * spot^2 * 0.01
```

DEX uses:

```text
position_sign * delta * open_interest * multiplier * spot
```

Both aggregate by strike, expiration, DTE bucket, and full chain. Gamma/DEX
flips reprice across a configured hypothetical spot grid using sticky-strike
IV, interpolate validated sign-change roots, and return all valid roots plus
the nearest root. No root is fabricated. Dealer hedge saturation is a
separate normalized heuristic based on absolute exposure, high-delta fraction,
gamma, and the local DEX slope.

## Failure behavior

The same state rules apply in replay and future live adapters:

- no L2 or invalid book → DOM metrics unavailable;
- no trades or unknown trade side → exact footprint unavailable or degraded;
- no exact trade prices → approximate VWAP/profile only;
- no OI → GEX/DEX unavailable;
- no IV/Greek source or enabled model → relevant option metric unavailable;
- stale inputs → stale status and reduced quality;
- invalid option contract → excluded with a reason;
- sequence gap → DOM unavailable until resnapshot;
- empty or zero-denominator calculations → deterministic documented result,
  never an unlabelled zero.

## Verification design

Use test-first cycles for each public behavior. Required fixture tests include:

- five-level OBI and microprice with hand-calculated values;
- sequence gap invalidation and snapshot recovery;
- displayed-liquidity persistence/reliability;
- three-trade VWAP and bar-only approximate VWAP;
- known footprint, CVD, diagonal VI stack, exhaustion, and flow flip;
- tied TPO POC and confirmed/unconfirmed single prints;
- known volume-at-price, value area, rolling-window boundaries, and clusters;
- normalized option validation and missing-OI behavior;
- GEX scaling, gamma/DEX roots, residual tolerance, and no-root cases;
- replay integration and JSON serialization round trips.

Property/invariant checks will enforce OBI bounds, microprice bounds, cumulative
CVD, deterministic profile rules, no future-session leakage, and provenance
labels. The offline CLI demo must run without network access and produce stable
output.

Documentation will add a methodology reference covering all formulas and the
required distinctions between observed data, approximations, flow delta,
dealer DEX, flow exhaustion, hedge saturation, TPO POC, and volume POC. The
root README and source manifest will document the fixture command and the
milestone boundary.

