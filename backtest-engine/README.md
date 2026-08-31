# backtest-engine

The primary executable in the repository: a Python 3.12+ backtesting platform built for reproducible simulation and independent verification.

- **Discover:** VectorBT runs fast vectorized experiments.
- **Validate:** Backtrader replays the same pandas signals through an event-driven engine with per-fill cost modeling.
- **Replay:** optional NautilusTrader daily-bar execution replay.
- **Verify:** canonical results, immutable manifests, reports, benchmarks, and an append-only JSONL experiment index preserve the evidence behind each run.

Signals execute at the next bar's open. Real persisted data is the default; synthetic data is never selected implicitly. A point-in-time universe CSV can filter bars before signal generation and execution.

## Install

From this directory on PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Offline Acceptance Demo

```powershell
python -m scripts.run_offline_demo
```

This deterministic, network-free command uses checked-in CSV fixtures to exercise ingestion, point-in-time filtering, strategy execution, exact zero/proportional VectorBT costs, benchmarking, persistence, manifest reload, JSONL indexing, comparison, and offline HTML reporting. Use `--output-root <path>` to change its artifact directory.

## CLI Workflow

```powershell
# Ingest a local fixture into data/clean/<SYMBOL>/<YEAR>.parquet.
bte ingest --source csv --input tests/fixtures/offline_demo/bars.csv --symbol DEMO --data-root demo-data

# Discovery and event-driven validation on that persisted dataset.
bte discover --strategy sma_cross --symbol DEMO --data-root demo-data --universe-csv tests/fixtures/offline_demo/universe.csv --cost zero
bte validate --strategy sma_cross --symbol DEMO --data-root demo-data --universe-csv tests/fixtures/offline_demo/universe.csv --cost us_equity_pershare

# Compare run IDs printed by the preceding commands.
bte compare --run-id <first-run-id> --run-id <second-run-id>
bte compare --run-id <first-run-id> --run-id <second-run-id> --json

# Reload a persisted result and regenerate its report without rerunning.
bte report --run-id <run-id>

# Explicit deterministic synthetic discovery.
bte discover --strategy sma_cross --synthetic --days 756 --seed 42
```

Successful normal runs write `result.json`, `manifest.json`, `metrics.json`, and `report.html` under `outputs/<run-id>/` and append to `outputs/experiments.jsonl`. Missing clean data, malformed or mismatched artifacts, corrupt index records, invalid universes, and unsupported engine assumptions produce explicit errors.

## Optional Replay

```powershell
python -m pip install -e ".[execution]"
bte replay --strategy sma_cross --symbol DEMO --data-root demo-data --universe-csv tests/fixtures/offline_demo/universe.csv --cost zero
```

NautilusTrader replay currently supports daily bars and the zero-cost model only. It is an execution-parity experiment, not paper/live integration.

## Cost Fidelity and Benchmarks

VectorBT supports exact zero and proportional costs in this project. It rejects per-share commissions with minimums and nonlinear volume-impact slippage because approximating them would make cross-engine results misleading. Backtrader supports the named per-fill models.

The included buy-and-hold benchmark covers one symbol from first available open to final close with no costs. It is explicitly unavailable for multiasset results.

## Validation and Reproducibility

The library includes walk-forward, parameter-stability, permutation, and Monte Carlo validation utilities. Walk-forward optimization sees only in-sample data, freezes parameters for each out-of-sample fold, and rejects overlapping OOS windows.

Every pipeline result carries a manifest identity derived from strategy, parameters, engine, cost configuration, filtered data content, universe content, random seed, relevant arguments, Git state, Python, and dependency versions. Manifests are immutable for a run ID; result writes are atomic; loading validates schemas and manifest/result consistency; malformed JSONL records report the corrupt line.

## Verification

```powershell
python -m pytest -q
python -m ruff check .
python -m mypy src/backtest_engine
python -m scripts.run_offline_demo
python -m scripts.benchmark_runtime
```

The runtime benchmark records its workload and environment but has no machine-dependent pass/fail threshold. A real-data acceptance workflow is available as `python -m scripts.run_v1_acceptance` after its expected clean cache has been populated.

## License

[MIT](../LICENSE).
