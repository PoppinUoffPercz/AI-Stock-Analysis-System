# Trading Intelligence Capability Matrix

Status legend: `done`, `partial`, `deferred by data/provider`.

## Shipped fixture-first capabilities

| Area | Status | Current boundary |
|---|---|---|
| Shared contracts, provenance, and artifact storage | partial | Versioned content-addressed artifacts, point-in-time envelopes, atomic/process-locked persistence; provider revision/index contracts remain. |
| Market microstructure | partial | Deterministic replay, DOM reconstruction, order flow, CVD, VWAP, TPO and volume profiles; no live L2/OPRA vendor adapters. |
| Options analytics | partial | Normalization, quote quality, European Black-Scholes, IV surfaces/history, expected-volatility context, and GEX/DEX scenarios; no American exercise or executable option lifecycle. |
| Regime, screens, and thesis | partial | Deterministic regime policy, screens, evidence coverage, traceable thesis output, and unsupported-family reasons; point-in-time fundamentals/catalysts remain unavailable. |
| Risk and construction | partial | Fresh-state, restricted-instrument, short-disabled, cash reserve, single-name, gross/net, and lot-size constraints; sector/correlation/portfolio-volatility/stress constraints remain. |
| Backtest integration and review | done | Existing manifest/index and validation tooling are reused; deterministic review artifacts and platform end-to-end contracts are present. |
| Streaming, replay, and paper execution | done | Bounded normalized streaming, deterministic replay, long-only local paper orders, persistence, reconciliation, terminal recovery, and no live trading. |
| Offline dashboard | done | Persisted artifacts can be rendered without a service or network dependency. |
| Read-only LLM orchestration | done | A bounded read-only summarizer is isolated from risk approval and execution. |

## Next dependency order

1. Add exchange-session and holiday/early-close contracts before intraday execution realism.
2. Add authoritative SEC point-in-time fundamentals and a provider-aware snapshot index.
3. Add selection-bias diagnostics (Deflated Sharpe Ratio and PBO) to existing review artifacts.
4. Add volume participation and zero-volume no-fill behavior to event-driven validation.
5. Add optional American-option valuation behind a QuantLib extra.

## Non-goals

- Live broker connectivity, vendor credentials, and autonomous execution remain disabled.
- Missing data remains unavailable/null with provenance; it is never fabricated as zero.
- The local paper broker remains a deterministic research boundary, not a production OMS.
