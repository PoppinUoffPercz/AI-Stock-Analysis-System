# Next Reliability and Research Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Use test-driven-development for each bug fix and verification-before-completion before any completion claim. Keep work inline unless the user explicitly asks for subagents.

**Goal:** Fix five reproduced correctness failures, remove repository drift, and establish a safe sequence for the next research-grade features.

**Architecture:** Preserve the existing fixture-first architecture and public interfaces. Keep date inputs inclusive at the CLI while translating provider-specific boundaries at adapters; enforce one finite canonical market-data schema; make replay state transitions atomic and restart-safe; keep the local paper broker intentionally smaller than a production OMS.

**Tech Stack:** Python 3.12, pandas, NumPy, PyArrow, pytest, Ruff, MyPy; optional future integrations use `exchange-calendars`, SEC EDGAR JSON APIs, and QuantLib only behind explicit extras.

## Global constraints

- Repository root: `C:/Users/alexp/Documents/Codex/2026-08-29/he/outputs/stock-analysis-system`.
- Read `git status --short` and the current diff before every task. The working tree already contains substantial user-owned edits.
- Do not reset, discard, stage, commit, or push unrelated work. In particular, do not alter the currently staged `scion-omaha-bots/shadow_log.csv` until Task 5's explicit user checkpoint.
- Implement Tasks 1-4 sequentially. They repair proven failures and should not be mixed with the follow-on feature roadmap.
- Keep the root package at `stock_analysis/...`; this repository does not use `src/stock_analysis/...`.
- Do not add live trading, credentials, vendor secrets, network-dependent tests, a second experiment registry, or a second execution engine.
- All new tests must be deterministic and offline. Run narrow red/green checks first, then the full gates in Task 6.
- The commit commands below are checkpoints for a clean isolated execution branch. If the shared working tree cannot stage only the named files safely, skip the commit and report why.

## Research basis and decisions

The local audit reproduced five bugs rather than inferring them from style:

1. `read_clean(..., end="2024-01-02")` excludes intraday rows later on January 2 even though the CLI documents an inclusive date.
2. `validate_clean` accepts infinite raw OHLC/volume and non-finite dividend/split values.
3. Two open sell orders can reserve the same shares; a failed trade event can partially mutate state and remain marked processed.
4. Restart recovery ignores a journal's terminal `close` action.
5. Duplicate accepted journal records can cause recovery to reuse an existing heap sequence; the next drain raises `TypeError`.

The public date contract remains inclusive because that is what the CLI already promises. The yfinance adapter must translate the inclusive day to yfinance's documented exclusive `end` boundary ([official history API](https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html)). The paper broker will gain only aggregate leaves reservation and atomic replay; richer OMS/reconciliation semantics belong behind the existing Nautilus adapter ([execution](https://nautilustrader.io/docs/latest/concepts/execution/), [reconciliation](https://nautilustrader.io/docs/latest/concepts/reconciliation/)).

## Task 1: Make date ranges truly inclusive across storage and providers

**Files:**

- Create: `backtest-engine/src/backtest_engine/data/dates.py`
- Modify: `backtest-engine/src/backtest_engine/data/store.py`
- Modify: `backtest-engine/src/backtest_engine/data/sources/base.py`
- Modify: `backtest-engine/src/backtest_engine/cli.py`
- Test: `backtest-engine/tests/test_data.py`
- Test: `backtest-engine/tests/test_ingest_cli.py`

**Interfaces:** `Source.fetch(symbol, start, end)` and `read_clean(..., start, end)` continue accepting optional `YYYY-MM-DD` strings; both bounds are inclusive calendar dates.

- [ ] Add a failing store regression to `backtest-engine/tests/test_data.py`:

```python
def test_read_clean_includes_intraday_rows_on_end_date(tmp_path):
    raw = _raw_frame(n=2)
    raw.loc[0, "timestamp"] = pd.Timestamp("2024-01-02T00:00:00Z")
    raw.loc[1, "timestamp"] = pd.Timestamp("2024-01-02T15:30:00Z")
    write_clean(raw, tmp_path / "clean", symbol="TEST", source="fixture")

    got = read_clean(tmp_path / "clean", "TEST", end="2024-01-02")

    assert got["timestamp"].tolist() == raw["timestamp"].tolist()
```

- [ ] Add a CSV adapter test with one row at midnight on the next day. Assert `end="2024-01-02"` includes the 15:30 row and excludes the January 3 row.
- [ ] Extend the mocked yfinance test so `FakeTicker.history` records keyword arguments; assert an inclusive `end="2024-01-02"` is sent upstream as `end="2024-01-03"`.
- [ ] Add a Stooq `_date_params` test asserting its inclusive `d2` remains `20240102`; do not apply the yfinance conversion to every provider.
- [ ] Run the failing tests:

```powershell
Set-Location backtest-engine
python -m pytest -q tests/test_data.py tests/test_ingest_cli.py -k "end_date or yfinance_end or stooq_end"
```

Expected: the store/CSV/yfinance assertions fail against current behavior.

- [ ] Create one small date helper with strict date-only parsing:

```python
from datetime import date, timedelta

import pandas as pd


def utc_day(value: str) -> pd.Timestamp:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid date {value!r}; expected YYYY-MM-DD") from exc
    return pd.Timestamp(parsed, tz="UTC")


def day_after(value: str) -> str:
    try:
        return (date.fromisoformat(value) + timedelta(days=1)).isoformat()
    except ValueError as exc:
        raise ValueError(f"invalid date {value!r}; expected YYYY-MM-DD") from exc
```

- [ ] In `read_clean` and `CsvSource.fetch`, filter `end` with `< utc_day(end) + pd.Timedelta(days=1)`. Use `utc_day(start)` for the lower bound.
- [ ] In `YFinanceSource.fetch`, pass `day_after(end)` when `end` is not `None`. Leave Stooq's `d2` inclusive and unchanged.
- [ ] Correct the misleading yfinance docstring: `auto_adjust=False` requests raw OHLC plus adjusted close/action facts; the normalizer derives adjusted OHLC from those values.
- [ ] Keep the CLI help text saying “Inclusive ... date”; add `YYYY-MM-DD` help to the ingest parser if absent.
- [ ] Rerun the narrow tests. Expected: all pass.
- [ ] Run `python -m ruff check src/backtest_engine/data tests/test_data.py tests/test_ingest_cli.py` and `python -m mypy src` from `backtest-engine/`.
- [ ] Optional isolated commit:

```powershell
git add -- backtest-engine/src/backtest_engine/data/dates.py backtest-engine/src/backtest_engine/data/store.py backtest-engine/src/backtest_engine/data/sources/base.py backtest-engine/src/backtest_engine/cli.py backtest-engine/tests/test_data.py backtest-engine/tests/test_ingest_cli.py
git commit -m "fix(backtest): honor inclusive data date ranges"
```

## Task 2: Reject every non-finite canonical market-data value

**Files:**

- Modify: `backtest-engine/src/backtest_engine/data/clean.py`
- Test: `backtest-engine/tests/test_data.py`

**Interface:** `validate_clean(df, source=...)` keeps filling missing adjustment/action columns. Existing `NaN` volume behavior remains: a missing volume becomes zero. Infinite volume and all non-finite OHLC/action values are rejected.

- [ ] Add failing parameterized tests:

```python
@pytest.mark.parametrize("column", ["open", "high", "low", "close"])
@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_validate_clean_rejects_nonfinite_raw_ohlc(column, value):
    raw = _raw_frame()
    raw.loc[0, column] = value
    with pytest.raises(CleanError, match="raw OHLC"):
        validate_clean(raw, source="fixture")


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("volume", np.inf, "volume"),
        ("dividend", np.nan, "dividend"),
        ("dividend", np.inf, "dividend"),
        ("split_ratio", np.nan, "split_ratio"),
        ("split_ratio", np.inf, "split_ratio"),
    ],
)
def test_validate_clean_rejects_nonfinite_volume_and_actions(column, value, message):
    raw = _raw_frame()
    raw.loc[0, column] = value
    with pytest.raises(CleanError, match=message):
        validate_clean(raw, source="fixture")
```

- [ ] Run `python -m pytest -q tests/test_data.py -k nonfinite` from `backtest-engine/`. Expected: the new raw/action cases fail.
- [ ] Coerce and validate each numeric family before applying relational invariants:

```python
raw_ohlc_columns = ["open", "high", "low", "close"]
adjusted_ohlc_columns = ["adj_open", "adj_high", "adj_low", "adj_close"]
for column in (*raw_ohlc_columns, *adjusted_ohlc_columns, "volume", "dividend", "split_ratio"):
    d[column] = pd.to_numeric(d[column], errors="coerce")

d["volume"] = d["volume"].fillna(0.0)
for columns, label in (
    (raw_ohlc_columns, "raw OHLC"),
    (adjusted_ohlc_columns, "adjusted OHLC"),
    (["volume"], "volume"),
    (["dividend"], "dividend"),
    (["split_ratio"], "split_ratio"),
):
    if not np.isfinite(d[columns].to_numpy(dtype=float)).all():
        raise CleanError(f"invalid {label}")
```

- [ ] Remove the now-redundant separate adjusted-OHLC conversion/check, but keep negative-volume, dividend, split, and OHLC ordering rules.
- [ ] Update the `CleanError` docstring contract to name non-finite numeric values.
- [ ] Run `python -m pytest -q tests/test_data.py`; then Ruff and MyPy for the same paths. Expected: all pass.
- [ ] Optional isolated commit:

```powershell
git add -- backtest-engine/src/backtest_engine/data/clean.py backtest-engine/tests/test_data.py
git commit -m "fix(backtest): reject non-finite clean data"
```

## Task 3: Reserve paper shares and make trade processing atomic

**Files:**

- Modify: `stock_analysis/paper.py`
- Test: `tests/test_paper.py`

**Interfaces:** Keep market-only, long-equity, deterministic replay behavior. Do not add limit orders, stop orders, shorting, broker connectivity, or asynchronous execution.

- [ ] Add a failing reservation regression:

```python
def test_paper_broker_rejects_sells_that_reuse_reserved_shares():
    broker = PaperBroker(1_000.0)
    broker.submit_order("buy", "AAA", "buy", 10.0, T0)
    broker.process_trade(_trade(1, "entry", size=10.0))

    first = broker.submit_order("sell-1", "AAA", "sell", 10.0, T0 + timedelta(seconds=2))
    second = broker.submit_order("sell-2", "AAA", "sell", 1.0, T0 + timedelta(seconds=2))

    assert first.status is PaperOrderStatus.OPEN
    assert second.status is PaperOrderStatus.REJECTED
    assert "available" in second.rejection_reason
```

- [ ] Add a cancellation test: canceling `sell-1` releases the reservation and permits a replacement sell.
- [ ] Add an atomicity test by monkeypatching `_apply_fill` to raise on the second eligible order. Capture `before = broker.state()`, assert the exception, then assert `broker.state() == before` and that the event can be retried after restoring the method.
- [ ] Run `python -m pytest -q tests/test_paper.py`. Expected: the reservation and rollback tests fail.
- [ ] Add one helper that sums remaining quantities for open/partially filled sells of a symbol:

```python
def _reserved_sell_quantity(self, symbol: str) -> float:
    active = {PaperOrderStatus.OPEN, PaperOrderStatus.PARTIALLY_FILLED}
    return sum(
        order.remaining_quantity
        for order in self.orders.values()
        if order.symbol == symbol
        and order.side is PaperOrderSide.SELL
        and order.status in active
    )
```

- [ ] At sell submission, compare the new quantity with `position_quantity - reserved_sell_quantity`. Reject over-reservation with a deterministic reason containing the available quantity.
- [ ] Extract the existing restore assignments into a private `_restore_state(state)` method and use it from `restore`.
- [ ] In `process_trade`, capture `before = self.state()` before fills. Add `last_event_at` and `processed_event_ids` only after all fills succeed. On any exception, call `_restore_state(before)` and re-raise:

```python
before = self.state()
try:
    emitted = self._process_trade_fills(event, event_id)
except Exception:
    self._restore_state(before)
    raise
self.last_event_at = event.timestamp
self.processed_event_ids.add(event_id)
return emitted
```

- [ ] Keep `_process_trade_fills` private and move only the existing active-order/fill loop into it. Do not change price, size, fee, ordering, or partial-fill semantics.
- [ ] Run `python -m pytest -q tests/test_paper.py tests/test_atomic_persistence.py` from root. Expected: all pass and retry is deterministic.
- [ ] Run `python -m ruff check stock_analysis/paper.py tests/test_paper.py` and `python -m ruff format --check stock_analysis/paper.py tests/test_paper.py`.
- [ ] Optional isolated commit:

```powershell
git add -- stock_analysis/paper.py tests/test_paper.py
git commit -m "fix(paper): reserve shares and roll back failed events"
```

## Task 4: Restore terminal stream state and preserve sequence uniqueness

**Files:**

- Modify: `stock_analysis/market_analytics/streaming.py`
- Test: `tests/market_analytics/test_streaming.py`

**Interfaces:** Keep append-only JSONL journal records and `StreamingIngestor.recover(max_buffer, journal)` unchanged.

- [ ] Add a failing close-recovery test:

```python
def test_streaming_recovery_preserves_terminal_close(tmp_path):
    journal = StreamJournal(tmp_path / "stream.jsonl")
    original = StreamingIngestor(2, journal=journal)
    original.ingest(_trade(0, "one"), _receive(_trade(0, "one")))
    original.close()

    recovered = StreamingIngestor.recover(2, journal)

    assert recovered.health.closed
    with pytest.raises(RuntimeError, match="closed"):
        recovered.ingest(_trade(1, "after"), _receive(_trade(1, "after")))
```

- [ ] Add a failing duplicate-journal regression. Append the same accepted `StreamEnvelope` twice, append a distinct same-time envelope, recover, ingest one more same-time event, and assert `close()` returns all unique events without `TypeError`.
- [ ] Add a corrupt-order test: an `accept` or `emit` record after `close` must raise a journal error instead of silently reopening history.
- [ ] Run `python -m pytest -q tests/market_analytics/test_streaming.py`. Expected: all three new assertions fail against current recovery.
- [ ] Read journal records once, track whether `close` has occurred, and retain the record position as the next unique sequence:

```python
records = journal.records()
closed = False
for sequence, record in enumerate(records):
    action = record.get("action")
    if closed:
        raise ValueError("stream journal contains a record after close")
    if action == "close":
        closed = True
        continue
    # existing accept/emit validation

ingestor._arrival_sequence = len(records)
ingestor._closed = closed
```

- [ ] Preserve identical duplicate accepts as one event, and preserve the existing error for reused identity with different content.
- [ ] Ensure `close()` on a recovered closed stream remains idempotent and does not append a second close record.
- [ ] Run the streaming tests, then `python -m pytest -q tests/market_analytics` from root. Run Ruff/format on the modified files.
- [ ] Optional isolated commit:

```powershell
git add -- stock_analysis/market_analytics/streaming.py tests/market_analytics/test_streaming.py
git commit -m "fix(streaming): recover closed state and unique ordering"
```

## Task 5: Restore one dependency truth and the source-only boundary

**Files:**

- Delete after confirmation: `scion-omaha-bots/requirements.txt`
- Untrack after confirmation, preserve locally: `scion-omaha-bots/shadow_log.csv`
- Modify: `scion-omaha-bots/README.md`
- Modify: `docs/architecture/06-File-Manifest.md`
- Replace stale status: `docs/implementation/trading-intelligence-checklist.md`
- Create: `tests/test_source_manifest.py`

**Checkpoint requiring user confirmation:** `shadow_log.csv` is currently staged user state. Do not execute the untracking command until the user confirms that the staged addition is accidental runtime output.

- [ ] Add a repository-policy test that fails only in a Git checkout and reports tracked runtime files precisely:

```python
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="requires a Git checkout")
def test_source_manifest_excludes_tracked_runtime_state():
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    forbidden = [path for path in tracked if Path(path).name == "shadow_log.csv"]
    assert forbidden == []
```

- [ ] Run `python -m pytest -q tests/test_source_manifest.py`. Expected: it identifies `scion-omaha-bots/shadow_log.csv`.
- [ ] After explicit confirmation, preserve the local file while removing it from Git's index:

```powershell
git rm --cached -- scion-omaha-bots/shadow_log.csv
git check-ignore -v -- scion-omaha-bots/shadow_log.csv
```

Expected: the file remains on disk and `.gitignore` explains its exclusion.

- [ ] Delete `scion-omaha-bots/requirements.txt`. Use `scion-omaha-bots/pyproject.toml` as the sole dependency declaration.
- [ ] Update install docs to use:

```powershell
python -m pip install -e .
python -m pip install -e ./scion-omaha-bots
# Only when OpenBB research adapters are required:
python -m pip install -e "./scion-omaha-bots[research]"
```

- [ ] Remove `requirements.txt` from the architecture file manifest.
- [ ] Replace the stale checklist snapshot with a capability matrix derived from actual modules/tests. Remove historic pass counts and “not started” claims for backtest integration, streaming, paper replay, dashboard, and read-only LLM support. Keep incomplete provider/risk/options work labeled partial.
- [ ] Run the source-manifest test and the packaging/CLI tests:

```powershell
python -m pytest -q tests/test_source_manifest.py tests/test_root_packaging.py tests/test_cli_router.py scion-omaha-bots/test_cli_entrypoints.py
```

- [ ] Inspect `git diff --cached --name-status` before any commit. It must not contain unrelated paths.
- [ ] Optional isolated commit only after user approval:

```powershell
git add -- scion-omaha-bots/requirements.txt scion-omaha-bots/README.md docs/architecture/06-File-Manifest.md docs/implementation/trading-intelligence-checklist.md tests/test_source_manifest.py
git commit -m "chore(repo): remove dependency and runtime-state drift"
```

## Task 6: Run final verification without hiding the dirty-tree boundary

**Files:** no source changes expected.

- [ ] From the repository root, run:

```powershell
python -m ruff check stock_analysis tests scion-omaha-bots
python -m ruff format --check stock_analysis tests scion-omaha-bots
python -m pytest -q
python -m compileall -q stock_analysis scion-omaha-bots/src
```

- [ ] From `backtest-engine/`, run:

```powershell
python -m ruff check src tests
python -m ruff format --check src tests
python -m mypy src
python -m pytest -q
python -m compileall -q src
```

- [ ] Re-run these five semantic probes as tests, not ad hoc scripts: inclusive intraday end date, non-finite data rejection, oversell reservation/rollback, recovered close, and duplicate-journal sequence.
- [ ] Run `git status --short`, `git diff --check`, and `git diff --cached --name-status`. Report pre-existing changes separately from files changed by this plan.
- [ ] Do not describe optional Nautilus skips as failures. Do not claim complete if any required command is red or interrupted.

## Researched follow-on roadmap

These are intentionally not part of Tasks 1-6. Give each its own plan after the reliability slice is green.

### 1. Exchange-session contract

Add a small calendar service used by ingestion validation, replay, and paper order eligibility. It should expose sessions, UTC open/close, breaks, holidays, and special closes from `exchange-calendars`, rather than maintaining holiday tables locally ([official calendar implementation](https://github.com/gerrymanoim/exchange_calendars/blob/master/exchange_calendars/exchange_calendar.py)). Start with XNYS/XNAS and deterministic early-close fixtures. This should precede intraday execution realism.

### 2. SEC point-in-time fundamentals and catalyst timeline

Add a read-only SEC provider that stores CIK, accession number, filing/acceptance timestamps, form, period, taxonomy, unit, and revision provenance in `SnapshotEnvelope`. Fetch submissions/company facts and support fixture replay; never fetch during tests. The SEC provides submissions and XBRL company-fact JSON plus bulk archives ([official EDGAR API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)). Feed this lane into thesis and screening only through `PointInTimeStore.as_of` so future filings cannot leak backward.

Before scaling it, make `PointInTimeStore.as_of` provider-aware and replace its full-directory scan with a small append-only index. Define an explicit revision sequence; do not use lexical `revision_id` ordering as business chronology.

### 3. Backtest selection-bias reports

Add Deflated Sharpe Ratio and Combinatorially Symmetric Cross-Validation/Probability of Backtest Overfitting as diagnostics attached to the existing manifest and review artifact. Record the actual number of trials/candidates so the statistics cannot pretend only the winner was tested. DSR addresses multiple trials and non-normal returns ([Bailey and López de Prado](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551)); PBO estimates the likelihood that a selected backtest overfits ([primary paper record](https://escholarship.org/uc/item/4hn4t174)). Keep deterministic synthetic tests and avoid automatic strategy approval.

### 4. Execution realism without a second OMS

Add a configurable volume-participation ceiling and reject/no-fill behavior on zero-volume bars in the event-driven adapter. Record unfilled leaves and cost-model assumptions in results. Do not expand the local broker into production order routing; use the optional Nautilus adapter for advanced OMS/order-report/reconciliation behavior.

### 5. American option valuation as an optional adapter

The current analytics are European Black-Scholes. For US equity options, add an optional QuantLib adapter with American exercise and binomial/finite-difference engines instead of extending the existing pricing math by hand ([QuantLib option documentation](https://quantlib-python-docs.readthedocs.io/en/latest/instruments/options.html)). Require explicit dividend/rate/borrow inputs, provenance, convergence tests, and a declared fallback when the extra is unavailable.

### 6. Opt-in yfinance repair lane

If data repair is exposed, keep `repair=False` as the default. When enabled, persist the flag and before/after quality evidence because yfinance documents both repair coverage and possible false positives ([official repair guide](https://ranaroussi.github.io/yfinance/advanced/price_repair.html)). Never silently mutate a historical dataset already referenced by a run manifest.

## Explicit non-goals and removals not recommended

- Keep the flat Scion/Omaha launchers while docs and users still rely on `python main.py` and `python buffett_main.py`; they are compatibility wrappers, not duplicate implementations.
- Keep the local `PaperBroker` for deterministic replay, but cap its scope at market-style, long-equity research.
- Keep unavailable/null provenance semantics; do not replace missing market evidence with zeros.
- Do not split large analytics modules merely to reduce line counts. Split only when a feature above needs a stable new interface.
- Do not enable yfinance repair, live L2/OPRA, broker connectivity, or LLM write access by default.

## Completion criteria

- Every reproduced bug has a red test before its fix and a green regression afterward.
- Public inclusive date behavior is consistent across CSV, clean storage, yfinance, and Stooq translations.
- Canonical clean data contains no non-finite numeric values after validation.
- Paper sell leaves cannot exceed holdings, and failed events leave no partial state or processed-event marker.
- Closed streams remain closed after recovery, and recovered arrival sequences cannot collide.
- Dependency truth lives in `pyproject.toml`; tracked source inventory contains no `shadow_log.csv`; status docs match shipped capability.
- Root and backtest lint, format, type, compile, and full test gates pass with current output recorded.
- No unrelated user change was reset, staged, committed, or pushed.
