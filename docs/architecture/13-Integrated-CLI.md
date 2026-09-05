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
stock-analysis portfolio combined
stock-analysis research run --bot scion
```

## Shared namespaces

These shared namespaces are available through the stable routing layer:

- `stock-analysis portfolio combined`
- `stock-analysis tracking report`
- `stock-analysis tracking feedback`
- `stock-analysis tracking daily-check`
- `stock-analysis tracking show`
- `stock-analysis credit status`
- `stock-analysis debate AAPL --compile`
- `stock-analysis research run --bot scion|omaha`

A shared command must identify `--bot scion` or `--bot omaha` when it can write state or send an alert.

Path options come before the namespace and preserve the existing defaults when
omitted:

```text
stock-analysis --state-root PATH --data-root PATH --outputs-root PATH backtest discover ...
```

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

## Startup and routing check

On Windows, a local check on 2026-08-31 used five fresh subprocesses for help
and three fresh subprocesses for a 60-day synthetic SMA run. The median times
were:

| Command | Median |
| :--- | ---: |
| `stock-analysis --help` | 92 ms |
| `bte --help` | 1,048 ms |
| direct `bte discover` | 7,116 ms |
| `stock-analysis backtest discover` | 7,100 ms |

The backtest commands used separate temporary output roots. The integrated
router calls the Python runner directly, so it added no measured startup or
subprocess overhead to the synthetic run. These figures are a local check, not
a machine-independent performance guarantee.
