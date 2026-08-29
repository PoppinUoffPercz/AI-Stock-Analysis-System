# backtest-engine

Research-first backtesting engine. Three-phase workflow on free data:

- **Phase 1 — Discovery**: VectorBT vectorized parameter sweeps
- **Phase 2 — Validation**: Backtrader event-driven with realistic fills/slippage/commissions
- **Phase 3 — Deployment**: NautilusTrader execution-parity replay; bridge to paper/live

Full design: see `PLAN.md` / `Backtest Engine Build Plan.md` in Obsidian.

## Install

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pre-commit install
```

## Usage

```
bte discover --strategy sma_cross --universe spx --start 2010-01-01 --end 2025-12-31
bte validate --strategy sma_cross --universe spx --start 2010-01-01 --end 2025-12-31
bte report   --run <run_id>
```

## Status

v1 targets milestones M0-M8 (research + validation).
v2 (M9) opens NautilusTrader replay and paper-trading integration.

## License

MIT.
