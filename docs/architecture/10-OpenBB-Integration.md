---
title: "OpenBB Integration"
date: 2026-07-08
tags:
  - docs
  - openbb
  - mcp
---

# OpenBB Integration

OpenBB v4.7.2 (Open Data Platform) is connected as an MCP server, giving the agent access to 20+ financial data providers through a unified interface.

## Architecture

```
opencode (this session)
  └─ MCP: openbb-mcp (local process via opencode.json)
       └─ OpenBB Core (openbb-core 1.6.13)
            ├─ equity      (yfinance, FMP, Polygon, Intrinio, Tiingo)
            ├─ news        (Benzinga, Biztoc)
            ├─ crypto      (yfinance, etc.)
            ├─ currency    (FRED, yfinance)
            ├─ economy     (FRED, IMF, OECD, BLS)
            ├─ etf         (yfinance, FMP)
            ├─ fixedincome (FRED)
            └─ sec         (SEC EDGAR, direct)
```

## Installation

```powershell
pip install openbb-mcp-server openbb-yfinance openbb-sec openbb-fred
```

The `openbb-mcp-server` starts a FastAPI server on port 8000 that translates REST endpoints into MCP tools.

## Configuration

Added to `~/.config/opencode/opencode.jsonc`:

```jsonc
"openbb": {
  "type": "local",
  "enabled": true,
  "command": [
    "...\\Scripts\\openbb-mcp.exe",
    "--default-categories", "equity,news",
    "--tool-discovery"
  ]
}
```

- `--default-categories equity,news` — Only exposes equity and news tools by default to keep token usage lean
- `--tool-discovery` — Agent can activate additional categories on demand (crypto, economy, etc.)

## How to Use

In any conversation, prompt the agent to use OpenBB. Examples:

```
use OpenBB to get the historical prices for NVDA
use OpenBB to screen for top daily gainers in the tech sector
use OpenBB to look up NVDA insider transactions
use OpenBB to get the latest news for AAPL
use OpenBB to search SEC filings for MSFT
use OpenBB to get FRED data for 10Y yield
```

The agent will automatically call the appropriate MCP tools when OpenBB is mentioned.

## Data Providers (Free Tier)

| Provider     | Data                                   | Needs API Key |
| :----------- | :------------------------------------- | :------------ |
| yfinance     | Prices, fundamentals, options          | No            |
| SEC EDGAR    | 10-K, 10-Q, 8-K filings                | No            |
| FRED         | Macro (GDP, CPI, yields, unemployment) | No (free key) |
| FMP          | Fundamentals, earnings, ratios         | Free key      |
| CBOE         | Options chains                         | No            |
| FINRA        | Short interest, trading data           | No            |
| CFTG         | Commodities data                       | No            |
| OECD         | Economic indicators                    | No            |
| BLS          | Employment data                        | No            |
| Congress.gov | Congressional trades                   | No            |

To add API keys for premium providers: `~/.openbb_platform/user_settings.json`.

## Using OpenBB via Python SDK (for scripts)

```python
from openbb import obb

# Historical prices
df = obb.equity.price.historical("AAPL").to_dataframe()

# Ticker info
info = obb.equity.info("NVDA").to_df()

# News
news = obb.news.company("MSFT").to_dataframe()

# SEC filings
filings = obb.sec.filings("GOOGL").to_dataframe()

# FRED data (need FRED_API_KEY)
gdp = obb.economy.gdp().to_dataframe()
```

## Provider-Specific Syntax

Some data requires specifying a provider (otherwise OpenBB picks a default):

```python
# Force yfinance provider
obb.equity.price.historical("AAPL", provider="yfinance")

# Force FRED provider
obb.economy.fred.series("GDP")

# Force SEC provider
obb.sec.filings("AAPL", form_type="10-K")
```

## Restart Note

If the MCP server is not responding, restart opencode — it auto-launches the MCP server on startup.