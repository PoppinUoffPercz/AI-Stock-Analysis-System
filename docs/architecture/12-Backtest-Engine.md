---
title: "Backtest Engine — How to Test & Hypothesize Strategies"
date: 2026-08-03
tags:
  - docs
  - architecture
  - trading
  - guide
---

# Backtest Engine — How to Test & Hypothesize Strategies

> Three-phase framework in `./backtest-engine`: Phase 1 discovery (VectorBT) → Phase 2 validation (Backtrader event-driven, realistic fills/slippage) → optional Phase 3 daily-bar replay (NautilusTrader). All open-source, no paid data.

See 12-Backtest-Engine for full design; this is the practical workflow guide.

---

## 1. Before you test anything: write the hypothesis

Every test must start with `strategies/<name>/hypothesis.md`. Pattern (see existing `strategies/sma_cross/`, `strategies/bollinger_breakout/`, `strategies/rsi_reversion/`):

```markdown
# <name> hypothesis
**Hypothesis**: One sentence — what market inefficiency does this capture?
Expected behavior: (bull / bear / choppy regime expectations)
Risk we want to rule out via M6 validation:
- **Look-ahead**: ...
- **Overfitting / parameter spike**: ...
Failure modes:
- <specific condition that means abandon>
```

Without this file, you have no benchmark to compare results against — any result is just a number. See 01-Dual-Agent-System for the Scion-Bot framework that this integrates with (portfolio tracking, debate engine, credit monitor).

---

## 2. Register your strategy (2 minutes)

Add to `src/backtest_engine/strategy/registry.py`:

```python
from backtest_engine.strategy.bollinger import bollinger_breakout  # your file
REGISTRY["your_name"] = (your_signal_factory, {"param": default})
```

Then `bte strats` shows it. The CLI (`cli.py`) pulls from this registry; no registry entry = no CLI command.

---

## 3. Signal factory contract

Your function must return a DataFrame with index aligned to `ohlc.index` and exactly these boolean columns:

| Column | Meaning |
| :--- | :--- |
| `entry` | `True` on the bar the signal triggers. Fill at next bar open (enforced by adapter). |
| `exit` | `True` on the bar the exit condition hits. Fill at next bar open. |

No future-bar leakage. See `builtin.py`, `bollinger.py`, `rsi_reversion.py`. Example (simplified SMA cross):

```python
def sma_cross(ohlc, params={"fast":10,"slow":30}):
    close = ohlc["close"]
    ma_f = close.rolling(params["fast"]).mean()
    ma_s = close.rolling(params["slow"]).mean()
    out = pd.DataFrame(index=ohlc.index)
    out["entry"] = ((ma_f > ma_s) & (ma_f.shift(1) <= ma_s.shift(1))).astype(bool)
    out["exit"] = ((ma_f < ma_s) & (ma_f.shift(1) >= ma_s.shift(1))).astype(bool)
    return out
```

---

## 4. The testing workflow (layered gates)

Run in order. Each gate is a filter — stop at the first failure.

### Gate A — CLI smoke (zero cost, explicit synthetic data)

```bash
bte discover --strategy <name> --synthetic --days 200 --seed 42 --cost zero
```

Expected: a JSON metrics block with `sharpe`, `total_return`, `profit_factor`, `max_drawdown`. Check `metrics/core.py` `bias_audit()` flags (`high_sharpe`, `too_smooth`, `thin_trades`, `low_wfe`). Any `True` = investigate before continuing.

### Gate B — Cost-sensitive validation (Backtrader, realistic execution)

```bash
bte validate --strategy <name> --symbol SPY --start 2020-01-01 --end 2024-12-31 --cost us_equity_pershare
```

Compare VBT (`discover`) vs BT (`validate`) equity curves. A gap > 5% = execution/slippage issue; the framework expects some gap due to fill-timing differences but a large gap indicates the cost model doesn't match reality.

### Gate C — Full bench (all 4 validation layers)

```bash
PYTHONPATH=src python notebooks/strategy_bench.py <name>
```

The notebook uses a deterministic synthetic scaffold for fast exploration. The real cached-data acceptance workflow is:

```bash
python -m scripts.run_v1_acceptance --start 2020-01-01 --end 2024-12-31
```

It runs a small SPY/QQQ/IWM sweep, the VBT/BT comparison, walk-forward, Monte Carlo, random-entry permutation, report generation, and optional Nautilus replay. Artifacts are written below `outputs/v1-acceptance/`.

This runs: single run → walk-forward (rolling IS/OOS) → Monte Carlo (trade-order shuffle) → permutation vs random-entry H0 → verdict (`deploy? True/False`).

**Decision rules (per `metrics/core.py` `bias_audit` + `walk_forward` WFE):**

| Gate result | Meaning |
| :--- | :--- |
| `WFE >= 0.5` | Robust across market regimes |
| `WFE < 0.5` | Overfit — strategy optimized to one regime |
| `perm p <= 0.05` | Signal survives random-entry test |
| `perm p > 0.05` | No significant entry edge |
| `high_sharpe == False`, `too_smooth == False`, `thin_trades == False` | No obvious bias smoke gun |

The bench runs `deploy? False` honestly — it kills weak signals rather than inflating them. See `notebooks/strategy_bench.py` line 204: `wf_ok = wf.wfe >= 0.5`, `perm_ok = perm.p_value <= 0.05`, `bias_clean = not flags["any_flag"]`, `deploy = wf_ok and perm_ok and bias_clean`.

---

## 5. Data and universe discipline

All data sources are free-tier only (plan §4 and M1):

| Source | What it pulls | Caveat |
| :--- | :--- | :--- |
| yfinance | Daily OHLCV + corp actions | Rate-limited; throttle set to 1.5s + retries |
| Stooq (CSV download) | Bulk EOD cross-check | No SDK; manual format alignment |
| Alpaca paper account | Backup minute bars (v2 / M9) | 200 calls/min; ~10yr 1m bars |

Universe file (`data/universe/*.csv`) tracks `symbol`, `list_date`, `delist_date`, `delist_reason`. The loader (`data/universe.py`) drops delisted tickers after their `delist_date`, preventing look-ahead via dead-name persistence. The residual survivorship bias (only listed tickers have clean free data) is documented; upgrade to a paid point-in-time feed is the documented future path.

The CLI reads persisted clean data by default from `data/clean/<SYMBOL>/<YEAR>.parquet`. Use `--synthetic` explicitly for an offline demo. Missing requested real data is an error; the CLI never silently replaces it with synthetic bars.

---

## 6. How this integrates with vault trade analysis

This framework directly connects to:

- 01-Dual-Agent-System — Scion-Bot (Burry-style swing) portfolio / risk management rules; this framework validates the signal layer that feeds it.
- 11-Debate-Engine — the Bull/Bear/Judge debate framework produces a consensus modifier; use the `permutation` layer here to check if the debate-modified strategy survives random-entry noise.
- 09-Performance-Tracker — `BacktestResult.trades` feeds into trade-log tracking; the `portfolio/` layer's position-size and exposure tracking is the direct consumer of the validated results.
- 10-OpenBB-Integration — data sources; the engine's `data/sources/` layer uses `yfinance` through this same OpenBB connection.

---

## 7. Key files for reproduction

| File / Command | What to do with it |
| :--- | :--- |
| `notebooks/strategy_bench.py` | The full hypothesis-test pipeline. Run: `python notebooks/strategy_bench.py <name>` |
| `strategies/` | Every registered strategy with its `hypothesis.md`. Copy the pattern for new ideas. |
| `tests/test_smoke_m0.py` | Skeleton plumbing tests |
| `tests/test_m2_vbt.py` | VBT adapter smoke (end-to-end) |
| `tests/test_m4_bt.py` | Backtrader adapter smoke (end-to-end) |
| `tests/test_m5_portability.py` | Cross-engine identity test |
| `tests/test_costs.py` | Commission + slippage property tests |
| `tests/test_m6_validation.py` | Validation layer (walk-forward, MC, permutation, stability) |
| `tests/test_m7_reporting.py` | Tearsheet + plotly + bias-audit |
| `tests/test_m8_cli.py` | CLI end-to-end |
| `src/backtest_engine/result.py` | Complete `BacktestResult` persistence and reload |
| `src/backtest_engine/strategy/adapters/nautilus_adapter.py` | Optional NautilusTrader daily-bar replay boundary |
| `scripts/run_v1_acceptance.py` | Reproducible cached-data acceptance run |
| `PLAN.md` + `system-guide/12-Backtest-Engine.md` (this) | Design doc + usage guide |

---

## 8. Quick command map

```
# Setup
pip install -e ".[dev]"
pre-commit install

# Discover a strategy on persisted clean data
python -m backtest_engine.cli discover --strategy sma_cross --symbol SPY --start 2020-01-01 --end 2024-12-31

# Explicit synthetic smoke run
python -m backtest_engine.cli discover --strategy sma_cross --synthetic --days 750 --seed 99 --cost zero

# Validate with realistic execution
python -m backtest_engine.cli validate --strategy sma_cross --symbol SPY --start 2020-01-01 --end 2024-12-31 --cost us_equity_pershare

# Optional NautilusTrader daily-bar replay (zero-cost boundary)
pip install -e ".[execution]"
python -m backtest_engine.cli replay --strategy sma_cross --symbol SPY --start 2020-01-01 --end 2024-12-31

# List all registered strategies
python -m backtest_engine.cli strats

# Generate tearsheet for a run
python -m backtest_engine.cli report --run-id <id>

# Full validation chain (discover -> WF -> MC -> perm -> verdict)
python -m scripts.run_v1_acceptance --start 2020-01-01 --end 2024-12-31

# Check health of project
ruff check src tests
ruff format --check src tests
mypy --config-file=pyproject.toml src
pytest -q
```

The report command reloads the persisted `result.json` and does not rerun the
strategy. Nautilus replay records native order/fill events; its daily equity
series is reconstructed by marking those native fills to the identical
canonical close bars, and the current boundary accepts only `--cost zero`.

---

## Related (Vault Links)

- Backtest Engine Build Plan — original spec with all milestones
- Backtesting Concepts — framework comparison notes
- Trading Strategy Workflow — broader quant context
- 01-Dual-Agent-System — portfolio framework this feeds into
- 09-Performance-Tracker — trade tracking + reporting
- 11-Debate-Engine — debate score modifier for new tickers
- `notebooks/strategy_bench.py` — reproducible full validation chain (run it)
