# backtest-engine

Research-first backtesting engine. Three-phase workflow on free data:

- **Phase 1 — Discovery**: VectorBT vectorized parameter sweeps
- **Phase 2 — Validation**: Backtrader event-driven with realistic fills/slippage/commissions
- **Phase 3 — Deployment**: NautilusTrader execution-parity replay; bridge to paper/live

Full design: see `PLAN.md` / `Backtest Engine Build Plan.md` in Obsidian.

## Install

Requires Python 3.12 or newer.

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pre-commit install
```

## Usage

```
# Real persisted clean data is the default.
bte discover --strategy sma_cross --symbol SPY --start 2020-01-01 --end 2024-12-31
bte validate --strategy sma_cross --symbol SPY --start 2020-01-01 --end 2024-12-31
bte report   --run-id <run-id-from-discover-or-validate>

# Synthetic data is explicit and intended for offline demos.
bte discover --strategy sma_cross --synthetic --days 756 --seed 42

# Optional daily-bar replay through NautilusTrader.
pip install -e ".[execution]"
bte replay --strategy sma_cross --symbol SPY --start 2020-01-01 --end 2024-12-31
```

Each successful run writes the complete `result.json`, `metrics.json`, and
`report.html` under `outputs/<run-id>/` and prints the artifact paths. Report
generation reloads `result.json`; it does not rerun the strategy.

For the reproducible real-data acceptance workflow, run
`python -m scripts.run_v1_acceptance` from this directory after the clean cache
is available.

## Status

v1 research and validation milestones M0-M8 are implemented. The M9 boundary
adds optional NautilusTrader daily-bar replay with the same strategy contract.
The current replay adapter supports the zero-cost model and is not paper/live
trading integration.

## License

MIT.
