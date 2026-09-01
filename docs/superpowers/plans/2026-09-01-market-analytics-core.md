# Market Analytics Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete offline-first market microstructure and options-positioning analytics core that runs through deterministic fixtures before any live provider, API, or UI work is added.

**Architecture:** Add an independent `stock_analysis.market_analytics` package built from standard-library dataclasses, enums, protocols, math, and bounded collections. A single `AnalyticsPipeline` consumes typed market events; `ReplayProvider` feeds the same pipeline used by future live adapters. Existing bot and backtest packages remain unchanged except for a lazy root CLI namespace and documentation.

**Tech Stack:** Python 3.12+, standard library runtime, `pytest`, `ruff`, and `mypy` for development checks. No provider SDK, network call, database, FastAPI, React, or new runtime dependency is part of this milestone.

## Global Constraints

- All event timestamps must be timezone-aware UTC.
- Every public computed value must carry `MetricMetadata` and a declared provenance.
- Missing analytics are `None` with `unavailable`/`degraded` metadata, never an unlabeled zero.
- A valid empty book may return zero-denominator OBI `0.0` only with degraded metadata and an explicit reason.
- Public OI does not reveal dealer inventory; every GEX/DEX result is labelled modeled.
- `flow_delta`, `dealer_dex`, `FlowDeltaExhaustion`, and `DealerHedgeSaturation` remain separate concepts.
- Exact trade calculations and approximate bar calculations must have different provenance.
- The replay path and future live path must share the same analytics pipeline and formulas.
- No live provider adapter, persistence layer, API, UI, screener, confluence scorer, or forward evaluator will be exposed in this milestone.
- Production code is written only after its focused test has failed for the expected missing-behavior reason.
- Use `C:\Users\alexp\AppData\Local\Programs\Python\Python312\python.exe` when the Windows `python` alias is unavailable.
- Do not stage or modify existing untracked `docs/research/` or `docs/superpowers/plans/` content except for the files named in this plan.

## File Map

Create:

- `stock_analysis/market_analytics/__init__.py` — stable public exports.
- `stock_analysis/market_analytics/models.py` — events, enums, instruments, metadata, and metric wrappers.
- `stock_analysis/market_analytics/config.py` — typed configuration and defaults.
- `stock_analysis/market_analytics/providers.py` — provider protocols and capabilities.
- `stock_analysis/market_analytics/replay.py` — deterministic fixture provider and replay runner.
- `stock_analysis/market_analytics/dom.py` — order-book state, metrics, walls, and bounded heatmap.
- `stock_analysis/market_analytics/order_flow.py` — classification, footprint, CVD, VI, exhaustion, and flow flips.
- `stock_analysis/market_analytics/vwap.py` — session VWAP and bands.
- `stock_analysis/market_analytics/profiles.py` — TPO, single prints, volume profiles, rolling windows, and clusters.
- `stock_analysis/market_analytics/options.py` — normalized option records, IV analytics, and Black–Scholes fallback.
- `stock_analysis/market_analytics/positioning.py` — dealer models, GEX/DEX, flips, walls, and saturation.
- `stock_analysis/market_analytics/pipeline.py` — event routing and analytics snapshots.
- `stock_analysis/market_analytics/fixtures.py` — deterministic fixture builders.
- `stock_analysis/market_analytics/serialization.py` — JSON-safe round trips.
- `tests/market_analytics/test_models.py`
- `tests/market_analytics/test_replay.py`
- `tests/market_analytics/test_dom.py`
- `tests/market_analytics/test_order_flow.py`
- `tests/market_analytics/test_vwap.py`
- `tests/market_analytics/test_profiles.py`
- `tests/market_analytics/test_options.py`
- `tests/market_analytics/test_positioning.py`
- `tests/market_analytics/test_pipeline.py`
- `tests/market_analytics/test_serialization.py`
- `tests/market_analytics/test_documentation.py`
- `tests/market_analytics/support.py` — reusable deterministic test constants and option helpers.

Modify:

- `stock_analysis/cli.py` — add a lazy `analytics demo` namespace and dispatch.
- `README.md` — document the fixture demo and milestone boundary.
- `SOURCE-MANIFEST.md` — record all new source, tests, and documentation.
- `pyproject.toml` — add root development type-checking support.

Create documentation:

- `docs/architecture/14-Market-Analytics.md` — package/data-flow and capability contract.
- `docs/methodology/market-analytics-methodology.md` — formulas, units, assumptions, and distinctions.

---

### Task 1: Establish typed models, provenance, and configuration

**Files:**
- Create: `stock_analysis/market_analytics/__init__.py`
- Create: `stock_analysis/market_analytics/models.py`
- Create: `stock_analysis/market_analytics/config.py`
- Create: `tests/market_analytics/support.py`
- Test: `tests/market_analytics/test_models.py`
- Modify: `pyproject.toml`

**Interfaces:**
- `MetricMetadata(as_of, provider, dataset, venue_scope, calculation_version, freshness_ms, status, methodology, quality_score, observed_or_modeled, reason)`
- `MetricResult[T](value, metadata)`
- `InstrumentSpec(symbol, venue, tick_size, price_precision, contract_multiplier)`
- Event dataclasses: `QuoteEvent`, `TradeEvent`, `BookSnapshotEvent`, `BookUpdateEvent`, `BarEvent`, `OptionChainEvent`, `SessionTransitionEvent`, and `CorporateActionEvent`.
- Enums: `MetricStatus`, `Provenance`, `Side`, `BookAction`, `AggressorSide`, and `CallPut`.
- `AnalyticsConfig` with nested `SessionConfig`, `DOMConfig`, `FlowConfig`, `VWAPConfig`, `ProfileConfig`, and `OptionsConfig`.

The event constructors use these field orders so all later fixture code is
unambiguous:

```python
QuoteEvent(symbol, timestamp, provider, dataset, bid, ask, bid_size, ask_size)
TradeEvent(symbol, timestamp, provider, dataset, price, size, aggressor_side, trade_id)
BookSnapshotEvent(symbol, timestamp, provider, dataset, sequence, levels)
BookUpdateEvent(symbol, timestamp, provider, dataset, sequence, action, side, price, size, order_id=None)
BarEvent(symbol, timestamp, provider, dataset, open, high, low, close, volume)
OptionChainEvent(symbol, timestamp, provider, dataset, spot, contracts)
SessionTransitionEvent(symbol, timestamp, provider, dataset, session_id, is_open)
CorporateActionEvent(symbol, timestamp, provider, dataset, action_type, ratio, old_symbol=None, new_symbol=None)
```

`OptionContractInput` is the raw normalized-input shape used by fixture
builders and contains `underlying`, `expiration`, `strike`, `call_put`,
`contract_multiplier`, `bid`, `ask`, `last`, `volume`, `open_interest`, `iv`,
`delta`, `gamma`, `theta`, `vega`, `quote_timestamp`, `trade_timestamp`,
`oi_as_of`, `greeks_source`, `iv_source`, `adjusted`, and
`adjustment_reason`; optional market fields may be `None`.

`tests/market_analytics/support.py` defines shared constants and helpers so
test snippets below are executable:

```python
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
T0 = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)


def ny_utc(hour: int, minute: int, *, day: int = 2) -> datetime:
    return datetime(2026, 1, day, hour, minute, tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)


def raw_option(**overrides):
    from stock_analysis.market_analytics.models import CallPut, OptionContractInput

    values = {
        "underlying": "AAA", "expiration": date(2026, 1, 16), "strike": 100.0,
        "call_put": CallPut.CALL, "contract_multiplier": 100, "bid": 1.0,
        "ask": 1.1, "last": 1.05, "volume": 10.0, "open_interest": 100.0,
        "iv": 0.20, "delta": 0.50, "gamma": 0.02, "theta": -0.01,
        "vega": 0.10, "quote_timestamp": T0, "trade_timestamp": T0,
        "oi_as_of": T0, "greeks_source": "fixture", "iv_source": "fixture",
        "adjusted": False, "adjustment_reason": None,
    }
    return OptionContractInput(**(values | overrides))
```

Tests import `T0`, `ny_utc`, and `raw_option` from this support module. Tests
that need module-specific helpers define them in their own file after the
target module exists.

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timezone

import pytest

from stock_analysis.market_analytics.models import (
    InstrumentSpec,
    MetricMetadata,
    MetricResult,
    MetricStatus,
    Provenance,
)


def test_metric_metadata_rejects_naive_as_of_and_out_of_range_quality():
    with pytest.raises(ValueError, match="timezone-aware"):
        MetricMetadata(
            as_of=datetime(2026, 1, 1),
            provider="fixture",
            dataset="trades",
            venue_scope="XNAS",
            quality_score=100,
            observed_or_modeled=Provenance.OBSERVED,
        )

    with pytest.raises(ValueError, match="quality_score"):
        MetricMetadata(
            as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
            provider="fixture",
            dataset="trades",
            venue_scope="XNAS",
            quality_score=101,
            observed_or_modeled=Provenance.OBSERVED,
        )


def test_instrument_normalizes_prices_to_tick_grid():
    instrument = InstrumentSpec("TEST", "XNAS", tick_size=0.05, price_precision=2)

    assert instrument.price_to_ticks(100.07) == 2001
    assert instrument.ticks_to_price(2001) == 100.05


def test_unavailable_metric_has_no_value_and_explicit_provenance():
    metadata = MetricMetadata.unavailable(
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
        provider="fixture",
        dataset="depth",
        venue_scope="XNAS",
        reason="sequence gap",
    )

    result = MetricResult[float](None, metadata)
    assert result.value is None
    assert result.metadata.status is MetricStatus.UNAVAILABLE
    assert result.metadata.observed_or_modeled is Provenance.UNAVAILABLE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/market_analytics/test_models.py`

Expected: collection fails with `ModuleNotFoundError: No module named 'stock_analysis.market_analytics'`.

- [ ] **Step 3: Write minimal implementation**

Implement frozen, slotted dataclasses and string-valued enums. Validate timezone awareness and `0 <= quality_score <= 100` in `MetricMetadata.__post_init__`. Implement `MetricMetadata.unavailable(...)` as the only helper that constructs an unavailable result. Normalize prices with integer ticks using `round(price / tick_size)` and return rounded display prices from `ticks_to_price`. Validate positive tick size, precision, and multiplier. Define all event fields as immutable and require their base timestamp fields to be UTC-aware. Add `mypy>=1.11` to the root `dev` extra without adding a runtime dependency. Put this exact support module beside the tests:

```python
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
T0 = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)


def ny_utc(hour: int, minute: int, *, day: int = 2) -> datetime:
    return datetime(2026, 1, day, hour, minute, tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)


def raw_option(**overrides):
    from stock_analysis.market_analytics.models import CallPut, OptionContractInput

    values = {
        "underlying": "AAA", "expiration": date(2026, 1, 16), "strike": 100.0,
        "call_put": CallPut.CALL, "contract_multiplier": 100, "bid": 1.0,
        "ask": 1.1, "last": 1.05, "volume": 10.0, "open_interest": 100.0,
        "iv": 0.20, "delta": 0.50, "gamma": 0.02, "theta": -0.01,
        "vega": 0.10, "quote_timestamp": T0, "trade_timestamp": T0,
        "oi_as_of": T0, "greeks_source": "fixture", "iv_source": "fixture",
        "adjusted": False, "adjustment_reason": None,
    }
    return OptionContractInput(**(values | overrides))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/market_analytics/test_models.py`

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```powershell
git add stock_analysis/market_analytics tests/market_analytics/test_models.py tests/market_analytics/conftest.py
git commit -m "feat: add market analytics typed models"
```

### Task 2: Add capability protocols and deterministic replay

**Files:**
- Create: `stock_analysis/market_analytics/providers.py`
- Create: `stock_analysis/market_analytics/replay.py`
- Test: `tests/market_analytics/test_replay.py`

**Interfaces:**
- `CapabilityRegistry(supports_l2, supports_mbo, supports_trade_side, supports_options_chain, supports_greeks, supports_open_interest, supports_auction_imbalance, supports_historical_ticks, supports_corporate_actions)`.
- Protocols: `MarketDataProvider`, `DepthDataProvider`, `HistoricalTradesProvider`, `OptionsDataProvider`, and `CorporateActionsProvider`.
- `ReplayProvider(events, capabilities, provider="fixture")` with `events(symbol=None)`.
- `ReplayEngine.run(provider, consumer, symbol) -> tuple[object, ...]`.
- `ReplayConsumer.consume(event)` and `ReplayConsumer.finalize(as_of)` protocols.

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timedelta, timezone

import pytest

from stock_analysis.market_analytics.models import TradeEvent
from stock_analysis.market_analytics.providers import CapabilityRegistry
from stock_analysis.market_analytics.replay import ReplayEngine, ReplayProvider


UTC = timezone.utc


def test_replay_preserves_equal_timestamp_input_order_and_filters_symbol():
    t = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
    events = [
        TradeEvent("AAA", t, "fixture", "trades", 100.0, 1.0, None, "first"),
        TradeEvent("BBB", t, "fixture", "trades", 200.0, 1.0, None, "other"),
        TradeEvent("AAA", t + timedelta(seconds=1), "fixture", "trades", 101.0, 2.0, None, "second"),
    ]
    provider = ReplayProvider(events, CapabilityRegistry(supports_historical_ticks=True))

    assert [event.trade_id for event in provider.events("AAA")] == ["first", "second"]


def test_replay_engine_rejects_missing_snapshot_consumer_contract():
    provider = ReplayProvider([], CapabilityRegistry())

    with pytest.raises(TypeError, match="consume"):
        ReplayEngine().run(provider, object(), "AAA")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/market_analytics/test_replay.py`

Expected: collection fails because the provider and replay modules do not exist.

- [ ] **Step 3: Write minimal implementation**

Implement the five protocols with precise iterator signatures over the event types. `ReplayProvider` stores a tuple in caller order, validates that every timestamp is UTC-aware, and filters by symbol without sorting equal timestamps. `ReplayEngine` checks `consume` and `finalize` with `getattr`, feeds only the requested symbol, appends non-`None` consumer snapshots, and appends the finalization result when present. No network or retry code belongs in this module.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/market_analytics/test_replay.py`

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```powershell
git add stock_analysis/market_analytics/providers.py stock_analysis/market_analytics/replay.py tests/market_analytics/test_replay.py
git commit -m "feat: add fixture provider and replay contract"
```

### Task 3: Implement order-book state and core DOM metrics

**Files:**
- Create: `stock_analysis/market_analytics/dom.py`
- Test: `tests/market_analytics/test_dom.py`

**Interfaces:**
- `OrderBookState(instrument, config, provider, dataset)`.
- `OrderBookState.apply(event, as_of=None) -> DOMSnapshot` for book, quote, trade, and session events; an optional `as_of` is a fixture/replay observation-time override.
- `OrderBookState.snapshot(as_of) -> DOMSnapshot` and `apply_modify(as_of, sequence, side, price, size) -> DOMSnapshot`.
- `DOMSnapshot.metrics: Mapping[str, MetricResult[float]]` with keys `book_imbalance_l1`, `book_imbalance_l3`, `book_imbalance_l5`, `book_imbalance_l10`, `midprice`, `microprice`, `microprice_minus_mid_bps`, `spread`, `spread_bps`, `depth_slope_bid`, `depth_slope_ask`, `bid_ask_depth_ratio`, `depth_concentration_bid`, `depth_concentration_ask`, `distance_weighted_imbalance`, `order_add_velocity`, `cancel_velocity`, `queue_depletion`, and `queue_replenishment`.
- `DOMSnapshot.state: str` with `valid`, `needs_snapshot`, `stale`, `locked`, or `crossed`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timezone

from stock_analysis.market_analytics.config import AnalyticsConfig
from stock_analysis.market_analytics.dom import OrderBookState
from stock_analysis.market_analytics.models import (
    BookLevel,
    BookSnapshotEvent,
    InstrumentSpec,
    Side,
)


def test_dom_snapshot_calculates_obi_and_microprice():
    as_of = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)
    levels = tuple(
        [BookLevel(Side.BID, 100.00 - i * 0.05, 10.0 + i) for i in range(5)]
        + [BookLevel(Side.ASK, 100.05 + i * 0.05, 5.0 + i) for i in range(5)]
    )
    state = OrderBookState(InstrumentSpec("AAA", "XNAS", 0.05, 2), AnalyticsConfig())

    snapshot = state.apply(BookSnapshotEvent("AAA", as_of, "fixture", "depth", 7, levels))

    assert snapshot.state == "valid"
    assert snapshot.metrics["book_imbalance_l1"].value == (10 - 5) / (10 + 5)
    assert snapshot.metrics["book_imbalance_l5"].value == (60 - 35) / (60 + 35)
    assert snapshot.metrics["midprice"].value == 100.025
    assert snapshot.metrics["microprice"].value == (100.05 * 10 + 100.00 * 5) / 15


def test_dom_sequence_gap_invalidates_until_resnapshot():
    as_of = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)
    state = OrderBookState(InstrumentSpec("AAA", "XNAS", 0.05, 2), AnalyticsConfig())
    levels = (BookLevel(Side.BID, 100.0, 10.0), BookLevel(Side.ASK, 100.05, 10.0))
    state.apply(BookSnapshotEvent("AAA", as_of, "fixture", "depth", 7, levels))

    gap = state.apply_modify(as_of, sequence=9, side=Side.BID, price=100.0, size=12.0)
    assert gap.state == "needs_snapshot"
    assert gap.metrics["book_imbalance_l1"].value is None

    recovered = state.apply(BookSnapshotEvent("AAA", as_of, "fixture", "depth", 20, levels))
    assert recovered.state == "valid"
    assert recovered.metrics["book_imbalance_l1"].value == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/market_analytics/test_dom.py`

Expected: collection fails because `dom.py` is absent.

- [ ] **Step 3: Write minimal implementation**

Maintain bid and ask maps keyed by normalized integer ticks. A snapshot clears both maps, records `expected_sequence = sequence + 1`, and restores validity. An incremental event is applied only when its sequence equals `expected_sequence`; otherwise set `needs_snapshot` and leave the book unchanged. `apply_modify` is a small test helper that creates a `BookUpdateEvent` and calls `apply`.

For N levels, sum the first N price levels on each side and return `(bid - ask) / (bid + ask)`. A valid empty book returns `0.0` with degraded metadata and reason `zero total displayed depth`. A missing/invalid book returns an unavailable result. Midprice and microprice require non-crossed best prices; microprice is `(ask * bid_size + bid * ask_size) / (bid_size + ask_size)`. Compute bps fields from midprice, use linear regression over normalized level distance for depth slope, top-N/total-N for concentration, and inverse-distance weights for weighted imbalance. Record add/cancel counters and trade-based depletion/replenishment in rolling configured windows.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/market_analytics/test_dom.py`

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```powershell
git add stock_analysis/market_analytics/dom.py tests/market_analytics/test_dom.py
git commit -m "feat: add order book state and dom metrics"
```

### Task 4: Add displayed-liquidity reliability and bounded DOM heatmap

**Files:**
- Modify: `stock_analysis/market_analytics/dom.py`
- Modify: `stock_analysis/market_analytics/config.py`
- Test: `tests/market_analytics/test_dom.py`

**Interfaces:**
- `LiquidityWall(price, side, size, normalized_size, distance_bps, age_ms, persistence_score, replenishment_score, cancel_score, executed_volume, reliability_score, metadata)`.
- `HeatmapObservation(timestamp, values, mode)`.
- `DOMHeatmap(max_observations, retention)` with `append`, `trim`, and `view(mode)`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import timedelta

from stock_analysis.market_analytics.models import BookLevel, BookSnapshotEvent, Side
from tests.market_analytics.support import T0


def make_state(*, wall_min_persistence_ms: int, heatmap_max_observations: int):
    from dataclasses import replace

    from stock_analysis.market_analytics.config import AnalyticsConfig
    from stock_analysis.market_analytics.dom import OrderBookState
    from stock_analysis.market_analytics.models import InstrumentSpec

    config = replace(
        AnalyticsConfig(),
        dom=replace(
            AnalyticsConfig().dom,
            wall_min_persistence_ms=wall_min_persistence_ms,
            heatmap_max_observations=heatmap_max_observations,
        ),
    )
    return OrderBookState(InstrumentSpec("AAA", "XNAS", 0.05, 2), config)


def snapshot_with_bid_size(price: float, size: float, timestamp=T0):
    return BookSnapshotEvent(
        "AAA", timestamp, "fixture", "depth", 1,
        (BookLevel(Side.BID, price, size), BookLevel(Side.ASK, price + 0.05, 10.0)),
    )


def test_wall_requires_persistence_and_heatmap_is_bounded():
    state = make_state(wall_min_persistence_ms=1_000, heatmap_max_observations=2)
    first = state.apply(snapshot_with_bid_size(100.0, 100.0))
    assert first.walls == ()

    state.apply(snapshot_with_bid_size(100.0, 100.0), as_of=first.as_of + timedelta(seconds=1))
    state.apply(snapshot_with_bid_size(100.0, 100.0), as_of=first.as_of + timedelta(seconds=2))
    result = state.snapshot(first.as_of + timedelta(seconds=2))

    assert result.walls[0].reliability_score > 0
    assert len(result.heatmap.observations) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/market_analytics/test_dom.py::test_wall_requires_persistence_and_heatmap_is_bounded`

Expected: FAIL because `DOMSnapshot` has no wall/heatmap implementation.

- [ ] **Step 3: Write minimal implementation**

Track per-price first-seen time, repeated appearances, size additions, cancellations, executions, and cancel-before-touch events. Normalize candidate size by the median of neighboring displayed levels and by the median total depth observed for the symbol. Emit a wall only when configured normalized-size, distance, and persistence thresholds pass. Calculate reliability as the configured weighted sum of clipped persistence, replenishment, executed-volume, repeated-appearance, and one-minus-cancel-rate scores. Name the result displayed-liquidity reliability; do not emit a spoofing label.

Store only the last configured observations in a `deque(maxlen=...)`; trim by timestamp as well as count. Implement absolute, signed, normalized, persistent, and add/cancel activity views from the bounded observations.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/market_analytics/test_dom.py`

Expected: all DOM tests pass.

- [ ] **Step 5: Commit**

```powershell
git add stock_analysis/market_analytics/dom.py stock_analysis/market_analytics/config.py tests/market_analytics/test_dom.py
git commit -m "feat: add displayed liquidity reliability"
```

### Task 5: Implement footprint, aggressor classification, CVD, and VI

**Files:**
- Create: `stock_analysis/market_analytics/order_flow.py`
- Modify: `stock_analysis/market_analytics/config.py`
- Test: `tests/market_analytics/test_order_flow.py`

**Interfaces:**
- `TradeClassifier.classify(trade, quote=None, previous_trade=None) -> TradeClassification`.
- `FootprintEngine.consume(trade, quote=None) -> FlowSnapshot`.
- `FootprintEngine.snapshot(as_of) -> FlowSnapshot`.
- `FootprintCell(bid_aggressor_volume, ask_aggressor_volume, total_volume, delta)`.
- `ImbalanceZone(bar_timestamp, price_low, price_high, direction, ratio, number_of_levels, volume, age, retested, failed, metadata)`.
- `FlowSnapshot.cells`, `flow_delta`, `cvd`, `quality`, `horizontal_imbalances`, `diagonal_imbalances`, and `stacked_imbalances`.

- [ ] **Step 1: Write the failing test**

```python
from stock_analysis.market_analytics.config import AnalyticsConfig
from stock_analysis.market_analytics.models import AggressorSide, InstrumentSpec, QuoteEvent, TradeEvent
from stock_analysis.market_analytics.order_flow import FootprintEngine
from tests.market_analytics.support import T0


def test_footprint_uses_explicit_side_and_detects_three_level_diagonal_stack():
    engine = FootprintEngine(InstrumentSpec("AAA", "XNAS", 0.05, 2), AnalyticsConfig())
    for price in (100.00, 100.05, 100.10):
        engine.consume(TradeEvent("AAA", T0, "fixture", "trades", price, 30.0, AggressorSide.BUY, str(price)))
        engine.consume(TradeEvent("AAA", T0, "fixture", "trades", price - 0.05, 5.0, AggressorSide.SELL, f"s{price}"))

    result = engine.snapshot(T0)
    assert result.flow_delta.value == 75.0
    assert result.cvd.value == 75.0
    assert len(result.stacked_imbalances) == 1
    assert result.stacked_imbalances[0].number_of_levels == 3


def test_quote_fallback_is_derived_and_unknown_trade_does_not_change_delta():
    engine = FootprintEngine(InstrumentSpec("AAA", "XNAS", 0.05, 2), AnalyticsConfig())
    engine.consume(TradeEvent("AAA", T0, "fixture", "trades", 100.05, 10.0, None, "buy"), QuoteEvent("AAA", T0, "fixture", "quotes", 100.0, 100.05, 20.0, 20.0))
    result = engine.consume(TradeEvent("AAA", T0, "fixture", "trades", 100.025, 10.0, None, "unknown"), None)

    assert result.flow_delta.value == 10.0
    assert result.quality.value < 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/market_analytics/test_order_flow.py`

Expected: collection fails because `order_flow.py` is absent.

- [ ] **Step 3: Write minimal implementation**

Use explicit `AggressorSide` with observed provenance and confidence `1.0`. Without a side, classify at or above the ask as buy and at or below the bid as sell with derived provenance and configured lower confidence; otherwise mark unknown and exclude its volume from delta. Aggregate cells by bar start and normalized price tick. Define delta as ask-aggressor volume minus bid-aggressor volume and CVD as cumulative bar delta.

Implement horizontal ratios at the same row and diagonal ratios comparing ask at P to bid one tick below P for bullish imbalance, and bid at P to ask one tick above P for bearish imbalance. A positive numerator with zero reference is a qualifying imbalance with a `None` ratio and explicit zero-reference reason. Find contiguous stacks using configured ratio and minimum-level settings. Keep retest/failure state in the zone object without guessing future price behavior. Set `FlowSnapshot.quality` below 100 whenever any positive-volume trade is unclassifiable.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/market_analytics/test_order_flow.py`

Expected: all footprint and VI tests pass.

- [ ] **Step 5: Commit**

```powershell
git add stock_analysis/market_analytics/order_flow.py stock_analysis/market_analytics/config.py tests/market_analytics/test_order_flow.py
git commit -m "feat: add footprint delta cvd and imbalances"
```

### Task 6: Add flow-delta exhaustion and flip events

**Files:**
- Modify: `stock_analysis/market_analytics/order_flow.py`
- Modify: `stock_analysis/market_analytics/config.py`
- Test: `tests/market_analytics/test_order_flow.py`

**Interfaces:**
- `BarSummary(timestamp, price, delta, cvd=None)`.
- `FlowDeltaExhaustionDetector.update(bar_summary) -> ExhaustionSnapshot`.
- `ExhaustionSnapshot.bullish_exhaustion_score`, `.bearish_exhaustion_score`, and `.flow_flip`.
- `FlowDeltaFlipEvent(timestamp, direction, pre_flip_exhaustion_score, delta_before, delta_after, cvd_slope_before, cvd_slope_after, confirmation_score)`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import timedelta

from stock_analysis.market_analytics.config import AnalyticsConfig
from stock_analysis.market_analytics.order_flow import BarSummary, FlowDeltaExhaustionDetector
from tests.market_analytics.support import T0


def test_buying_move_with_stalling_cvd_emits_bearish_exhaustion_then_flip():
    detector = FlowDeltaExhaustionDetector(AnalyticsConfig().flow)
    for index, (price, delta) in enumerate(((100, 20), (101, 18), (102, 4), (103, -8))):
        result = detector.update(BarSummary(T0 + timedelta(minutes=index), price, delta))

    assert result.bearish_exhaustion_score.value >= 0.5
    assert result.flow_flip is not None
    assert result.flow_flip.direction == "bearish"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/market_analytics/test_order_flow.py::test_buying_move_with_stalling_cvd_emits_bearish_exhaustion_then_flip`

Expected: FAIL because the detector and event do not exist.

- [ ] **Step 3: Write minimal implementation**

Maintain the configured rolling bars and calculate normalized price slope, CVD slope, delta slope, price-per-absolute-delta efficiency, divergence, and absorption. Calculate bearish exhaustion from a positive price slope combined with weakening positive delta/CVD confirmation; calculate bullish exhaustion as the sign-inverted case. Combine only configured feature weights and clip to `[0, 1]`. Detect a sign change in configured rolling delta or CVD slope and record before/after values. A flip remains distinct from dealer DEX flip and is only emitted when the configured confirmation score passes.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/market_analytics/test_order_flow.py`

Expected: all order-flow tests pass.

- [ ] **Step 5: Commit**

```powershell
git add stock_analysis/market_analytics/order_flow.py stock_analysis/market_analytics/config.py tests/market_analytics/test_order_flow.py
git commit -m "feat: add flow exhaustion and delta flips"
```

### Task 7: Implement exact/approximate session VWAP

**Files:**
- Create: `stock_analysis/market_analytics/vwap.py`
- Modify: `stock_analysis/market_analytics/config.py`
- Test: `tests/market_analytics/test_vwap.py`

**Interfaces:**
- `SessionClock.session_id(timestamp) -> str | None`.
- `VWAPEngine.consume_trade(trade) -> VWAPSnapshot`.
- `VWAPEngine.consume_bar(bar) -> VWAPSnapshot`.
- `VWAPSnapshot.metrics` with `session_vwap`, `distance_from_vwap_bps`, `vwap_zscore`, two configured upper/lower bands, and `vwap_slope`.

- [ ] **Step 1: Write the failing test**

```python
from stock_analysis.market_analytics.config import AnalyticsConfig
from stock_analysis.market_analytics.models import AggressorSide, BarEvent, Provenance, TradeEvent
from stock_analysis.market_analytics.vwap import VWAPEngine
from tests.market_analytics.support import T0, ny_utc


def test_exact_vwap_is_hand_calculated_and_resets_at_new_rth_session():
    engine = VWAPEngine(AnalyticsConfig())
    engine.consume_trade(TradeEvent("AAA", ny_utc(9, 31), "fixture", "trades", 100.0, 2.0, AggressorSide.BUY, "1"))
    result = engine.consume_trade(TradeEvent("AAA", ny_utc(9, 32), "fixture", "trades", 101.0, 1.0, AggressorSide.SELL, "2"))

    assert result.metrics["session_vwap"].value == (100 * 2 + 101) / 3
    assert result.metrics["session_vwap"].metadata.observed_or_modeled is Provenance.DERIVED_FROM_OBSERVED

    next_day = engine.consume_trade(TradeEvent("AAA", ny_utc(9, 31, day=3), "fixture", "trades", 110.0, 1.0, None, "3"))
    assert next_day.metrics["session_vwap"].value == 110.0


def test_bar_vwap_is_explicitly_approximate():
    result = VWAPEngine(AnalyticsConfig()).consume_bar(BarEvent("AAA", ny_utc(10, 0), "fixture", "bars", 99, 101, 98, 100, 10))
    assert result.metrics["session_vwap"].metadata.observed_or_modeled is Provenance.APPROXIMATE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/market_analytics/test_vwap.py`

Expected: collection fails because `vwap.py` is absent.

- [ ] **Step 3: Write minimal implementation**

Convert UTC timestamps to the configured session timezone. Include only RTH timestamps by default; reset accumulators when the session ID changes. Exact trades accumulate `price * volume`, volume, and squared-price volume for weighted dispersion. Bar mode uses `(high + low + close) / 3`, marks every result approximate, and never claims tick precision. Return unavailable when total volume is zero. Calculate bands as VWAP plus/minus configured dispersion multipliers and calculate slope from the configured recent VWAP samples.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/market_analytics/test_vwap.py`

Expected: all VWAP tests pass.

- [ ] **Step 5: Commit**

```powershell
git add stock_analysis/market_analytics/vwap.py stock_analysis/market_analytics/config.py tests/market_analytics/test_vwap.py
git commit -m "feat: add exact and approximate session vwap"
```

### Task 8: Implement TPO, value area, and single prints

**Files:**
- Create: `stock_analysis/market_analytics/profiles.py`
- Modify: `stock_analysis/market_analytics/config.py`
- Test: `tests/market_analytics/test_profiles.py`

**Interfaces:**
- `TPOEngine.consume_bar(bar) -> TPOProfileSnapshot`.
- `TPOEngine.finalize_session(session_id, as_of) -> TPOProfileSnapshot`.
- `TPOProfileSnapshot.metrics` with `tpo_poc`, `tpo_vah`, `tpo_val`, `tpo_midpoint`, counts above/below POC, initial-balance high/low, and single-print zones.
- `SinglePrintZone(low, high, creation_time, direction, confirmed, filled, first_retest_time, age_sessions)`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import timedelta

from stock_analysis.market_analytics.config import AnalyticsConfig
from stock_analysis.market_analytics.models import InstrumentSpec
from stock_analysis.market_analytics.profiles import TPOEngine
from stock_analysis.market_analytics.models import BarEvent
from tests.market_analytics.support import T0


def add_tpo_rows(engine, rows):
    for row, brackets in rows.items():
        for bracket_index, _ in enumerate(sorted(brackets)):
            engine.consume_bar(
                BarEvent(
                    "AAA", T0 + timedelta(minutes=30 * bracket_index), "fixture", "bars",
                    float(row), float(row), float(row), float(row), 1.0,
                )
            )


def test_tpo_poc_tie_breaks_to_closest_midpoint_then_lower_row():
    profile = TPOEngine(InstrumentSpec("AAA", "XNAS", 1.0, 0), AnalyticsConfig())
    add_tpo_rows(profile, {100: {"a"}, 101: {"a", "b"}, 102: {"a", "b"}, 103: {"a"}})

    result = profile.finalize_session("2026-01-02", T0)

    assert result.metrics["tpo_poc"].value == 101.0


def test_single_print_is_unconfirmed_while_developing_and_confirmed_at_close():
    profile = TPOEngine(InstrumentSpec("AAA", "XNAS", 1.0, 0), AnalyticsConfig())
    add_tpo_rows(profile, {100: {"a", "b"}, 101: {"a"}, 102: {"a", "b"}})
    developing = profile.snapshot(T0)
    assert developing.single_prints[0].confirmed is False
    closed = profile.finalize_session("2026-01-02", T0 + timedelta(hours=6))
    assert closed.single_prints[0].confirmed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/market_analytics/test_profiles.py`

Expected: collection fails because the profile module is absent.

- [ ] **Step 3: Write minimal implementation**

Assign each bar to a configured bracket and add the bracket ID once to every normalized row between low and high. Select TPO POC by highest count, then closest row to profile midpoint, then lower row. Expand value area from POC until cumulative TPO count reaches `ceil(total_count * value_area_pct)`, choosing the higher-count adjacent row, then the side closer to midpoint, then the lower row on a complete tie. Initial balance is the first configured number of brackets. A developing single print is an internal row with one TPO and configured neighboring confirmation conditions; mark it confirmed only on session finalization. Keep filled/retest fields explicit and unchanged until an observed later price event updates them.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/market_analytics/test_profiles.py`

Expected: all TPO tests pass.

- [ ] **Step 5: Commit**

```powershell
git add stock_analysis/market_analytics/profiles.py stock_analysis/market_analytics/config.py tests/market_analytics/test_profiles.py
git commit -m "feat: add tpo profiles and single prints"
```

### Task 9: Add exact/approximate rolling volume profiles and clusters

**Files:**
- Modify: `stock_analysis/market_analytics/profiles.py`
- Modify: `stock_analysis/market_analytics/config.py`
- Test: `tests/market_analytics/test_profiles.py`

**Interfaces:**
- `VolumeProfileEngine.consume_trade(trade) -> VolumeProfileSnapshot`.
- `VolumeProfileEngine.consume_bar(bar) -> VolumeProfileSnapshot`.
- `RollingVolumeProfileEngine.finalize_session(session_id, histogram, exact) -> Mapping[int, VolumeProfileSnapshot]`.
- `VolumeProfileSnapshot(window_sessions, vpoc, vah, val, profile_high, profile_low, total_volume, hvns, lvns, exact_or_approximate, metadata)`.
- `ProfileLevelCluster(center_price, member_levels, member_windows, cluster_strength, distance_from_spot_bps, support_or_resistance_context)`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import timedelta

from stock_analysis.market_analytics.config import AnalyticsConfig
from stock_analysis.market_analytics.models import BarEvent, InstrumentSpec, Provenance
from stock_analysis.market_analytics.profiles import RollingVolumeProfileEngine, VolumeProfileEngine
from tests.market_analytics.support import T0


def test_rolling_volume_profile_contains_only_completed_sessions():
    engine = RollingVolumeProfileEngine(InstrumentSpec("AAA", "XNAS", 1.0, 0), AnalyticsConfig())
    engine.finalize_session("s1", {100: 10.0}, exact=True)
    engine.finalize_session("s2", {101: 20.0}, exact=True)

    before_close = engine.snapshot(as_of=T0, current_session="s3")
    assert before_close[2].total_volume == 30.0
    assert before_close[2].vpoc == 101.0

    engine.finalize_session("s3", {99: 100.0}, exact=True)
    after_close = engine.snapshot(as_of=T0 + timedelta(days=1), current_session=None)
    assert after_close[2].total_volume == 130.0


def test_bar_profile_is_approximate_and_value_area_uses_highest_volume_row():
    result = VolumeProfileEngine(InstrumentSpec("AAA", "XNAS", 1.0, 0), AnalyticsConfig()).consume_bar(
        BarEvent("AAA", T0, "fixture", "bars", 99, 103, 98, 102, 10)
    )
    assert result.exact_or_approximate == "approximate"
    assert result.metadata.observed_or_modeled is Provenance.APPROXIMATE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/market_analytics/test_profiles.py -k volume`

Expected: FAIL because the rolling volume-profile classes do not exist.

- [ ] **Step 3: Write minimal implementation**

Exact mode increments the trade’s normalized tick by trade volume. Bar mode assigns all bar volume to the configured representative price and marks the profile approximate; it does not distribute volume across the candle range. On session finalization, copy the histogram into each configured rolling window, append it to a bounded deque, and subtract evicted session bins from that window’s running histogram. Calculate VPOC from highest volume with deterministic price tie-breaking, expand value area by adjacent volume until the configured percentage, and identify HVN/LVN using configured neighbor-volume thresholds. Cluster profile levels using tick tolerance, bps tolerance, and optional ATR distance; include all source windows and level sources in each cluster.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/market_analytics/test_profiles.py`

Expected: all TPO and volume-profile tests pass.

- [ ] **Step 5: Commit**

```powershell
git add stock_analysis/market_analytics/profiles.py stock_analysis/market_analytics/config.py tests/market_analytics/test_profiles.py
git commit -m "feat: add rolling volume profiles"
```

### Task 10: Normalize options and calculate IV-by-strike analytics

**Files:**
- Create: `stock_analysis/market_analytics/options.py`
- Modify: `stock_analysis/market_analytics/config.py`
- Test: `tests/market_analytics/test_options.py`

**Interfaces:**
- `OptionContract(underlying, expiration, strike, call_put, contract_multiplier, bid, ask, mid, last, volume, open_interest, iv, delta, gamma, theta, vega, quote_timestamp, trade_timestamp, oi_as_of, greeks_source, iv_source, adjusted, adjustment_reason)` is the validated accepted record produced from `OptionContractInput`.
- `OptionChainNormalizer.normalize(snapshot) -> NormalizedOptionChain(accepted, rejected)`.
- `IVSurfaceAnalyzer.analyze(chain: NormalizedOptionChain | OptionChainEvent, spot, as_of) -> IVSurfaceSnapshot`.
- `EuropeanBlackScholes.greeks(spot, contract, volatility, as_of) -> Greeks`.
- `IVSurfaceSnapshot.by_expiration`, `atm_iv`, `skew`, `slope`, `curvature`, anomaly fields, and `heatmap`.

- [ ] **Step 1: Write the failing test**

```python
from stock_analysis.market_analytics.config import AnalyticsConfig
from stock_analysis.market_analytics.models import Provenance
from stock_analysis.market_analytics.options import IVSurfaceAnalyzer, OptionChainNormalizer
from tests.market_analytics.support import T0, raw_option


def option_snapshot_with(*, spot=100.0, contracts=None, invalid_contracts=()):
    from stock_analysis.market_analytics.models import OptionChainEvent

    accepted = tuple(contracts) if contracts is not None else (raw_option(),)
    return OptionChainEvent("AAA", T0, "fixture", "options", spot, accepted + tuple(invalid_contracts))


def test_option_normalization_rejects_invalid_oi_spread_and_multiplier():
    chain = OptionChainNormalizer().normalize(option_snapshot_with(
        invalid_contracts=(
            raw_option(open_interest=-1),
            raw_option(bid=2.0, ask=1.0),
            raw_option(contract_multiplier=0),
        )
    ))

    assert len(chain.accepted) == 1
    assert {item.reason for item in chain.rejected} == {"negative open interest", "bid above ask", "invalid multiplier"}


def test_iv_surface_selects_nearest_atm_and_marks_provider_values_observed():
    snapshot = option_snapshot_with(spot=100.0, contracts=(
        raw_option(strike=99, iv=0.21), raw_option(strike=101, iv=0.25)
    ))
    result = IVSurfaceAnalyzer(AnalyticsConfig()).analyze(snapshot, 100.0, T0)

    assert result.atm_iv.value == 0.21
    assert result.atm_iv.metadata.observed_or_modeled is Provenance.OBSERVED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/market_analytics/test_options.py`

Expected: collection fails because `options.py` is absent.

- [ ] **Step 3: Write minimal implementation**

Validate expiration, strike, positive multiplier, nonnegative volume/OI, bid/ask ordering, positive reasonable prices, stale underlying context, and adjusted-contract policy. Return accepted contracts plus rejection records; do not coerce invalid OI to zero. Use provider IV/Greeks as observed when present. Calculate nearest-spot ATM IV, per-expiration skew/slope/curvature, robust median/MAD anomaly scores, quote-quality weighting, and expiration-by-strike heatmap cells. Implement European Black–Scholes delta/gamma/theta/vega and bisection IV solving with explicit approximate provenance and early-exercise methodology text. The model is available only when configured.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/market_analytics/test_options.py`

Expected: all options normalization and IV tests pass.

- [ ] **Step 5: Commit**

```powershell
git add stock_analysis/market_analytics/options.py stock_analysis/market_analytics/config.py tests/market_analytics/test_options.py
git commit -m "feat: add option normalization and iv surface"
```

### Task 11: Implement modeled GEX, DEX, flips, walls, and saturation

**Files:**
- Create: `stock_analysis/market_analytics/positioning.py`
- Modify: `stock_analysis/market_analytics/config.py`
- Test: `tests/market_analytics/test_positioning.py`

**Interfaces:**
- `DealerPositionModel.position_sign(contract) -> int` and `.description`.
- `ClassicOIOProxy` and `UnsignedExposure`.
- `PositioningEngine.analyze(chain: NormalizedOptionChain | OptionChainEvent, spot, as_of) -> PositioningSnapshot`.
- `PositioningSnapshot.net_gex`, `positive_gex`, `negative_gex`, `gex_by_strike`, `gex_by_expiration`, `gamma_flip`, `net_dex`, `dex_by_strike`, `dealer_dex_flip`, `dealer_hedge_saturation`, `call_wall`, `put_wall`, and model metadata.
- `FlipResult(all_roots, nearest_root, residuals, slope_near_spot, metadata)`.

- [ ] **Step 1: Write the failing test**

```python
from stock_analysis.market_analytics.config import AnalyticsConfig
from stock_analysis.market_analytics.models import Provenance
from stock_analysis.market_analytics.positioning import PositioningEngine
from tests.market_analytics.support import T0, raw_option


def gamma_crossing_chain():
    from stock_analysis.market_analytics.models import CallPut

    return option_snapshot_with(contracts=(
        raw_option(call_put=CallPut.CALL, strike=95.0, gamma=0.01, delta=0.75),
        raw_option(call_put=CallPut.PUT, strike=105.0, gamma=0.04, delta=-0.25),
    ))


def all_positive_gamma_chain():
    from stock_analysis.market_analytics.models import CallPut

    return option_snapshot_with(contracts=(
        raw_option(call_put=CallPut.CALL, strike=95.0, gamma=0.01),
        raw_option(call_put=CallPut.CALL, strike=105.0, gamma=0.04),
    ))


def test_gex_scales_with_open_interest_and_multiplier_and_missing_oi_is_unavailable():
    chain = option_snapshot_with(contracts=(raw_option(gamma=0.02, open_interest=10, contract_multiplier=100),))
    engine = PositioningEngine(AnalyticsConfig())
    first = engine.analyze(chain, spot=100.0, as_of=T0)

    doubled = option_snapshot_with(contracts=(raw_option(gamma=0.02, open_interest=20, contract_multiplier=100),))
    second = engine.analyze(doubled, spot=100.0, as_of=T0)
    missing = option_snapshot_with(contracts=(raw_option(gamma=0.02, open_interest=None, contract_multiplier=100),))
    unavailable = engine.analyze(missing, spot=100.0, as_of=T0)

    assert second.net_gex.value == 2 * first.net_gex.value
    assert unavailable.net_gex.value is None


def test_gamma_flip_returns_zero_residual_and_no_root_returns_none():
    engine = PositioningEngine(AnalyticsConfig())
    crossing = engine.analyze(gamma_crossing_chain(), spot=100.0, as_of=T0)
    no_root = engine.analyze(all_positive_gamma_chain(), spot=100.0, as_of=T0)

    assert crossing.gamma_flip.nearest_root is not None
    assert abs(crossing.gamma_flip.nearest_root.residual) <= AnalyticsConfig().options.root_residual_tolerance
    assert no_root.gamma_flip.nearest_root is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/market_analytics/test_positioning.py`

Expected: collection fails because `positioning.py` is absent.

- [ ] **Step 3: Write minimal implementation**

Centralize classic signs as call `+1`, put `-1`; unsigned exposure uses positive magnitude for both sides and applies absolute delta for unsigned DEX. Reject chains without valid OI for exposure metrics. Calculate each option’s GEX as `position_sign * gamma * OI * multiplier * spot**2 * 0.01` and DEX as `position_sign * delta * OI * multiplier * spot`, then aggregate by strike, expiration, DTE bucket, and full chain. Include contract multiplier in every calculation.

For flips, evaluate the selected exposure function across the configured spot grid, hold each contract’s IV sticky by strike, obtain hypothetical Greeks from provider values only when the model can reprice them, interpolate each sign-change interval, re-evaluate the residual at the interpolated root, and retain only roots within tolerance. Return every valid root and the nearest root; return no root when none qualifies. Build gamma/DEX clusters and conventional call/put walls only for the classic model. Calculate hedge saturation from configured high-absolute-delta fraction, absolute DEX, absolute gamma, and local DEX slope, normalize each component, and label it heuristic modeled exposure.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/market_analytics/test_positioning.py`

Expected: all positioning tests pass.

- [ ] **Step 5: Commit**

```powershell
git add stock_analysis/market_analytics/positioning.py stock_analysis/market_analytics/config.py tests/market_analytics/test_positioning.py
git commit -m "feat: add modeled gex dex and exposure flips"
```

### Task 12: Wire the analytics pipeline, fixtures, serialization, and CLI demo

**Files:**
- Create: `stock_analysis/market_analytics/pipeline.py`
- Create: `stock_analysis/market_analytics/fixtures.py`
- Create: `stock_analysis/market_analytics/serialization.py`
- Modify: `stock_analysis/market_analytics/__init__.py`
- Modify: `stock_analysis/cli.py`
- Test: `tests/market_analytics/test_pipeline.py`
- Test: `tests/market_analytics/test_serialization.py`
- Test: `tests/test_cli_router.py`

**Interfaces:**
- `AnalyticsPipeline(instrument, config, capabilities, provider="fixture")`.
- `AnalyticsPipeline.consume(event) -> AnalyticsSnapshot`.
- `AnalyticsPipeline.finalize(as_of) -> AnalyticsSnapshot`.
- `AnalyticsSnapshot(as_of, symbol, dom, flow, vwap, profiles, options, positioning, data_quality)`.
- `build_full_fixture() -> tuple[ReplayProvider, InstrumentSpec, AnalyticsConfig]`.
- `to_jsonable(value) -> JSON-compatible object` and `from_jsonable(...)` for supported snapshots.
- CLI command: `python -m stock_analysis analytics demo`.

- [ ] **Step 1: Write the failing test**

```python
from stock_analysis.market_analytics.fixtures import build_full_fixture
from stock_analysis.market_analytics.models import AnalyticsSnapshot, Provenance
from stock_analysis.market_analytics.pipeline import AnalyticsPipeline
from stock_analysis.market_analytics.replay import ReplayEngine
from stock_analysis.market_analytics.serialization import from_jsonable, to_jsonable


def run_fixture_to_final_snapshot():
    provider, instrument, config = build_full_fixture()
    pipeline = AnalyticsPipeline(instrument, config, provider.capabilities)
    return ReplayEngine().run(provider, pipeline, instrument.symbol)[-1]


def test_full_fixture_replay_uses_one_pipeline_and_exposes_provenance():
    provider, instrument, config = build_full_fixture()
    pipeline = AnalyticsPipeline(instrument, config, provider.capabilities)
    snapshots = ReplayEngine().run(provider, pipeline, instrument.symbol)

    final = snapshots[-1]
    assert final.dom.metrics["book_imbalance_l5"].metadata.provider == "fixture"
    assert final.flow.flow_delta.metadata.observed_or_modeled in {Provenance.OBSERVED, Provenance.DERIVED_FROM_OBSERVED}
    assert final.positioning.net_gex.metadata.observed_or_modeled is Provenance.MODELED


def test_snapshot_json_round_trip_preserves_unavailable_values():
    snapshot = run_fixture_to_final_snapshot()
    restored = from_jsonable(to_jsonable(snapshot), AnalyticsSnapshot)

    assert restored.positioning.net_gex.value == snapshot.positioning.net_gex.value
    assert restored.dom.metrics["book_imbalance_l10"].value == snapshot.dom.metrics["book_imbalance_l10"].value
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/market_analytics/test_pipeline.py tests/market_analytics/test_serialization.py`

Expected: collection fails because the pipeline, fixtures, and serializers are absent.

- [ ] **Step 3: Write minimal implementation**

Route each event type once: quotes to DOM and classifier context, book events to DOM, trades to DOM/flow/VWAP/exact VP, bars to flow/VWAP/TPO/approximate VP, session transitions to all session engines, and option snapshots to normalization/IV/positioning. Preserve the event timestamp as snapshot `as_of`. Aggregate data-quality results from component metadata without converting unavailable metrics to zero.

Build small deterministic fixtures containing the five-level book, sequence gap/recovery, three-trade VWAP, a three-level diagonal VI stack, TPO tie, single-print profile, rolling profile sessions, normalized options, one GEX root, and one no-root chain. Serialize enums, datetimes, decimals/floats, dataclasses, `None`, and mappings into JSON-safe values with an explicit type tag only where needed for round trips. Export the stable public classes from `__init__.py`.

Add `analytics` to the root `NAMESPACES` and parser help. Dispatch lazily to a small demo runner so root help does not import analytics or any live-data package. The demo must print stable JSON and return `0`; it must not call the network.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/market_analytics tests/test_cli_router.py`

Expected: all new analytics and CLI tests pass.

- [ ] **Step 5: Commit**

```powershell
git add stock_analysis/market_analytics stock_analysis/cli.py tests/market_analytics tests/test_cli_router.py
git commit -m "feat: add replayable analytics pipeline demo"
```

### Task 13: Add methodology documentation and source inventory

**Files:**
- Create: `docs/architecture/14-Market-Analytics.md`
- Create: `docs/methodology/market-analytics-methodology.md`
- Modify: `README.md`
- Modify: `SOURCE-MANIFEST.md`
- Test: `tests/market_analytics/test_documentation.py`

**Interfaces:**
- Documentation must name the exact fixture command and the offline-only boundary.
- Methodology must contain the formulas and units for OBI, microprice, delta/CVD, VWAP, TPO POC/value area, VPOC, GEX, DEX, flips, and saturation.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path


def test_methodology_documents_required_distinctions():
    text = Path("docs/methodology/market-analytics-methodology.md").read_text(encoding="utf-8")
    for phrase in (
        "public option OI does not disclose dealer inventory",
        "flow delta is not dealer DEX",
        "flow delta exhaustion is not dealer hedge saturation",
        "TPO POC counts time-price occurrences",
        "volume POC counts traded volume",
        "candle-derived volume profile is approximate",
    ):
        assert phrase in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/market_analytics/test_documentation.py`

Expected: FAIL because the methodology file does not exist.

- [ ] **Step 3: Write minimal implementation**

Document the event contracts, fixture capabilities, state recovery, all formulas, default configuration, provenance statuses, approximate fallbacks, modeled-position assumptions, and deferred live/API/UI boundary. Add the demo command to the root README and list every added file in `SOURCE-MANIFEST.md`. Keep claims limited to behavior covered by tests.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/market_analytics/test_documentation.py`

Expected: documentation test passes.

- [ ] **Step 5: Commit**

```powershell
git add docs/architecture/14-Market-Analytics.md docs/methodology/market-analytics-methodology.md README.md SOURCE-MANIFEST.md tests/market_analytics/test_documentation.py
git commit -m "docs: document market analytics methodology"
```

### Task 14: Run complete verification and make no unsupported claims

**Files:**
- Modify: only files required by verification failures from Tasks 1–13.

- [ ] **Step 1: Run the complete offline test suite**

Run: `python -m pytest -q`

Expected: exit code `0`, zero failures, and no unexpected errors or warnings.

- [ ] **Step 2: Run scoped lint and formatting checks**

Run:

```powershell
python -m ruff check stock_analysis/market_analytics stock_analysis/cli.py tests/market_analytics tests/test_cli_router.py
python -m ruff format --check stock_analysis/market_analytics stock_analysis/cli.py tests/market_analytics tests/test_cli_router.py
```

Expected: both commands exit `0`.

- [ ] **Step 3: Run type checking**

Run: `python -m mypy stock_analysis/market_analytics`

Expected: exit code `0` with no type errors.

- [ ] **Step 4: Run the deterministic demonstration and CLI help**

Run:

```powershell
python -m stock_analysis analytics demo
python -m stock_analysis --help
python -m stock_analysis analytics --help
```

Expected: demo exits `0` with stable JSON; both help commands exit `0` without network access.

- [ ] **Step 5: Verify no secrets or generated artifacts were added**

Run:

```powershell
git status --short
rg -n -i "api[_-]?key|secret|token|password|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY" stock_analysis docs tests
```

Expected: only intentional untracked pre-existing directories remain; the secret scan returns no matches in added implementation/docs/tests.

- [ ] **Step 6: Review the requirement matrix and report limitations**

Confirm each Solution A item has a source module, fixture, and test. Report the exact commands and counts from fresh output. State that real L2/OPRA adapters, persistence, API/UI, screener/confluence, and forward research are intentionally deferred; do not claim live readiness.
