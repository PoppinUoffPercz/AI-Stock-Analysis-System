# Backtest Engine Build Plan

> Research-first, staged toward paper/live. Hybrid stack. All open source. US equities daily+EOD.
> Synthesized from web research on vectorized vs event-driven engines, the Python backtesting library landscape, free data sources, and overfitting / validation best practices.

Related: Backtesting Concepts · Trading Strategy Workflow

---

## 1. Goals & Constraints

### Primary goals
1. **Research throughput** — rapidly evaluate strategy ideas for edge, run parameter sweeps, cross-asset tests.
2. **Realistic validation** — simulate fills, slippage, commissions, partials, path-dependent logic.
3. **Staged path to live** — surviving strategies get a path to paper and live execution without rewrite.

### Locked-in decisions
| Area | Decision |
|---|---|
| Stack | Hybrid: **VectorBT** (research) → **Backtrader** (validation; event-driven) → **NautilusTrader** (execution realism; live-parity). Custom glue where needed. |
| Build vs buy | **No paid products.** Open-source libraries only. Anything missing, we code ourselves. |
| Universe | US equities, **daily + EOD** OHLCV (no intraday in v1). |
| Data | **Free tier only**: yfinance, Stooq CSV dumps, Alpaca free/paper account (200 calls/min, ~10yr minute bars available for a later phase). |
| Validation | **Full rigor**: walk-forward analysis + Monte Carlo trade-order permutation + parameter-stability heatmaps + held-out OOS. |
| Mission | **Both, staged.** Research first; design for portability; execution plumbing deferred until needed. |

### Non-goals (v1)
- Intraday / tick / L2 order-book simulation.
- Crypto / futures / forex.
- HFT / microstructure modeling.
- Live broker wiring (paper-trading integration is the v2 boundary).

---

## 2. Three-Phase Workflow (the spine of the design)

Mirrors the consensus workflow from the research (VectorBT docs, python.financial, QuantStart):

```
Phase 1: DISCOVERY (VectorBT)
   └── fast parameter sweeps, signal hypothesis testing, robustness checks

Phase 2: VALIDATION (Backtrader — event-driven)
   └── realistic fills, slippage, commissions, path-dependent exits, walk-forward OOS

Phase 3: DEPLOYMENT (NautilusTrader — execution-parity replay)
   └── identical strategy logic with microstructure realism; bridge to paper/live
```

**Portability rule**: a strategy must migrate across phases with minimal rewrite. Strategy logic lives in a thin, framework-agnostic `StrategySpec` (signals + risk rules + sizing). Adapter classes bind that spec to each engine. Rewrite cost = execution mechanics only, never signal logic.

---

## 3. Architecture

### 3.1 Repo structure

```
backtest-engine/
├── data/                       # Raw + normalized data cache (parquet)
│   ├── raw/                    # Per-source raw downloads (CSV/parquet)
│   ├── clean/                  # Normalized OHLCV, corp-action adjusted, deduped
│   └── universe/               # Ticker lists, membership history, listings/delistings
├── src/backtest_engine/
│   ├── data/
│   │   ├── sources/            # yfinance, stooq, alpaca adapters (one class each)
│   │   ├── ingest.py           # Fetch + cache + dedupe
│   │   ├── clean.py            # Adjust splits/divs, align timestamps, validate OHLCV
│   │   ├── universe.py         # Universe membership; survivorship-bias handling
│   │   └── store.py            # Parquet I/O, schema, partitions
│   ├── strategy/
│   │   ├── spec.py             # StrategySpec dataclass (signals, params, risk rules)
│   │   ├── registry.py         # Strategy registry / discovery
│   │   └── adapters/           # vbt_adapter.py, bt_adapter.py, nautilus_adapter.py
│   ├── execution/
│   │   ├── costs.py            # Commission + slippage models (per asset class)
│   │   └── fills.py            # Fill simulation for backtrader event loop
│   ├── portfolio/
│   │   ├── positions.py        # Position tracking, lots, P&L
│   │   ├── risk.py             # Exposure caps, max-DD, sector limits
│   │   └── sizing.py           # Fixed-fractional, vol-target, Kelly
│   ├── validation/
│   │   ├── walk_forward.py     # Rolling in-sample/out-sample window engine
│   │   ├── monte_carlo.py       # Resampled trade-order permutation
│   │   ├── permutation.py      # Significance vs H0 (random entry) tests
│   │   └── stability.py        # Parameter-stability heatmaps + degradation curves
│   ├── metrics/
│   │   ├── core.py             # Sharpe, Sortino, Calmar, max-DD, CAGR, hit rate
│   │   ├── tearsheet.py        # QuantStats-style report HTML
│   │   └── attribution.py      # Per-trade, per-period, per-regime breakdowns
│   ├── pipeline/
│   │   ├── discovery.py        # Phase 1 runner (VectorBT sweeps)
│   │   ├── validation.py       # Phase 2 runner (Backtrader event loop)
│   │   └── replay.py           # Phase 3 runner (NautilusTrader replay)
│   ├── cli.py                  # `bte discover|validate|replay|report`
│   └── config.py               # pydantic settings: data dirs, cost models, capital
├── tests/                      # pytest; golden tests against published strategy results
├── notebooks/                  # Exploration; never the source of truth
├── strategies/                 # User strategy library (YAML + Python)
├── outputs/                    # Run artifacts: equity curves, logs, tearsheets
├── pyproject.toml
└── PLAN.md
```

### 3.2 Engine adapter interface

Each adapter implements a common protocol so strategies stay portable:

```python
class EngineAdapter(Protocol):
    def run(self, spec: StrategySpec, data: UniverseData, costs: CostModel,
            capital: float, **kw) -> BacktestResult: ...
```

- **VBTAdapter** — wraps `vbt.Portfolio.from_signals`. Broadcasts parameter grids. Vectorized result (fast; optimistic on fills).
- **BTAdapter** — wraps Backtrader's `Cerebro`. Custom `Broker` subclass injecting our `CostModel` and slippage. Custom `Analyzer` writing to `BacktestResult`. This is the realism gate.
- **NautilusAdapter** (v2) — wraps `NautilusTrader`'s backtest node. Same `StrategySpec`, with limit/stop/TIF support. Pluggable toward the live node later.

### 3.3 StrategySpec — the portability contract

```python
@dataclass
class StrategySpec:
    name: str
    signals: SignalFunc            # (bars) -> entry/exit indicators, framework-neutral
    params: dict                  # sweeps live here in Phase 1
    risk: RiskRules               # max position, max DD, sector exposure caps
    sizing: SizingRule             # e.g. vol-target 20%
    cost_model: CostModel          # commissions + slippage assumptions
    universe_ref: str              # points to saved universe
```

Signals are pure functions over pandas Series; adapters translate to each framework's idioms. Risk rules and cost models are owned by the engine, **not** re-implemented per framework — this is the leak we close by writing our own glue.

---

## 4. Data Layer (free sources, daily EOD)

### 4.1 Sources (priority order)

| Source | Role | Why |
|---|---|---|
| **yfinance** | Primary bulk OHLCV | Free, decent history, splits/divs auto-adjusted. Rate-limited; throttle + cache aggressively. |
| **Stooq** (CSV) | Cross-check / gap fill | Free bulk downloads of decades of EOD data; good for validating yfinance output. |
| **Alpaca** (paper) | Backup minute data (future) | 200 calls/min, ~10yr bars w/ paper account. Only if we add intraday in a later phase. |

### 4.2 Storage

- **Format**: parquet, partitioned by `symbol/year`. One file per symbol-year for cheap reads.
- **Schema**: `timestamp (UTC, tz-aware), open, high, low, close, volume, adj_open, adj_high, adj_low, adj_close, dividend, split_ratio, source`.
- **Locality**: all cache on local disk first; no cloud in v1.

### 4.3 Cleaning pipeline (once per ingest, then on demand)

1. **Validate** OHLC sanity: `high >= max(open,close,low)`, `low <= min(...)`, `volume >= 0`, no NaN within active trading dates.
2. **Adjust** for splits and dividends: store both raw and adjusted prices. **Use the adjusted series for signals** to avoid look-ahead from future corp-action adjustments — research flagged this as a common bias source. Default back-adjusted.
3. **Dedupe** across sources when cross-checking Stooq vs yfinance; flag disagreements > 0.5%.
4. **Track boundary**: mark each symbol's first and last active date. Feeds the survivorship handler.

### 4.4 Survivorship bias handling (even on free data)

Free sources don't ship delisted-ticker history cleanly, so we mitigate, not eliminate:

- Explicit **universe membership file** (CSV) listing each ticker with `list_date` / `delist_date` / `delist_reason`.
- The universe loader **drops a ticker from the tradable set after its delist date** and refuses to use post-delist prices — prevents look-ahead via dead-name persistence.
- v1 documents residual bias; a paid survivorship-free feed (Polygon/Databento) is the documented upgrade path.

---

## 5. Execution Realism Models

Vectorized engines get these wrong; event-driven engines get them right. We own them in one place and feed into every adapter.

### 5.1 Commission model
- Per-share: `$0.005/share` (ZeroPro/Alpaca-style) or flat `$1/order` fallback — configurable.
- Min floor and max cap.

### 5.2 Slippage model (pluggable; default = volume-impact)
- **Linear impact**: `slip = base_bps + k * (order_size / bar_volume)`.
- **Square-root impact** (advanced): `slip = k * sqrt(order_size / bar_volume)` — more realistic for larger orders.
- **Fixed bps**: sanity check.

### 5.3 Fill assumptions
- Default: market orders fill at `next_bar_open ± slippage`. Limit/stop orders filled only if `(bar_low <= limit <= bar_high)` intrabar; partial fills modeled via volume fraction.
- Research explicitly warned: *"off-by-one indexing — using current bar close to fill a same-bar trade"* is the #1 look-ahead vector. Phase 2 (Backtrader) enforces next-bar fill by construction; Phase 1 (VBT) is configured with `init_cash`/`upon_op` settings forcing next-open execution to close the loophole.

### 5.4 Latency / decision lag
- v1: decisions at bar close, execution at next bar open. Documented and consistent across adapters.
- v2 (Nautilus): configurable latency model.

---

## 6. Validation Layer (full rigor)

### 6.1 Walk-forward analysis
- **Rolling windows**: e.g. 5y in-sample (IS) → 1y out-of-sample (OOS), rolled annually.
- Re-optimize params on IS, apply fixed params on OOS, stitch OOS equity curves.
- Report **walk-forward efficiency** = OOS-CAGR / IS-CAGR; flag <50% as overfit.
- Minimum 5 IS/OOS pairs; aim for 10+ for confidence.

### 6.2 Monte Carlo trade-order permutation
- Take realized trade list; resample trade *order* (shuffle) 1,000–10,000x keeping the same trade distribution.
- Report the distribution of max drawdown. Trade-order permutation cannot vary terminal wealth or Sharpe because both are order-invariant, so this method does not report them.
- Use the separately named `bootstrap_trade_returns` operation when terminal-wealth or Sharpe distributions are required; `block_bootstrap_returns` remains the autocorrelation-preserving variant.

### 6.3 Permutation test vs H0
- H0: "no edge — entries are random."
- Generate 1,000 variants of the strategy with the *same exit logic* but **random entry dates**. Compare real strategy's metric to the random-entry distribution. p-value = fraction of random variants that beat the real one.
- Cheapest, most underused robustness check the research surfaced.

### 6.4 Parameter stability heatmap
- For each sweep, compute the metric surface over the 2D (or 3D) parameter grid.
- A robust strategy has a **broad, smooth plateau**, not a single spike. Spikes = curve fit.
- Plot param degradation over walk-forward IS windows: drifting optimal params is fine; jumping is a red flag.

### 6.5 OOS discipline
- Hold out the **last 20–30% of the data chronologically** as untouched OOS. Optimize *only* on the IS subset. Touching OOS parameters after seeing OOS results = forfeit the test (research called this *"meta-overfitting"*).
- Document every OOS run in `runs.log` with timestamp, params, and metric — so we can't silently re-tune.

---

## 7. Metrics & Reporting

- **Core**: total return, CAGR, vol, Sharpe, Sortino, Calmar, max-DD + duration, hit rate, profit factor, avg win/loss, turnover, exposure.
- **Tearsheet**: QuantStats-style HTML report (we use `quantstats` — open source) with equity curve, drawdown underwater plot, monthly returns heatmap, return distribution.
- **Attribution**: per-regime (bull/bear/sideways using 200D-MA on SPY), per-year, per-sector.
- **Bias audit panel**: flags if (a) Sharpe > 1.5, (b) equity curve "too smooth", (c) trade count < 30, (d) OOS-CAGR/IS-CAGR < 50%. Research repeatedly cited these as look-ahead/overfit smoke guns.

---

## 8. Bias Defenses (cross-cutting — every phase)

| Bias | Defense |
|---|---|
| **Look-ahead** | Event-driven Phase 2 closes the loophole by design. Phase 1 set to `next_open` fills. Audit script greps for `.shift(-1)`, `.iloc[i+1]`, future-dated corp-action leakage. |
| **Survivorship** | Universe membership file with delist dates; load tickers as-of a date. Documented residual bias on free data. |
| **Overfitting** | Walk-forward + permutation test + stability heatmap + OOS lock. |
| **Data-snooping** | Run-log of every OOS test; strategies tagged with a hypothesis *before* looking at data (`strategies/<name>/hypothesis.md`). |
| **Cost omission** | `CostModel` is **mandatory** in `StrategySpec`. No backtest runs without one. |

---

## 9. Python Dependencies

### Core
- `python>=3.11`
- `numpy`, `pandas` (time-series algebra)
- `pyarrow` (parquet I/O)
- `pydantic` (config + spec validation)

### Phase 1 — Discovery
- `vectorbt` (open source — paid PRO exists; we use OSS only; Numba JIT is in OSS)
- `numba` (transitive; we also use directly for any custom kernels)

### Phase 2 — Validation
- `backtrader` (event-driven, mature, GPL; works on modern Python via maintained forks like `backtrader2`)

### Phase 3 — Execution parity (v2; include in deps from start for consistency)
- `nautilus_trader` (Rust-backed event-driven; contains a backtest node + live node)

### Data
- `yfinance` (bulk EOD)
- `requests` (Stooq CSV pulls; no SDK)
- `alpaca-py` (Alpaca free/paper account, v2 only)
- `pandas-ta` or `ta` (indicators — prefer `pandas-ta` for breadth)

### Validation / stats
- `scipy` (permutation tests, distributions)
- `statsmodels` (block bootstrap, regression diagnostics)
- `scikit-learn` (Walk-forward, TimeSeriesSplit, parameter-search orchestration)

### Reporting
- `quantstats` (tearsheets)
- `plotly` (interactive equity/drawdown/heatmap)
- `matplotlib` (static fallback)

### Engineering
- `pytest`, `pytest-cov`, `hypothesis` (property tests for cost/fill math)
- `ruff` (lint + format)
- `mypy` (types, especially on the `StrategySpec` contract)
- `pre-commit` (enforce lint + tests on commit)

> **VectorBT PRO note**: paid PRO features (probabilistic fills, callbacks) are deliberately skipped. Where we need a PRO feature, we implement it ourselves (e.g. our own slippage/fill logic in the Backtrader broker). Stack stays 100% open.

---

## 10. Build Sequence (mini-milestones)

Each milestone ships something runnable. Verify with `pytest` before moving on.

### M0 — Skeleton (0.5 day)
- Repo, `pyproject.toml`, ruff/mypy/pytest config, pre-commit, CI placeholder.
- `config.py` with pydantic settings; `cli.py` stub.

### M1 — Data layer (1-2 days)
- yfinance + Stooq adapters → parquet cache.
- Clean + validate (OHLC sanity, split/div adj, dedupe cross-source).
- Universe membership file loader; as-of point-in-time ticker set.
- Smoke test: load SPY 2010-2025, validate row count, adj-close sanity.

### M2 — Phase 1: Discovery engine (1-2 days)
- `VBTAdapter` wrapping `vbt.Portfolio.from_signals`.
- Parameter sweep harness; output `BacktestResult` with core metrics.
- Required setting: `upon_op`-equivalent forcing next-open fills.
- Smoke test: SMA crossover on SPY, 2-param sweep, returns Sharpe.

### M3 — Cost + execution models (1 day)
- `CostModel` (commission + slippage, pluggable).
- Slippage: linear-impact default, sqrt-impact option.
- Property tests via `hypothesis` on fill math (no negative fills, costs never negative).

### M4 — Phase 2: Validation engine (2-3 days)
- `BTAdapter` over Backtrader.
- Custom `Broker` injecting our `CostModel`.
- Custom `Analyzer` writing to `BacktestResult` (same schema as Phase 1).
- Smoke test: same SMA crossover, compare VBT vs BT equity curves within tolerance; flag deltas as cost/slippage effects.

### M5 — StrategySpec + portability (1 day)
- `StrategySpec` dataclass + registry.
- Refactor M2/M4 adapters to consume the spec (signals + risk + sizing).
- Cross-engine identity test: same spec, same data, same costs → VBT and BT results agree within documented tolerance.

### M6 — Validation layer (3-4 days)
- Walk-forward runner with stitched OOS equity; WFE report.
- Monte Carlo trade-order + block-bootstrap returns; percentile bands.
- Permutation test vs random-entry H0.
- Parameter-stability heatmap.
- All four report into the tearsheet.

### M7 — Reporting (1-2 days)
- QuantStats integration; bias-audit panel.
- Plotly dashboards (equity, DD underwater, param heatmap, MC distribution, WF OOS curve).
- Clickable HTML output written to `outputs/<run_id>/report.html`.

### M8 — CLI + docs (1 day)
- `bte discover|validate|replay|report` commands.
- README; `strategies/` folder with 2 example strategies (SMA cross, RSI mean-reversion) each annotated with its hypothesis file.

### M9 (v2 boundary) — Phase 3: NautilusTrader replay
- `NautilusAdapter` for the same `StrategySpec`.
- Compare Backtrader vs Nautilus on identical data → quantify execution-realism gap.
- Define the paper/live integration path (broker TBD; Alpaca paper is the free option).

---

## 11. Open Risks / Things to Decide Before M1

1. **Backtrader on modern Python** — upstream repo stalled ~2021. Commit to either (a) the community `backtrader2` fork, or (b) pin an older Python for Backtrader while Phase 1/3 run 3.11+. **Recommendation**: try `backtrader2` first; confirm it imports on Python 3.11 in M0.
2. **NautilusTrader supports US daily equities cleanly?** — confirm in M0 that its data API ingests our parquet schema. If friction is high, defer Phase 3 adapter and use Backtrader as the production-realism gate for v1.
3. **yfinance rate limits** — throttled client from day one: 1-2 sec/request sleep + retry-with-backoff. Stooq is the fallback if we hit walls.
4. **Survivorship on free data** — residual bias is real. Decide document + proceed, or postpone until a paid feed. **Recommendation**: document and proceed; cap strategy universe to S&P 500 components as-of each backtest date (membership history free via Wikipedia scraping + Stooq).
5. **VectorBT OSS vs PRO** — confirm `from_signals`, parameter broadcasting, portfolio stats are all in OSS. If `from_signals`'s fill options are too naive, drop to the lower-level `Portfolio.from_orders` API — confirm in M2.

---

## 12. Definition of Done (v1)

- [ ] Pull SPY + 50-ticker universe EOD 2010-2025 from free sources, cached locally.
- [ ] Run an SMA-crossover param sweep in Phase 1 → `BacktestResult`.
- [ ] Run the same strategy through Phase 2 with realistic costs → equity within 2% of Phase 1 net of cost delta.
- [ ] Run walk-forward (5 IS/OOS pairs) → stitched OOS equity + WFE.
- [ ] Run Monte Carlo (1000 shuffles) → 5/50/95 percentile DD bands.
- [ ] Run permutation test → p-value vs random-entry H0.
- [ ] Report tearsheet with bias-audit panel written to `outputs/`.
- [ ] `pytest` green, `ruff` clean, `mypy` clean.

Once v1 is green, M9 opens the path to NautilusTrader replay and paper-trading integration.

---

## 13. Research Sources (for reference)

- Timothy Kimutai, "How I Built an Event-Driven Backtesting Engine in Python" (Medium, 2025) — 6-layer event-driven architecture; lookahead-bias structural defenses.
- python.financial, "Python Backtesting Landscape (2026)" — research → replay → live workflow; VBT PRO vs NautilusTrader positioning.
- QuantStart, "Event-Driven Backtesting with Python" — original event-queue + handler pattern.
- IBKR Campus, "Vector-Based vs Event-Based Backtesting" — tradeoffs, fill assumptions, risk controls.
- Pineify, "Python Backtesting Libraries Compared" (2026) — library feature matrix incl. license/live-trading columns.
- Trading Dude (Medium), "Battle-Tested Backtesters" — VectorBT vs Zipline vs Backtrader practical comparison.
- Trading Dude (Medium), "Beyond yFinance" — data API landscape; Alpaca free-tier details.
- Deep et al., "Rigorous Walk-Forward Validation Framework" (arXiv 2512.12924, 2025) — 34-fold walk-forward, permutation testing, honest-reporting protocol.
- QuantInsti, "Walk-Forward Optimization" — IS/OOS mechanics, WFE, limitations.
- Surmount, "Walk-Forward Analysis vs Backtesting" — meta-overfitting pitfalls, fitness-function shopping.
- Alpaca-py docs — historical bar API for free-tier minute data (v2 endpoint).

---

## Related notes
- Backtesting Concepts
- Trading Strategy Workflow
