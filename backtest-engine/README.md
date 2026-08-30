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
bte discover --strategy sma_cross --days 756 --seed 42
bte validate --strategy sma_cross --days 756 --seed 42
bte report   --run-id <run-id-from-discover-or-validate>
```

Each successful discover or validate run writes `metrics.json` and `report.html`
under `outputs/<run-id>/` and prints both artifact paths.

## Status

v1 targets milestones M0-M8 (research + validation).
v2 (M9) opens NautilusTrader replay and paper-trading integration.

## License

MIT.
