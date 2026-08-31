# REPRODUCIBLE SIMULATION AND VERIFICATION PLATFORM

This repository is centered on [`backtest-engine`](backtest-engine/): a Python 3.12+ platform for turning a market-data snapshot and a strategy specification into an auditable research result. It separates fast discovery from event-driven validation, records the inputs behind every run, and fails explicitly when an engine cannot honor a requested assumption.

The goal is not to manufacture a favorable backtest. The goal is to make a result reproducible, inspectable, and difficult to obtain through accidental leakage.

## What It Demonstrates

- A shared pandas signal contract across VectorBT discovery and Backtrader validation.
- Next-bar-open execution to prevent a signal from trading on the same observation that created it.
- Point-in-time universe filtering with listing and delisting boundaries.
- Walk-forward utilities that optimize only in-sample, freeze parameters out-of-sample, and reject overlapping OOS windows.
- Named execution-cost models with explicit engine compatibility checks.
- Immutable, content-addressed run manifests containing data, universe, strategy, configuration, code, seed, and runtime provenance.
- Atomic result persistence, an append-only JSONL experiment index, and corruption checks with actionable file and line errors.
- Reloadable reports and comparisons that use persisted results instead of silently rerunning a strategy.

## Architecture

```text
CSV / yfinance / Stooq
          |
          v
validate + normalize -> partitioned Parquet clean store
          |
          +-> point-in-time universe filter
          |
          v
pandas strategy signals
          |
          +-> VectorBT discovery
          +-> Backtrader validation
          +-> NautilusTrader replay (optional)
          |
          v
canonical BacktestResult + benchmark + metrics
          |
          v
result.json / manifest.json / metrics.json / report.html
          |
          v
append-only experiments.jsonl -> compare persisted runs
```

The strategy layer is deliberately engine-neutral. Adapters translate the same signals into engine-specific execution while returning one canonical result model. See [`backtest-engine/README.md`](backtest-engine/README.md) for the command reference and [`docs/architecture/12-Backtest-Engine.md`](docs/architecture/12-Backtest-Engine.md) for the design background.

## Validation Philosophy

The platform treats research controls as executable constraints:

- **Anti-leakage:** signals are shifted to the next bar for VectorBT fills; signal frames and persisted results are validated before use.
- **Point-in-time universes:** an optional membership CSV filters every bar by `list_date` and `delist_date`, reducing survivorship bias rather than assuming today's constituents existed historically.
- **Walk-forward evaluation:** rolling, half-open in-sample and out-of-sample windows keep optimization away from future observations and stitch only OOS equity.
- **Reproducibility:** stable manifest fields are hashed; run timestamps and IDs remain provenance rather than changing experiment identity.
- **Artifact integrity:** manifests are write-once for a run identity, result writes are atomic, mismatched or malformed artifacts raise explicit errors, and corrupt JSONL records identify their line number.
- **No silent fallback:** missing clean data does not become synthetic data. Synthetic runs require `--synthetic`, unsupported costs fail fast, and unavailable benchmarks are labeled unavailable.

These controls improve confidence in a simulation; they do not establish that a strategy will perform in live markets.

## Quick Start

Use Python 3.12 or newer. From the repository root on PowerShell:

```powershell
cd backtest-engine
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Run the exact deterministic, network-free demonstration:

```powershell
python -m scripts.run_offline_demo
```

It ingests the checked-in CSV fixture, applies point-in-time universe membership, runs zero-cost and proportional-cost VectorBT simulations, persists and reloads their artifacts, indexes and compares both runs, and creates offline HTML reports. It prints a JSON result with `"status": "PASS"` or exits nonzero.

## Research Workflow

### 1. Ingest

Create the canonical partitioned clean-data store from a local CSV:

```powershell
bte ingest --source csv --input tests/fixtures/offline_demo/bars.csv --symbol DEMO --data-root demo-data
```

Network-backed `yfinance` and `stooq` sources are also available. Input validation rejects malformed OHLCV data instead of persisting it.

### 2. Discover

Run fast VectorBT discovery against persisted data and an optional point-in-time universe:

```powershell
bte discover --strategy sma_cross --symbol DEMO --data-root demo-data --universe-csv tests/fixtures/offline_demo/universe.csv --cost zero
```

For an explicit synthetic smoke run:

```powershell
bte discover --strategy sma_cross --synthetic --days 756 --seed 42
```

### 3. Validate

Re-run the strategy through Backtrader's event-driven path:

```powershell
bte validate --strategy sma_cross --symbol DEMO --data-root demo-data --universe-csv tests/fixtures/offline_demo/universe.csv --cost us_equity_pershare
```

The Python validation package also provides walk-forward, parameter-stability, permutation, and Monte Carlo tools. These are library APIs, not separate `bte` subcommands.

### 4. Compare

Compare explicit persisted runs using IDs printed by `discover` or `validate`:

```powershell
bte compare --run-id <first-run-id> --run-id <second-run-id>
bte compare --run-id <first-run-id> --run-id <second-run-id> --json
```

### 5. Report

Regenerate a report from the saved canonical result without rerunning the strategy:

```powershell
bte report --run-id <run-id>
```

Each normal run writes `result.json`, `manifest.json`, `metrics.json`, and `report.html` under `backtest-engine/outputs/<run-id>/`, then appends its summary to `backtest-engine/outputs/experiments.jsonl`.

## Verification

From `backtest-engine/` with the development dependencies installed:

```powershell
python -m pytest -q
python -m ruff check .
python -m mypy src/backtest_engine
python -m scripts.run_offline_demo
python -m scripts.benchmark_runtime
```

The benchmark reports workload and environment metadata; it intentionally does not impose a machine-dependent CI timing threshold.

## Scope and Limitations

- VectorBT has exact cost support here only for zero and proportional models. Per-share commissions with minimums and nonlinear volume-impact models cannot be represented exactly and fail fast; use Backtrader for those models.
- The built-in buy-and-hold benchmark requires exactly one symbol. Multiasset results record the benchmark as unavailable rather than inventing an aggregation rule.
- Point-in-time correctness depends on the supplied universe history. The included sample and demo fixtures are not a complete survivorship-free market database.
- Market-data sources can contain errors, revisions, missing observations, and corporate-action differences. Validation and optional source cross-checks reduce, but do not eliminate, this risk.
- NautilusTrader is an optional daily-bar replay adapter installed with `python -m pip install -e ".[execution]"`. It currently supports only the zero-cost model and is not a paper- or live-trading integration.
- The platform models research assumptions; it does not model every exchange, broker, latency, liquidity, tax, borrow, or market-impact condition.

## Other Repository Content

- [`scion-omaha-bots/`](scion-omaha-bots/) contains separate experimental Scion and Omaha stock-research and paper-tracking tools. They are not integrated consumers of `backtest-engine`, and they do not execute real trades.
- [`frameworks/`](frameworks/) contains research methodologies, prompts, risk notes, data-source references, and agent profiles used by those experiments.
- [`docs/`](docs/) contains architecture and operating notes.
- [`SOURCE-MANIFEST.md`](SOURCE-MANIFEST.md) records the repository's source inventory and exclusions.

## License

Licensed under the [MIT License](LICENSE). This repository is for research and education and is not financial advice.
