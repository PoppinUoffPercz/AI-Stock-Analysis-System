# Source Manifest

This project is assembled from the live source projects and the model-facing framework definitions. The source projects were not modified.

## Included

- `scion-omaha-bots/`: executable Python source, tests, requirements, profiles, and portable launchers from the local Scion-Bot source project.
- `backtest-engine/`: source, tests, notebooks, strategies, CI/configuration, and hypotheses from the local backtesting-engine source project.
- `frameworks/`: agent definitions and research framework notes from the bot project and Obsidian vault.
- `docs/architecture/`: directly related system guides and backtesting design notes from the Obsidian vault.

## Excluded

- Generated ticker reports, screener outputs, daily briefs, debates, and news outputs.
- Portfolio/trade/reflection JSON and CSV state, logs, backups, downloaded data, caches, virtual environments, and editor configuration.
- Obsidian web clippings, mortgage co-pilot notes, voice/setup notes, and external OpenBB/WhatsApp credentials/configuration.

## Final Files

| Path | Size |
|---|---:|
| `.gitignore` | 0.5 KB |
| `backtest-engine/.github/workflows/ci.yml` | 0.4 KB |
| `backtest-engine/.gitignore` | 0.2 KB |
| `backtest-engine/.pre-commit-config.yaml` | 0.6 KB |
| `backtest-engine/data/.gitkeep` | 0 KB |
| `backtest-engine/notebooks/quick_ticker_check.py` | 1 KB |
| `backtest-engine/notebooks/strategy_bench.py` | 7.4 KB |
| `backtest-engine/outputs/.gitkeep` | 0 KB |
| `backtest-engine/pyproject.toml` | 3.2 KB |
| `backtest-engine/README.md` | 0.9 KB |
| `backtest-engine/src/backtest_engine/__init__.py` | 0.1 KB |
| `backtest-engine/src/backtest_engine/cli.py` | 6.3 KB |
| `backtest-engine/src/backtest_engine/config.py` | 1.8 KB |
| `backtest-engine/src/backtest_engine/data/__init__.py` | 0 KB |
| `backtest-engine/src/backtest_engine/data/clean.py` | 3.9 KB |
| `backtest-engine/src/backtest_engine/data/ingest.py` | 3.3 KB |
| `backtest-engine/src/backtest_engine/data/sources/__init__.py` | 0 KB |
| `backtest-engine/src/backtest_engine/data/sources/base.py` | 8.9 KB |
| `backtest-engine/src/backtest_engine/data/store.py` | 2.8 KB |
| `backtest-engine/src/backtest_engine/data/universe.py` | 3.6 KB |
| `backtest-engine/src/backtest_engine/execution/__init__.py` | 0 KB |
| `backtest-engine/src/backtest_engine/execution/costs.py` | 5.4 KB |
| `backtest-engine/src/backtest_engine/metrics/__init__.py` | 0 KB |
| `backtest-engine/src/backtest_engine/metrics/core.py` | 6.5 KB |
| `backtest-engine/src/backtest_engine/metrics/tearsheet.py` | 5.3 KB |
| `backtest-engine/src/backtest_engine/pipeline/__init__.py` | 0 KB |
| `backtest-engine/src/backtest_engine/pipeline/discovery.py` | 1.7 KB |
| `backtest-engine/src/backtest_engine/portfolio/__init__.py` | 0 KB |
| `backtest-engine/src/backtest_engine/strategy/__init__.py` | 0 KB |
| `backtest-engine/src/backtest_engine/strategy/adapters/__init__.py` | 0 KB |
| `backtest-engine/src/backtest_engine/strategy/adapters/bt_adapter.py` | 9.7 KB |
| `backtest-engine/src/backtest_engine/strategy/adapters/vbt_adapter.py` | 7.1 KB |
| `backtest-engine/src/backtest_engine/strategy/base.py` | 1.8 KB |
| `backtest-engine/src/backtest_engine/strategy/bollinger.py` | 1.3 KB |
| `backtest-engine/src/backtest_engine/strategy/builtin.py` | 1.1 KB |
| `backtest-engine/src/backtest_engine/strategy/registry.py` | 0.9 KB |
| `backtest-engine/src/backtest_engine/strategy/result.py` | 1.5 KB |
| `backtest-engine/src/backtest_engine/strategy/rsi_reversion.py` | 1 KB |
| `backtest-engine/src/backtest_engine/strategy/signals.py` | 0.8 KB |
| `backtest-engine/src/backtest_engine/strategy/spec.py` | 1.4 KB |
| `backtest-engine/src/backtest_engine/validation/__init__.py` | 0 KB |
| `backtest-engine/src/backtest_engine/validation/monte_carlo.py` | 4.7 KB |
| `backtest-engine/src/backtest_engine/validation/permutation.py` | 2.9 KB |
| `backtest-engine/src/backtest_engine/validation/stability.py` | 3.3 KB |
| `backtest-engine/src/backtest_engine/validation/walk_forward.py` | 4.8 KB |
| `backtest-engine/strategies/bollinger_breakout/hypothesis.md` | 1.4 KB |
| `backtest-engine/strategies/rsi_reversion/hypothesis.md` | 1.6 KB |
| `backtest-engine/strategies/sma_cross/hypothesis.md` | 1.3 KB |
| `backtest-engine/tests/__init__.py` | 0 KB |
| `backtest-engine/tests/test_costs.py` | 4 KB |
| `backtest-engine/tests/test_data.py` | 9.4 KB |
| `backtest-engine/tests/test_m2_vbt.py` | 6.4 KB |
| `backtest-engine/tests/test_m4_bt.py` | 3.3 KB |
| `backtest-engine/tests/test_m5_portability.py` | 3.4 KB |
| `backtest-engine/tests/test_m6_validation.py` | 6.8 KB |
| `backtest-engine/tests/test_m7_reporting.py` | 3.7 KB |
| `backtest-engine/tests/test_m8_cli.py` | 2.2 KB |
| `backtest-engine/tests/test_smoke_m0.py` | 3.6 KB |
| `backtest-engine/tests/test_strategy_bollinger.py` | 2 KB |
| `docs/architecture/00-INDEX.md` | 1.7 KB |
| `docs/architecture/01-Dual-Agent-System.md` | 2.9 KB |
| `docs/architecture/02-CLI-Reference.md` | 4.4 KB |
| `docs/architecture/03-Credit-Monitor.md` | 2.3 KB |
| `docs/architecture/04-Vault-Structure.md` | 4.4 KB |
| `docs/architecture/05-Workflows.md` | 3.2 KB |
| `docs/architecture/06-File-Manifest.md` | 5.7 KB |
| `docs/architecture/07-WhatsApp-Alerts.md` | 1.5 KB |
| `docs/architecture/08-Full-Operating-Manual.md` | 22.7 KB |
| `docs/architecture/09-Performance-Tracker.md` | 8.4 KB |
| `docs/architecture/10-OpenBB-Integration.md` | 3.7 KB |
| `docs/architecture/11-Debate-Engine.md` | 3.1 KB |
| `docs/architecture/12-Backtest-Engine.md` | 7.9 KB |
| `docs/architecture/Backtest Engine Build Plan.md` | 21 KB |
| `docs/architecture/README.md` | 0.6 KB |
| `docs/README.md` | 0.5 KB |
| `frameworks/agents/Council Prompt.md` | 2.1 KB |
| `frameworks/agents/Omaha-Bot Agent Profile.md` | 8.3 KB |
| `frameworks/agents/Scion Bot Agent Reference.md` | 4.3 KB |
| `frameworks/agents/Scion-Bot Agent Profile.md` | 5.3 KB |
| `frameworks/agents/TradingAgents Comparison.md` | 8.5 KB |
| `frameworks/data/Financial Data Sources and APIs.md` | 9.1 KB |
| `frameworks/data/Financial Research Database.md` | 3.3 KB |
| `frameworks/data/Key Economic Indicators.md` | 6.8 KB |
| `frameworks/methodologies/Contrarian Trading Framework.md` | 7.6 KB |
| `frameworks/methodologies/Famous Contrarian Investors.md` | 6.7 KB |
| `frameworks/methodologies/Hedge Fund.md` | 2.5 KB |
| `frameworks/methodologies/Michael Burry Methodology.md` | 6.9 KB |
| `frameworks/methodologies/Value Investing Metrics.md` | 4.9 KB |
| `frameworks/methodologies/Warren Buffett Methodology.md` | 3.1 KB |
| `frameworks/prompts/Stock Research Prompts.md` | 5.7 KB |
| `frameworks/README.md` | 0.9 KB |
| `frameworks/risk/Market Sentiment Indicators.md` | 7.7 KB |
| `frameworks/risk/Options and Short Interest for Contrarians.md` | 8.8 KB |
| `frameworks/risk/Position Sizing Models.md` | 6.7 KB |
| `frameworks/risk/Risk Management Ruleset.md` | 7.6 KB |
| `frameworks/risk/Swing Trading Technical Patterns.md` | 6.3 KB |
| `frameworks/skills/credit-monitor/SKILL.md` | 3.5 KB |
| `README.md` | 2.3 KB |
| `scion-omaha-bots/analyzer.py` | 23.8 KB |
| `scion-omaha-bots/backfill_trades_timing.py` | 3.9 KB |
| `scion-omaha-bots/buffett_agent_profile.md` | 8.3 KB |
| `scion-omaha-bots/buffett_analyzer.py` | 29.6 KB |
| `scion-omaha-bots/buffett_main.py` | 34.9 KB |
| `scion-omaha-bots/buffett_news_engine.py` | 10 KB |
| `scion-omaha-bots/buffett_portfolio.py` | 14 KB |
| `scion-omaha-bots/buffett_screener.py` | 22.9 KB |
| `scion-omaha-bots/burry_agent_profile.md` | 5.3 KB |
| `scion-omaha-bots/calibrate_timing.py` | 4.7 KB |
| `scion-omaha-bots/check_consistency.py` | 0.6 KB |
| `scion-omaha-bots/check_open_fills.py` | 1.4 KB |
| `scion-omaha-bots/check_unadjusted.py` | 1.1 KB |
| `scion-omaha-bots/credit_monitor.py` | 23.3 KB |
| `scion-omaha-bots/daily_check.py` | 7.2 KB |
| `scion-omaha-bots/debate.py` | 18 KB |
| `scion-omaha-bots/diagnose_fills.py` | 1.3 KB |
| `scion-omaha-bots/earnings.py` | 3.9 KB |
| `scion-omaha-bots/entry_timing.py` | 12.1 KB |
| `scion-omaha-bots/feedback.py` | 14.7 KB |
| `scion-omaha-bots/find_fill_day.py` | 1.5 KB |
| `scion-omaha-bots/main.py` | 24.3 KB |
| `scion-omaha-bots/news_engine.py` | 9 KB |
| `scion-omaha-bots/notify.py` | 7.1 KB |
| `scion-omaha-bots/openbb_mcp_bridge.bat` | 0.2 KB |
| `scion-omaha-bots/openbb_mcp_proxy.py` | 3.5 KB |
| `scion-omaha-bots/performance_tracker.py` | 2.8 KB |
| `scion-omaha-bots/portfolio.py` | 14.7 KB |
| `scion-omaha-bots/README.md` | 3.6 KB |
| `scion-omaha-bots/reflection.py` | 6.3 KB |
| `scion-omaha-bots/report_card.py` | 11.8 KB |
| `scion-omaha-bots/requirements.txt` | 0.1 KB |
| `scion-omaha-bots/run_daily_screener.bat` | 0.1 KB |
| `scion-omaha-bots/screener.py` | 20.7 KB |
| `scion-omaha-bots/shadow_audit.py` | 8 KB |
| `scion-omaha-bots/smart_money.py` | 11.3 KB |
| `scion-omaha-bots/ta_lib.py` | 10.7 KB |
| `scion-omaha-bots/test_smart_money.py` | 1.5 KB |
| `scion-omaha-bots/test_stop_width.py` | 1 KB |
| `scion-omaha-bots/tracker.py` | 16.7 KB |
| `scion-omaha-bots/wait_for_openbb.py` | 0.6 KB |
| `SOURCE-MANIFEST.md` | 8.9 KB |