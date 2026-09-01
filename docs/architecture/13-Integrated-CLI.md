# Integrated CLI

The canonical command is `stock-analysis`.

## Initial namespaces

- `stock-analysis scion`: forwards commands to the Scion bot.
- `stock-analysis omaha`: forwards commands to the Omaha bot.
- `stock-analysis backtest`: forwards commands to the Backtest Engine.

Examples:

```text
stock-analysis scion --watchlist LULU,PFE screener
stock-analysis omaha --watchlist KO,PG run
stock-analysis backtest discover --strategy sma_cross --synthetic --days 200 --seed 42 --cost zero
```

## Shared namespaces

These are added only after the initial routing layer is stable:

- `stock-analysis portfolio combined`
- `stock-analysis tracking report`
- `stock-analysis tracking feedback`
- `stock-analysis tracking daily-check`
- `stock-analysis tracking show`
- `stock-analysis credit status`
- `stock-analysis debate AAPL --compile`

A shared command must identify `--bot scion` or `--bot omaha` when it can write state or send an alert.

## Compatibility

These existing commands remain supported:

- `python main.py`
- `python buffett_main.py`
- `bte`

The root router calls Python entry points directly. It does not use a shell or a subprocess.

## Help and side effects

The root help and namespace help must work without network access. Help must not call yfinance, VectorBT, Backtrader, Plotly, OpenBB, credentials, messaging, or vault services. Help must not write state files.

## Exit codes

- `0`: command completed successfully.
- `2`: argparse used its normal parser-error status.
- Any other nonzero value: import, configuration, or domain failure.

The root command does not automatically run both bots or connect a live screener to a backtest. Those workflows require separate contracts.
