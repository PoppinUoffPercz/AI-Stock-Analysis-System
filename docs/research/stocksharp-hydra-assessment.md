# StockSharp Hydra assessment

Date: 2026-08-31

## Question

Would StockSharp Hydra and its market-data retrieval layer help our Python stock-analysis workflow?

## Finding

Yes as an optional acquisition and storage sidecar. No as a direct replacement for the Python ingest layer or as source code to embed in this MIT project without a separate license review.

## What Hydra provides

StockSharp describes Hydra as software that automatically loads and stores market data. The official documentation covers instruments, candles, tick trades, order books, and other market-data types; historical and real-time sources; local storage; API access; and export. It can build candles from ticks, Level 1, order books, or smaller candle intervals. Sources are selected per instrument, data type, timeframe, and date period, and downloads can be scheduled.

Sources: [StockSharp README](https://github.com/StockSharp/StockSharp/blob/master/README.md#hydra), [Hydra documentation](https://doc.stocksharp.com/en/topics/hydra), [Hydra first-start workflow](https://doc.stocksharp.com/en/topics/hydra/first_start), [market-data conversion](https://doc.stocksharp.com/en/topics/hydra/working_with_data/any_market_data_types).

## Fetcher and integration shape

The current repository exposes the retrieval side through `RemoteMarketDataDrive` and `RemoteStorageClient`, rather than a Python-native fetcher. The remote drive connects to a Hydra server through a StockSharp message adapter, defaults to `127.0.0.1:5002`, supports credentials, looks up securities, enumerates available data types and dates, and loads per-date data streams. The repository's save-to-local sample copies those remote streams into a local StockSharp storage drive.

Sources: [RemoteMarketDataDrive.cs](https://github.com/StockSharp/StockSharp/blob/master/Algo/Storages/RemoteMarketDataDrive.cs), [RemoteStorageClient.cs](https://github.com/StockSharp/StockSharp/blob/master/Algo/Storages/RemoteStorageClient.cs), [Hydra server save-to-local sample](https://github.com/StockSharp/StockSharp/blob/master/Samples/03_Storage/05_HydraServerSaveToLocal/Program.cs).

The current `master` tree does not contain a standalone `Hydra/` source directory. It contains the storage abstractions and Hydra integration samples; the full desktop/server product is therefore not something this Python repository can simply import.

## Fit against our workflow

Our system currently expects thin Python source adapters to produce a canonical OHLCV frame, validate and normalize it, write yearly Parquet partitions, preserve raw and adjusted fields plus corporate-action facts, and then run point-in-time universe filtering and reproducible backtests. See [`backtest-engine/src/backtest_engine/data/sources/base.py`](../../backtest-engine/src/backtest_engine/data/sources/base.py), [`backtest-engine/src/backtest_engine/data/ingest.py`](../../backtest-engine/src/backtest_engine/data/ingest.py), and [`backtest-engine/README.md`](../../backtest-engine/README.md).

Hydra would add value where we currently have a gap:

- broader broker/exchange/data-provider coverage;
- intraday bars, ticks, Level 1, order books, and order logs;
- scheduled collection and a central or remote data store;
- conversion of raw market data into derived candle series;
- a convenient way to acquire data once and feed several research tools.

It would not replace our fundamentals, SEC/filing, macro, sentiment, corporate-action, or point-in-time-universe sources. It also does not automatically make data research-grade: the chosen connector, adjustments, security mapping, timezone, candle-building rule, and data revision history still need to be captured in our run manifest.

## Main risks

1. **Not Python-native.** The visible integration is C#/.NET and StockSharp message/storage types. The repository's Python analytics examples are written for IronPython inside StockSharp, not for our CPython/pandas/Parquet pipeline. See [Algo.Analytics.Python README](https://github.com/StockSharp/StockSharp/blob/master/Algo.Analytics.Python/README.md).

2. **Format boundary.** Hydra's native storage is StockSharp binary/CSV. Export supports formats including Excel, XML, binary, text, JSON, and SQL tables, but our clean store is partitioned Parquet. A bridge and schema validation are still required. See [Hydra export documentation](https://doc.stocksharp.com/en/topics/hydra/working_with_data/export_data).

3. **Instrument identity.** StockSharp identifies instruments as `instrument@board`, for example `AAPL@NASDAQ`. Our engine mostly works with a plain symbol, so a stable symbol/board mapping must be added before importing data. See [instrument identifier documentation](https://github.com/StockSharp/doc/blob/master/en/topics/api/instruments/instrument_identifier.md).

4. **Licensing.** The current linked repository's `LICENSE` says it is not under a general-purpose open-source license. StockSharp's official EULA grants personal use and prohibits copying, modifying, incorporating, or making the software available to others without permission. This is incompatible with treating Hydra source or binaries as an unreviewed dependency in our GitHub-ready MIT project. See [repository LICENSE](https://github.com/StockSharp/StockSharp/blob/master/LICENSE) and [official EULA](https://stocksharp.com/en/products/eula/).

5. **Data-provider terms remain separate.** A free downloader does not mean that every connected market-data source is free for every use, history length, or redistribution model. Each selected connector and its data entitlement need separate checking.

## Recommended architecture

Keep the Python backtest engine as the system of record:

```text
Hydra connector/server
        |
        v
CSV/JSON/SQL or StockSharp remote stream
        |
        v
Python import bridge -> raw staging -> validate_clean -> clean Parquet
        |
        v
point-in-time universe -> VectorBT discovery -> Backtrader validation
```

Do not write Hydra output directly into `data/clean`. Import it into a separate staging area, preserve the StockSharp security ID and board, data type, timeframe, source, adjustment/build mode, requested period, retrieval timestamp, and Hydra/connector version, then run the same cleaner and manifest logic used by yfinance and Stooq. Treat Hydra-built candles as derived data and record what they were built from.

## Go/no-go

**Go for a small sidecar pilot** if we need better intraday/tick/order-book coverage or scheduled multi-provider collection.

**No-go for immediate adoption** if the goal is simply to improve the current daily-bar Python workflow. yfinance/Stooq/CSV are simpler, already fit the canonical schema, and keep the project portable and MIT-compatible.

Suggested pilot: acquire one US equity through one connector, export a small daily and intraday sample, compare timestamps, corporate actions, missing rows, and adjusted prices against our current sources, then run the imported data through the existing cleaner and a temporary data root. Do not commit downloaded data, credentials, Hydra binaries, or provider data to this repository.
