# Integrated CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide one `stock-analysis` command that exposes the Scion bot, Omaha bot, and backtest engine through clear namespaces while preserving the current commands and avoiding new network work or performance regressions.

**Architecture:** Keep the root CLI thin. It parses the namespace, builds a small context object, and forwards arguments to deep domain modules. Do not merge the two large bot orchestrators or copy their business logic into the root router. Use direct Python calls, lazy imports, and explicit adapters for the current flat-file bot layout.

**Tech Stack:** Python 3.12, `argparse`, the existing Scion/Omaha modules, the existing `backtest_engine.cli.main`, pytest, Ruff, MyPy, Hatchling.

## Global Constraints

- Preserve the existing `python main.py`, `python buffett_main.py`, and `bte` entry points during migration.
- The first integrated version must forward existing domain arguments without changing trading, scoring, data, or backtest behavior.
- Do not run live market requests, OpenBB, WhatsApp, vault access, or credential-dependent work in CLI tests or CI.
- Do not change the default state files until explicit path routing has tests.
- Keep imports lazy so `stock-analysis --help` works without importing heavy data and plotting libraries.
- Use small commits. Each task below should be independently reviewable and should leave its verification commands passing.

## Target command surface

The first public shape should be:

```text
stock-analysis scion --watchlist LULU,PFE screener
stock-analysis omaha --watchlist KO,PG run
stock-analysis backtest discover --strategy sma_cross --synthetic --days 200 --seed 42 --cost zero
```

After the compatibility layer is stable, add:

```text
stock-analysis portfolio combined
stock-analysis tracking report
stock-analysis tracking feedback
stock-analysis tracking daily-check
stock-analysis tracking show
stock-analysis credit status
stock-analysis debate AAPL --compile
```

Do not add a universal `evaluate` command yet. The project still needs a written contract for how screener signals become backtest inputs.

---

## Task 1: Freeze the command and exit-code contract

- [ ] Add `docs/architecture/13-Integrated-CLI.md`.
- [ ] Document the namespace map above, the existing commands forwarded by each bot, global option placement, and examples using deterministic backtest mode.
- [ ] Define that successful commands return `0`, parser errors return argparse errors, and domain failures return a nonzero code with a useful stderr message.
- [ ] Define that `--help`, `scion --help`, `omaha --help`, and `backtest --help` must not make network requests or write state.
- [ ] Add a small command contract test file at `tests/test_cli_contract.py` with the expected help text and the two deterministic examples below:

```text
python -m stock_analysis --help
python -m stock_analysis backtest discover --strategy sma_cross --synthetic --days 200 --seed 42 --cost zero
```

Verification:

```text
python -m pytest -q tests/test_cli_contract.py
```

Expected result: the test file is initially allowed to fail until the router in Task 3 exists; do not mark this task complete until the contract assertions are green.

Commit: `docs: define integrated cli contract`.

## Task 2: Make both existing bot entry points callable

Files:

- `scion-omaha-bots/main.py`
- `scion-omaha-bots/buffett_main.py`
- `scion-omaha-bots/test_cli_entrypoints.py`

- [ ] Extract each parser construction into `build_parser() -> argparse.ArgumentParser` without changing command names, options, defaults, or help wording unless the change is needed for integration.
- [ ] Change each entry point to `main(argv: Sequence[str] | None = None) -> int`.
- [ ] Pass `argv` to `parse_args` and return `0` after a successful command. Keep the current script behavior with `raise SystemExit(main())` under the `__main__` guard.
- [ ] Keep command handlers in their current files. Do not duplicate them in the root CLI.
- [ ] Add parser-only tests for `screener`, `analyze`, `portfolio`, `run`, Scion tracking commands, Omaha `trim`, Omaha `close`, and Omaha `combined`. These tests must not call yfinance.
- [ ] Add one test that calls `main(["--help"])` through the parser seam if the current argparse behavior makes that practical; otherwise test `build_parser()` and the returned namespace.

Verification:

```text
python -m pytest -q scion-omaha-bots/test_cli_entrypoints.py
python scion-omaha-bots/main.py --help
python scion-omaha-bots/buffett_main.py --help
```

Commit: `refactor: expose bot cli runner seams`.

## Task 3: Add the thin root router

Files to add:

- `stock_analysis/__init__.py`
- `stock_analysis/__main__.py`
- `stock_analysis/cli.py`
- `tests/test_cli_router.py`

- [ ] Build one root `argparse` parser with `scion`, `omaha`, and `backtest` subcommands.
- [ ] Use `argparse.REMAINDER` for the three domain namespaces so the root parser does not need to reimplement every existing domain option.
- [ ] Implement `main(argv: Sequence[str] | None = None) -> int` and keep all dispatch in small functions such as `_run_scion`, `_run_omaha`, and `_run_backtest`.
- [ ] Import the target domain module only inside its dispatch function. `stock_analysis.cli` import and root help must work without importing yfinance, vectorbt, Plotly, OpenBB, or numba.
- [ ] Call `backtest_engine.cli.main(domain_args)` directly. Do not spawn a subprocess and do not use a shell.
- [ ] During the compatibility period, use one clearly named loader for the current flat bot directory and one clearly named path adapter for `backtest-engine/src`. Keep these adapters in `stock_analysis/cli.py`; do not spread path mutations through domain modules.
- [ ] Normalize a legacy bot handler result of `None` to exit code `0`, while preserving a nonzero integer result.
- [ ] Return a clear nonzero error if a component is not installed or cannot be imported. Include the component name and the installation location in the message.
- [ ] Add tests for root help, each namespace help, dispatch with monkeypatched runner modules, unknown namespaces, and exit-code forwarding.

Verification:

```text
python -m pytest -q tests/test_cli_contract.py tests/test_cli_router.py
python -m stock_analysis --help
python -m stock_analysis scion --help
python -m stock_analysis omaha --help
python -m stock_analysis backtest --help
```

Commit: `feat: add integrated cli router`.

## Task 4: Add shared command adapters without merging bot logic

Files to inspect and adapt:

- `scion-omaha-bots/tracker.py`
- `scion-omaha-bots/report_card.py`
- `scion-omaha-bots/feedback.py`
- `scion-omaha-bots/daily_check.py`
- `scion-omaha-bots/debate.py`
- `scion-omaha-bots/credit_monitor.py`
- `scion-omaha-bots/buffett_main.py`

- [ ] Give each shared tool a callable parser and `main(argv: Sequence[str] | None = None) -> int` seam, or create one small adapter module when the file is currently library-only.
- [ ] Route `stock-analysis tracking`, `stock-analysis credit`, and `stock-analysis debate` directly to those seams.
- [ ] Move the combined portfolio display out of `buffett_main.py` into `scion-omaha-bots/combined_portfolio.py` only if extraction can reuse the current behavior unchanged. Keep `buffett_main.py combined` as a compatibility wrapper.
- [ ] Require an explicit bot selector where a shared operation needs one. Never silently run both agents for a command that can write state or send alerts.
- [ ] Add offline tests that use temporary files and monkeypatched market data. No shared adapter test may modify the repository state files.

Verification:

```text
python -m pytest -q tests/test_cli_router.py scion-omaha-bots/test_cli_entrypoints.py
python -m stock_analysis tracking --help
python -m stock_analysis credit --help
python -m stock_analysis debate --help
```

Commit: `feat: expose shared cli commands`.

## Task 5: Introduce explicit application paths

Files to add or modify:

- `stock_analysis/config.py`
- `scion-omaha-bots/portfolio.py`
- `scion-omaha-bots/buffett_portfolio.py`
- `scion-omaha-bots/tracker.py`
- `scion-omaha-bots/performance_tracker.py`
- `scion-omaha-bots/news_engine.py`
- `scion-omaha-bots/buffett_news_engine.py`
- `scion-omaha-bots/credit_monitor.py`
- `scion-omaha-bots/reflection.py`
- `tests/test_cli_paths.py`

- [ ] Add a frozen `AppPaths` object with `project_root`, `bot_state_root`, `backtest_data_root`, and `backtest_outputs_root`.
- [ ] Add root options before a namespace: `--state-root`, `--data-root`, and `--outputs-root`. Do not change the current default locations when these options are omitted.
- [ ] Thread explicit paths into portfolio managers, tracker files, performance logs, news state, reflection state, and credit state.
- [ ] Add `--outputs-root` support to the root backtest adapter and pass the resolved path through settings rather than changing the process working directory.
- [ ] Use `pathlib.Path` at the boundary and convert to strings only where legacy modules require strings.
- [ ] Test that a complete offline command writes only below `tmp_path`, and test that the default path values still point to the current project layout.

Verification:

```text
python -m pytest -q tests/test_cli_paths.py
python -m stock_analysis --state-root "$PWD/.tmp-state" backtest discover --strategy sma_cross --synthetic --days 200 --seed 42 --cost zero
```

On Windows PowerShell, use a real temporary directory in place of `$PWD/.tmp-state`. Remove that temporary directory after the test. Do not commit runtime files.

Commit: `refactor: make cli state paths explicit`.

## Task 6: Package the bot modules behind a stable import boundary

Files:

- `scion-omaha-bots/pyproject.toml`
- `scion-omaha-bots/src/scion_omaha_bots/`
- `scion-omaha-bots/main.py`
- `scion-omaha-bots/buffett_main.py`
- bot test files that import flat modules

- [ ] Move the flat bot modules into `scion-omaha-bots/src/scion_omaha_bots/` in small groups, starting with pure utilities and then domain modules.
- [ ] Replace implicit flat imports with package-relative imports inside the package.
- [ ] Put the stable `scion_main` and `omaha_main` runner functions in the package. Make the old top-level scripts compatibility wrappers only.
- [ ] Add a Hatchling package definition and a console entry point only after the package imports pass from an unrelated working directory.
- [ ] Update tests to import the package boundary. Keep a small compatibility test for the old scripts.
- [ ] Remove the root router path adapter only after this task passes in a clean environment.

Verification:

```text
python -m pip install -e scion-omaha-bots
python -c "import scion_omaha_bots"
python -m pytest -q scion-omaha-bots
```

Do not add a plugin registry or dynamic command discovery. The fixed command map is easier to test and has less startup work.

Commit: `refactor: package bot modules`.

## Task 7: Make installation and launch predictable

Files:

- root `pyproject.toml`
- root `README.md`
- `backtest-engine/pyproject.toml`
- `scion-omaha-bots/pyproject.toml`

- [ ] Add the root `stock-analysis` console script pointing to `stock_analysis.cli:main`.
- [ ] Keep `bte` and the two legacy bot script entry points documented as compatibility commands.
- [ ] Decide and document the supported install sequence for the separate component dependencies. Do not use a non-portable local file URL or silently install the large optional statistics stack.
- [ ] If a single root install is desired, declare the combined runtime dependencies once and verify that the resulting wheel contains the root router plus both packaged component namespaces. Otherwise, document the root launcher as a thin local workspace command with editable component installs.
- [ ] Make `python -m stock_analysis` and the installed `stock-analysis` command produce the same result.

Verification:

```text
python -m pip install -e .
stock-analysis --help
python -m stock_analysis --help
```

Compare the two help outputs. They must expose the same namespaces. Commit: `build: add stock-analysis console entry point`.

## Task 8: Add explicit workflows only after the seams are stable

- [ ] Implement `stock-analysis portfolio combined` by reusing the existing combined portfolio calculations and adding a read-only test fixture.
- [ ] Add `stock-analysis research run --bot scion` and `stock-analysis research run --bot omaha` only if the existing `run` behavior can be called without duplicating command handlers.
- [ ] Require `--bot scion|omaha` for any command that could write a portfolio, tracker, or alert state.
- [ ] Keep `stock-analysis backtest` as a separate namespace. Do not automatically run a live screener before a backtest.
- [ ] Add an integration test for the one useful offline path: `backtest discover --synthetic`.

Performance gate:

- [ ] Measure root help startup against direct `bte --help` and verify that lazy imports keep root help fast.
- [ ] Measure the synthetic backtest through `stock-analysis backtest` against direct `bte`; the root adapter must not add a subprocess or material runtime cost.
- [ ] Do not add asynchronous scheduling, plugin loading, or automatic dual-agent cycles in this milestone.

Commit: `feat: add explicit integrated workflows`.

## Task 9: Finish CI and documentation

Files:

- `.github/workflows/` workflow files
- `README.md`
- `scion-omaha-bots/README.md`
- `docs/architecture/01-Dual-Agent-System.md`
- `docs/architecture/02-CLI-Reference.md`
- `docs/architecture/08-Full-Operating-Manual.md`
- `docs/architecture/12-Backtest-Engine.md`
- `SOURCE-MANIFEST.md`

- [ ] Add a CI smoke job for root help, namespace help, and the deterministic synthetic backtest.
- [ ] Keep live market tests separate from the offline CLI job and mark them clearly.
- [ ] Run both existing test suites, Ruff, formatting checks, and MyPy after the package boundary is stable.
- [ ] Update every command example to use the canonical `stock-analysis` form, while retaining a short compatibility section for old commands.
- [ ] State which commands require network access, credentials, or local vault setup.
- [ ] Update `SOURCE-MANIFEST.md` for every added package, test, and documentation file.

Verification:

```text
python -m pytest -q
ruff check .
ruff format --check .
mypy backtest-engine/src
python -m stock_analysis --help
python -m stock_analysis backtest discover --strategy sma_cross --synthetic --days 200 --seed 42 --cost zero
```

Commit: `docs: document integrated cli and ci smoke checks`.

## Completion criteria

- [ ] A new user can install the documented dependencies and run one `stock-analysis` command.
- [ ] Scion, Omaha, and backtest behavior is still reachable without a compatibility break.
- [ ] Root and namespace help are offline and lazy.
- [ ] State and output locations are explicit and testable.
- [ ] The synthetic backtest is reproducible through the integrated CLI.
- [ ] Existing quality checks pass, and no performance regression is measured.
- [ ] The project does not yet claim that live research, portfolio actions, and backtesting are one automatic decision loop.
