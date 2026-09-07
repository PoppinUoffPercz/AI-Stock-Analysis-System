# Trading Intelligence Architecture

## Current flow

```text
fixture/replay market events
        |
        v
stock_analysis.market_analytics.AnalyticsPipeline
        |
        +-- DOM / order flow / VWAP / profiles
        +-- options / volatility / positioning
        +-- provenance-aware FeatureRecord
        |
        v
RegimeEngine -> ScreeningEngine -> ThesisBuilder -> RiskEngine
        |              |                |             |
        +--------------+----------------+-------------+
                               |
                               v
                  immutable content-addressed artifacts
```

The deterministic intelligence layer lives in `stock_analysis.intelligence`. It consumes the
existing `FeatureRecord`; it does not create a second analytics engine, portfolio tracker, or
experiment registry.

## Ownership and boundaries

| Area | Owner | Current support |
| --- | --- | --- |
| Market events, availability metadata, analytics | `stock_analysis.market_analytics` | Fixture/replay analytics implemented; vendor streaming is not implemented |
| DOM, footprint, VWAP, TPO/volume profiles | `stock_analysis.market_analytics` | Deterministic fixture/replay support |
| IV/surface/positioning proxies | `stock_analysis.market_analytics` | Research analytics; signed dealer exposure remains model-dependent |
| Regime policy | `stock_analysis.intelligence.engine.RegimeEngine` | Explainable trend/volatility/liquidity rules; unsupported dimensions remain missing |
| Screening | `ScreeningEngine` | Trend-continuation and VWAP mean-reversion families; other families explicitly unsupported |
| Thesis | `ThesisBuilder` | Deterministic evidence-backed research thesis; no LLM required |
| Risk | `RiskEngine` | Fresh-state, cash, single-name, gross/net and lot-size gates; thesis is never approval |
| Persistence | `ArtifactStore` plus shared atomic persistence | Immutable research artifacts with schema version and SHA-256 identity |
| Backtests | `backtest-engine` | Existing discovery/validation/reproducibility path; intelligence integration is still pending |
| Scion/Omaha | `scion-omaha-bots` | Existing research workflows preserved; legacy scores may be supplied as bounded screen inputs |
| Execution | none in intelligence layer | Live execution is not implemented and cannot be activated through this slice |

## Audit rules

- Ranking scores are ordering metrics, not probabilities of profit.
- Missing or stale inputs are excluded from deterministic decisions instead of being zero-filled.
- Feature metadata dated after the decision timestamp is rejected.
- A thesis contains a position request only; `RiskEngine` returns the separate approval decision.
- Risk rejects stale portfolio state and short positions by default.
- Artifact identity is calculated from deterministic payload content. The store rejects corrupted or
  mismatched payloads and uses the shared process lock plus atomic replacement helper.
- Research artifacts use a separate `research/` namespace. No broker credentials or order APIs are
  present in this layer.

## Offline checkpoint

Run:

```powershell
stock-analysis --outputs-root .\outputs intelligence checkpoint
stock-analysis --outputs-root .\outputs intelligence checkpoint --json
stock-analysis --outputs-root .\outputs intelligence checkpoint --degraded --json
```

The checkpoint uses only the repository's explicitly labeled deterministic fixtures. It may return
zero candidates. That is a valid outcome and is not tuned away.

Persisted artifacts are written under `outputs/intelligence-checkpoint/research/`. They can be
loaded without network access:

```powershell
stock-analysis intelligence show .\outputs\intelligence-checkpoint\research\screen\<identity>.json
```

## Known limits

This checkpoint is not the full requested platform. It does not yet claim production support for
point-in-time vendor revisions, historical option-chain ingestion, American option exercise,
regime breadth/correlation/rates dimensions, sector/correlation portfolio caps, review proposals,
paper-broker lifecycle, streaming feeds, dashboards, or LLM orchestration. Those remain dependency-
ordered follow-on work in the implementation checklist.
