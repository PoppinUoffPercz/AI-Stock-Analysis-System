# Correctness-First Trading Harness Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the trading and backtesting harness trustworthy before adding features.

**Architecture:** Repair shared root causes at the engine, data, validation, portfolio, and CLI boundaries. Keep public interfaces unless correctness requires a change, and verify each repair with a focused regression followed by the relevant full suite.

**Tech Stack:** Python 3.11+, pandas, NumPy, VectorBT, Backtrader, yfinance-shaped data, pytest, Ruff, mypy, and the existing portfolio JSON state model.

## Global Constraints

- Work sequentially and complete exactly one task at a time.
- Write and run a smallest failing regression before production code.
- Run targeted tests, the relevant complete suite, Ruff, mypy, and `git diff --check` before each task commit.
- Do not push, rewrite history, modify unrelated user changes, or perform broad refactors.
- Preserve close-based valuation, documented next-open fills, raw OHLC, corporate-action facts, deterministic seeds, and temporary test state paths.
- Use separate commits with the exact messages specified by the task.

## Task Checklist

- [ ] Task 1: Enforce VectorBT next-open fills; assert exact timestamps/prices; commit `fix: enforce next-open vectorbt fills`.
- [ ] Task 2: Record only completed Backtrader fills; commit `fix: record completed backtrader fills only`.
- [ ] Task 3: Charge Backtrader execution costs through broker accounting; commit `fix: charge execution costs in backtrader`.
- [ ] Task 4: Normalize yfinance corporate actions and adjusted OHLC safely; commit `fix: normalize corporate actions correctly`.
- [ ] Task 5: Implement genuine deterministic random-entry testing with finite-sample p-values; commit `fix: implement genuine random-entry testing`.
- [ ] Task 6: Separate trade-order permutation from bootstrap statistics; commit `fix: align monte carlo methods with reported statistics`.
- [ ] Task 7: Merge incremental partitions and atomically replace validated files; commit `fix: merge incremental data partitions atomically`.
- [ ] Task 8a: Preserve Scion partial-exit cost basis and test it; commit `fix: preserve scion cost basis after scale-out`.
- [ ] Task 8b: Preserve Omaha partial-exit cost basis and test it; commit `fix: preserve omaha cost basis after trim`.
- [ ] Task 9: Persist run artifacts and make immediate report lookup work; commit `fix: persist backtest run artifacts`.
- [ ] Task 10: Reuse one listing/delisting membership predicate; commit `fix: enforce point-in-time universe membership`.
- [ ] Task 11: Delete only proven-unused backtest surfaces after all behavioral work is green; commit `refactor: remove unused backtest surfaces`.

## Per-Task Gate

For each checklist item: inspect callers and tests; add one minimal regression; run it and confirm the expected failure; implement the smallest root-cause fix; run the regression and relevant suite; run Ruff and mypy on touched modules; inspect the diff; commit only intended files; then update this checklist and continue.

## Final Gate

From `backtest-engine`, run `python -m pytest -q`, `python -m ruff check src tests`, `python -m ruff format --check src tests`, and `python -m mypy src`. Run bot portfolio tests separately, then `git diff --check`, verify the worktree, and report every commit, command result, and remaining limitation.
