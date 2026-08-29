---
title: "TradingAgents Comparison & Integration Plan"
date: 2026-07-08
tags:
  - strategy
  - architecture
  - reference
  - planning
---

# TradingAgents Comparison & Integration Plan

> **Source:** [github.com/TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) v0.3.1
> **Our system:** Scion-Bot (Burry) + Omaha-Bot (Buffett) dual-agent trading framework

---

## What TradingAgents Is

TradingAgents is an open-source multi-agent LLM trading framework that mirrors the dynamics of a real-world trading firm. Built with LangGraph, it deploys specialized LLM-powered agents:

| Role | Function |
| :--- | :--- |
| **Fundamentals Analyst** | Evaluates company financials, intrinsic value, red flags |
| **Sentiment Analyst** | Reads Yahoo News, StockTwits, Reddit for market mood (v0.2.5+, grounded) |
| **News Analyst** | Monitors global news, macro indicators (including FRED + Polymarket) |
| **Technical Analyst** | MACD, RSI, patterns, price forecasts |
| **Bull / Bear Researchers** | Structured debate rounds — cross-examine analyst findings |
| **Risk Management Team** | Aggressive / Conservative / Neutral risk analysts debate portfolio risk |
| **Trader** | Translates research into concrete transaction proposal (entry, stop, sizing) |
| **Portfolio Manager** | Final authority — approves/rejects with typed decision + thesis |

### Key Architecture Details

- **LangGraph state machine**: Nodes (analysts, researchers, risk, trader, PM) connected by conditional edges
- **Multi-provider LLM**: OpenAI, Anthropic, Google, DeepSeek, Ollama, OpenRouter, vLLM, Bedrock, etc.
- **Structured output (Pydantic)**: ResearchPlan, TraderProposal, PortfolioDecision, SentimentReport
- **Persistent decision log**: Writes to `~/.tradingagents/memory/trading_memory.md`, resolves realized return vs benchmark on next run, generates reflection paragraph injected into future PM prompts
- **Checkpoint/resume**: LangGraph saves state after each node — crashed runs resume from last step
- **Verified data-access contract**: Symbol normalization, look-ahead-safe news, stale-OHLCV rejection
- **Alpha benchmarks**: Per-region index (SPY, N225, HSI, FTSE, etc.) for realized-return comparison

---

## Feature Comparison

| Capability                      |            TradingAgents             |       Scion-Bot (Burry)        |      Omaha-Bot (Buffett)       |
| :------------------------------ | :----------------------------------: | :----------------------------: | :----------------------------: |
| **LLM-powered analysts**        |      ✅ GPT/Claude/Gemini agents      |      ❌ Rule-based scoring      |      ❌ Rule-based scoring      |
| **Bull/Bear debate**            |      ✅ Structured debate rounds      |               ❌                |               ❌                |
| **Sentiment (social media)**    |     ✅ StockTwits + Reddit + News     |      ❌ Keyword news only       |      ❌ Keyword news only       |
| **Macro / prediction markets**  |         ✅ FRED + Polymarket          |     ❌ Credit spreads only      |     ❌ Credit spreads only      |
| **Technical analysis**          |       ✅ MACD, RSI via yfinance       |      ✅ 11-function ta_lib      |      ✅ 11-function ta_lib      |
| **Real portfolio management**   |           ❌ Simulated only           |  ✅ Stop losses, targets, cash  |   ✅ Thesis-driven, no stops    |
| **Dual philosophy**             |          ❌ Single framework          |    ✅ Burry (value + swing)     | ✅ Buffett (quality + forever)  |
| **Live position monitoring**    |                  ❌                   |        ✅ daily_check.py        |        ✅ daily_check.py        |
| **Structured decision output**  |          ✅ Pydantic schemas          |            ❌ Dicts             |            ❌ Dicts             |
| **Memory / reflection loop**    | ✅ Tracks alpha, reflects, re-injects |    ❌ feedback.py rules only    |    ❌ feedback.py rules only    |
| **Performance reports**         |                  ❌                   |    ✅ report_card.py → vault    |    ✅ report_card.py → vault    |
| **Strategy feedback engine**    |                  ❌                   |    ✅ feedback.py (6 rules)     |    ✅ feedback.py (6 rules)     |
| **Backtesting**                 | ✅ Look-ahead filtered, date-fidelity |               ❌                |               ❌                |
| **Alpha tracking**              |        ✅ Per-region benchmark        |               ❌                |               ❌                |
| **Portfolio VaR / drawdown**    |                  ❌                   |               ❌                |               ❌                |
| **Credit market overlay**       |                  ❌                   |      ✅ credit_monitor.py       |      ✅ credit_monitor.py       |
| **WhatsApp notifications**      |                  ❌                   |          ✅ notify.py           |          ✅ notify.py           |
| **Obsidian vault integration**  |                  ❌                   | ✅ Markdown reports + wikilinks | ✅ Markdown reports + wikilinks |
| **Multi-investment philosophy** |                  ❌                   |           ✅ 2 agents           |           ✅ 2 agents           |

---

## Integration Roadmap — 4 Phases

### Phase 1: Concepts Only (No LLM Dependencies)

These borrow ideas from TradingAgents without adding any new dependencies or API keys:

1. **Alpha tracking** — `report_card.py` computes benchmark return (SPY) alongside each closed trade's return. New column: `Alpha vs SPY`. Shows cumulative alpha portfolio-wide.

2. **Portfolio VaR / max-drawdown guard** — Before `portfolio.py` opens a position, compute total portfolio drawdown if all positions hit their stops. Reject if > 15% of total capital.

3. **Decision reflection log** — New `reflection.py`. On trade close, appends 1-2 sentences to `reflection_log.json`. Before next screener run, injects recent reflections into the scoring context.

### Phase 2: Selective LLM Augmentation (Bolt Onto Existing System)

If Phase 1 proves the concepts valuable, add LLM calls to our existing architecture:

4. **LLM Sentiment Analyst** — Replace keyword news scoring with an LLM call on high-impact articles. Our keyword filter acts as pre-screen to reduce cost.

5. **LLM Qualitative Analysis** — In `analyzer.py` / `buffett_analyzer.py`, inject a brief LLM synthesis call (financial data → qualitative summary). Enriches reports with insights our rules can't capture.

6. **Structured Decision Output** — Add Pydantic schemas to `tracker.py` / `portfolio.py` for typed, validated decision records.

### Phase 3: Run TradingAgents as Parallel Signal

Install TradingAgents and run it as a **third opinion** alongside Scion and Omaha:

7. **Install TradingAgents** in its own virtual environment.
8. **Feed screened tickers** through `TradingAgentsGraph.propagate()` and capture its decision.
9. **Compare decisions** across 3 systems: Which agrees? Which outperforms? Log all 3 in `tracker.py`.
10. **Wait for 10+ closed trades** per system before drawing conclusions about LLM-agent superiority.

### Phase 4: Full Architecture Migration (If Phase 3 Confirms Value)

If the LLM-agent approach clearly beats our deterministic system:

11. **Replace analysts**: Scrap rule-based `screener.py` / `analyzer.py`, replace with TradingAgents' LangGraph pipeline.
12. **Integrate with our infra**: Keep `portfolio.py`, `tracker.py`, `feedback.py`, `notify.py`, `credit_monitor.py`, vault output. Only the analysis generation changes.
13. **Dual-philosophy**: Maintain separate LangGraph configs for Burry-style (value + swing) and Buffett-style (quality + forever) agents.

---

## Decision Tree

```
Phase 1 (no risk, no cost)
  ├─ Alpha tracking → useful? ──► Keep forever
  ├─ Portfolio VaR → stops bad entries? ──► Keep forever  
  └─ Reflection log → improves picks? ──► Keep forever

Phase 2 (LLM bolt-on, moderate cost)
  └─ Does LLM sentiment beat keyword scoring? ──► If yes, keep

Phase 3 (install TradingAgents, API costs)
  └─ Does LLM-agent debate beat deterministic scoring? ──► 
       ├─ If no → stop here, we're already optimal for our style
       └─ If yes → proceed to Phase 4

Phase 4 (full migration, high effort)
  └─ Replace analysis engine with LangGraph
      Keep portfolio, tracking, notifications, vault
```

---

**Current Status:** Phase 1 implemented 2026-07-08. Proceeding to Phase 2/3 decision after evaluating Phase 1 utility on live trades.
