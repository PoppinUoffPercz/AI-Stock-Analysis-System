# Luna Max Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Work inline as Luna Max to conserve usage; no additional agents needed. Steps use checkbox syntax for tracking.

**Goal:** Fix the outstanding type errors and make three small, behavior-preserving simplifications.

**Architecture:** Keep existing interfaces, validation, persistence contracts, and portfolio sizing rules. Reuse the shared atomic writer and Python's stable sort; move invariant volatility calculations outside the sizing loop.

**Tech Stack:** Python 3.12+, pytest, Ruff, MyPy; no new dependencies.

## Global constraints

- Repository: `C:/Users/alexp/Documents/Codex/2026-08-29/he/outputs/stock-analysis-system`. All paths below are relative to this root.
- Read local agent instructions and current diffs first. Preserve all existing work, especially staged `scion-omaha-bots/shadow_log.csv`.
- Do not commit, stage, push, broadly format the repository, remove useful features, or rewrite financial formulas.
- These four tasks are the entire implementation scope. Report other findings separately. Do not declare the prior seven-stage platform mission complete merely because these checks pass.
- Use the working Python interpreter with installed development dependencies. Run commands individually and inspect their exit status. Prior results are historical, not current acceptance evidence.

## Task 1: Fix the four reported MyPy errors

**Files:** `stock_analysis/intelligence/models.py`, `stock_analysis/intelligence/engine.py`.
**Interfaces:** Keep `RiskPolicy` and `RiskEngine.decide` unchanged.

- [ ] From `backtest-engine/`, run `python -m mypy src`. Confirm the reported optional-float loop inference and reused position/pending-order loop-variable errors still exist before editing.
- [ ] In `RiskPolicy.__post_init__`, replace only the optional-limit loop with:

```python
for optional_value, label in (
    (self.max_sector_fraction, "max_sector_fraction"),
    (self.max_correlated_fraction, "max_correlated_fraction"),
    (self.max_pair_correlation, "max_pair_correlation"),
    (self.max_annualized_volatility, "max_annualized_volatility"),
):
    if optional_value is not None:
        _require_finite(float(optional_value), label)
        if optional_value < 0:
            raise ValueError(f"{label} must be nonnegative")
```

- [ ] In `_advanced_rooms`, replace only the pending-order loop with:

```python
for pending_order in pending:
    if pending_order.signed_notional != 0:
        current_by_symbol[pending_order.symbol] = (
            current_by_symbol.get(pending_order.symbol, 0.0)
            + pending_order.signed_notional
        )
```

- [ ] Run `python -m mypy src` from `backtest-engine/` and `python -m pytest -q tests/intelligence/test_checkpoint.py` from root. Expected: no typing errors and all tests pass. Do not add casts or ignores.

## Task 2: Simplify stable replay ordering

**Files:** `stock_analysis/market_analytics/replay.py`; existing tests in `tests/test_paper.py` and `tests/market_analytics/test_replay.py`.
**Interfaces:** `ReplayProvider(events, capabilities, provider)` and `events(symbol)` remain unchanged.

- [ ] Run `python -m pytest -q tests/test_paper.py tests/market_analytics/test_replay.py` from root as the characterization baseline. The existing out-of-order test checks equal-timestamp arrival order.
- [ ] Replace the `incoming` tuple plus enumerated sorting block in `ReplayProvider.__init__` with:

```python
self._events = tuple(sorted(events, key=lambda event: event.timestamp))
```

- [ ] Keep the UTC validation and filtering behavior intact. Python sorting is stable, so equal timestamps retain their original order without explicit sequence tuples.
- [ ] Rerun the same tests. Expected: identical ordering and all tests pass.

## Task 3: Reuse the shared atomic result writer

**Files:** `backtest-engine/src/backtest_engine/strategy/persistence.py`; existing tests in `backtest-engine/tests/test_persistence.py` and `tests/test_atomic_persistence.py`.
**Interfaces:** Keep `persist_result`, `load_result`, and `_write_manifest_once` unchanged externally.

- [ ] Inspect `_atomic_write` callers and tests first: `rg -n '_atomic_write|atomic_write_text|result\\.' backtest-engine/src backtest-engine/tests tests/test_atomic_persistence.py`.
- [ ] Run `python -m pytest -q tests/test_persistence.py` from `backtest-engine/` and `python -m pytest -q tests/test_atomic_persistence.py` from root. Expected: baseline passes.
- [ ] Add the import and replace the result publication call:

```python
from stock_analysis.persistence import atomic_write_text

# At the existing result publication call:
atomic_write_text(path, encoded)
```

- [ ] Remove the now-unused `_atomic_write` function. Keep `os`, `tempfile`, and `_write_manifest_once`: the manifest uses hard-link creation to preserve write-once semantics under races. Do not replace it with an overwriting writer.
- [ ] Rerun the two suites above. Confirm result round trips, atomic-write failure preservation, and immutable manifest behavior. Temporary filename prefixes are private implementation details, but file contents and manifest behavior must remain unchanged.

## Task 4: Precompute volatility statistics once per sizing request

**Files:** `stock_analysis/intelligence/engine.py`; `tests/intelligence/test_checkpoint.py`.
**Interfaces:** `_volatility_room` still returns the same safe notional; `RiskEngine.decide` returns the same status, binding constraints, and rounded quantity.

- [ ] Before editing, capture decisions from the current implementation using the existing volatility fixture and deterministic multi-symbol contexts. Cover a binding cap, a nonbinding cap, existing exposure above the cap, positive/negative correlations, and lot-rounding boundaries. Preserve full returned decisions as the comparison baseline; do not regenerate expected outputs from the new code.
- [ ] Immediately before the nested `volatility` function, calculate these invariant statistics once:

```python
means = [sum(row[i] for row in rows) / len(rows) for i in range(len(symbols))]
denominator = len(rows) - 1
covariances = [
    [
        sum((row[i] - means[i]) * (row[j] - means[j]) for row in rows)
        / denominator
        for j in range(len(symbols))
    ]
    for i in range(len(symbols))
]
```

- [ ] Inside `volatility`, retain the existing notionals and weights calculation; replace its means/covariance/variance block with:

```python
variance = 0.0
for i, left_weight in enumerate(weights):
    for j, right_weight in enumerate(weights):
        variance += left_weight * right_weight * covariances[i][j]
return sqrt(max(0.0, variance) * self.policy.annualization_factor)
```

- [ ] Preserve the current summation order, sample denominator, 50 bisection iterations, tolerances, and lot rounding. Do not introduce global caching or change the handling of already-over-limit portfolios in this task.
- [ ] Compare every captured baseline decision to the optimized version. Require identical approved quantities, statuses, and binding constraints. Run `python -m pytest -q tests/intelligence/test_checkpoint.py`.
- [ ] Measure both versions on the same deterministic multi-symbol input with `timeit.repeat`, using equal repeat counts. Report actual timings or state that no timing claim was established. The structural improvement is computing covariance once rather than up to 52 times per sizing request.

## Final gate and handoff

- [ ] Format only edited files. From root run `python -m ruff check stock_analysis tests` and `python -m pytest -q tests scion-omaha-bots`.
- [ ] From `backtest-engine/`, run individually:

```powershell
python -m ruff check src tests
python -m ruff format --check src tests
python -m mypy src
python -m pytest
```

- [ ] From root run `git diff --check` and `git status --short`. Verify the pre-existing staged file and unrelated diffs were preserved. A dirty tree is expected.
- [ ] Report four task outcomes, exact test results, measured timing if available, and remaining blockers. Optional NautilusTrader skips must be reported as skips. No commits or pushes.
