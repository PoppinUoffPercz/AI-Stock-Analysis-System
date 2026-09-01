# Scion-Bot & Omaha-Bot: Dual-Agent Trading System

A Python-based paper trading system running two autonomous agents inspired by contrasting investment philosophies:

| Agent | Persona | Strategy | Horizon |
| :--- | :--- | :--- | :--- |
| **Scion-Bot** | Michael Burry | Swing-trading beaten-down "ick" stocks | Days to weeks |
| **Omaha-Bot** | Warren Buffett | Long-term quality compounding | Years to decades |

## Integrated CLI

From the repository root, use the canonical command:

```powershell
stock-analysis scion --watchlist LULU,PFE screener
stock-analysis omaha --watchlist KO,PG run
stock-analysis portfolio combined
stock-analysis research run --bot scion
```

Install this package with `python -m pip install -e scion-omaha-bots`.
The historical `python main.py` and `python buffett_main.py` commands remain
supported when run from this directory.

## Architecture

```
# Shared
notify.py                  WhatsApp alert bridge (via zappy-mcp)
requirements.txt           Python dependencies

# Scion-Bot (Burry — Swing Trading)
screener.py                Market scanner — finds "roadkill" near 52W lows
analyzer.py                Deep-dive DCF + NCAV + technical analysis
news_engine.py             News catalyst & sentiment monitoring
portfolio.py               Position tracking with stop-loss + profit targets
main.py                    CLI orchestrator

# Omaha-Bot (Buffett — Quality Compounder)
buffett_screener.py        Market scanner — finds wonderful businesses at fair prices
buffett_analyzer.py        Four Filters + Owner Earnings DCF deep-dive
buffett_portfolio.py       Long-term position tracker (no stop-losses)
buffett_main.py            CLI orchestrator
```

## Quick Start

### Scion-Bot (Burry Swing Trades)
```bash
python main.py screener              # Scan for swing candidates
python main.py analyze PFE           # Deep-dive a ticker
python main.py news                  # Scan for news catalysts
python main.py portfolio              # View positions
python main.py check                 # Check stop-losses/targets
python main.py add PFE --score 90    # Open a position
python main.py run                   # Full automated cycle
```

### Omaha-Bot (Buffett Long-Term Holdings)
```bash
python buffett_main.py screener       # Screen for quality compounders
python buffett_main.py analyze KO     # Deep-dive Coca-Cola
python buffett_main.py portfolio       # View positions
python buffett_main.py check          # Review intrinsic values
python buffett_main.py add KO         # Open a long-term position
python buffett_main.py trim KO --pct 25  # Trim overweight position
python buffett_main.py close KO       # Exit position (thesis break)
python buffett_main.py run            # Full review cycle
```

## Agent Profiles

- **Scion-Bot (Burry):** [`../frameworks/agents/Scion-Bot Agent Profile.md`](../frameworks/agents/Scion-Bot%20Agent%20Profile.md) — swing-trading with 52W low floors, 8% position caps, 100-200% turnover
- **Omaha-Bot (Buffett):** [`../frameworks/agents/Omaha-Bot Agent Profile.md`](../frameworks/agents/Omaha-Bot%20Agent%20Profile.md) — quality compounding with 25% position caps, no stop-losses, 5-15% turnover

## Key Differences

| Dimension | Scion-Bot (Burry) | Omaha-Bot (Buffett) |
| :--- | :--- | :--- |
| Horizon | Days to weeks | Years to decades |
| Universe | Beaten-down stocks near 52W low | Quality compounders with moats |
| Entry trigger | Price near 52W low + support holds | Fair price for a wonderful business |
| Positions | 12-18 | 5-12 |
| Max position | 8% | 25% |
| Risk mgmt | Hard stop-loss on 52W low break | No stop-loss; thesis break exits |
| Profit-taking | +20% scale out, +40% liquidate | Hold unless thesis breaks |
| Annual turnover | 100-200% | 5-15% |

## WhatsApp Notifications

Both agents support WhatsApp alerts. Configure `zappy-mcp` and run with:
```bash
python buffett_main.py run --notify --recipient "YOUR_CHAT_ID"
```

## Disclaimer

This is a research/educational tool. It does NOT execute real trades. All portfolio positions are tracked in local JSON files (paper trading). NOT financial advice.
