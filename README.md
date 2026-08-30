# Stock Analysis System

This project packages the executable research system behind the stock-analysis workflow:

- `scion-omaha-bots/` — Scion-Bot (Michael Burry-style swing analysis) and Omaha-Bot (Warren Buffett-style quality-compounder analysis).
- `backtest-engine/` — research-first strategy testing: VectorBT discovery, Backtrader validation, and validation/reporting utilities.
- `frameworks/` — the agent profiles, prompts, methodologies, risk rules, data-source definitions, and model-facing skills used to guide analysis.
- `docs/` — architecture, operating procedures, and backtesting design notes.

## Quick start

### Dual agents

```powershell
cd scion-omaha-bots
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Scion-Bot (Burry-style swing system)
python main.py screener
python main.py analyze PFE

# Omaha-Bot (Buffett-style compounder system)
python buffett_main.py screener
python buffett_main.py analyze KO
```

The bots are paper-trading/research tools. They do not execute real trades. Optional OpenBB, Obsidian, and WhatsApp integrations require separate local configuration and credentials.

### Backtesting engine

```powershell
cd backtest-engine
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

bte discover --strategy sma_cross --days 756 --seed 42
bte validate --strategy sma_cross --days 756 --seed 42
bte report --run-id <run-id-from-discover-or-validate>
python -m pytest -q
```

Read `docs/architecture/12-Backtest-Engine.md` for the intended discovery → validation → replay workflow.

## Framework order

1. Read `frameworks/agents/` for the Scion/Omaha personas and agent definitions.
2. Read `frameworks/prompts/` for reusable research and council prompts.
3. Read `frameworks/methodologies/` and `frameworks/risk/` for the investment and risk rules.
4. Read `frameworks/skills/` for model-facing operating instructions such as the credit-monitor skill.
5. Use `docs/architecture/` for system wiring, data flow, and operational details.

## Provenance

The source inventory and exclusions are recorded in `SOURCE-MANIFEST.md`. Generated reports, portfolios, logs, caches, backups, downloaded data, personal configuration, and credentials are intentionally excluded.

This repository is for research and education only and is not financial advice.
