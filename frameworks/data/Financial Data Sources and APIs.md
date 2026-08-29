# Best Financial Data Sources and APIs

> **Created:** 2026-07-06
> **Purpose:** Comprehensive list of financial data APIs, platforms, and data sources for market analysis

---

## 1. Free / Freemium APIs

### Yahoo Finance (yfinance Python library)
- **URL:** https://finance.yahoo.com
- **Python:** `pip install yfinance`
- **Data:** Real-time quotes, historical OHLCV (1m to monthly), financial statements (annual/quarterly), options chains, news, holdings
- **Cost:** Free
- **Limits:** Unofficial API, can break; ~2,000 calls/hour soft cap
- **Best For:** Retail screeners, rapid prototyping, fundamental pulls
- **Usage:** 
  ```python
  import yfinance as yf
  t = yf.Ticker("AAPL")
  info = t.info           # Fundamental metrics
  hist = t.history("6mo") # Historical price data
  financials = t.financials  # Annual income statement
  balance = t.balance_sheet  # Annual balance sheet
  cashflow = t.cashflow   # Annual cash flow
  news = t.news           # Recent news
  options = t.option_dates() # Option expiry dates
  ```

### SEC EDGAR (Full-Text Search API)
- **URL:** https://efts.sec.gov/LATEST/search-index?q=
- **Data:** All SEC filings (10-K, 10-Q, 8-K, 13F, 4)
- **Cost:** Free
- **Best For:** Insider trading (Form 4), institutional holdings (13F), original annual reports (10-K footnotes)
- **Usage:** SEC has a public API at https://data.sec.gov/api/xbrl/companyfacts/CIK#####.json for structured financials

### FRED (Federal Reserve Economic Data)
- **URL:** https://fred.stlouisfed.org
- **Data:** 800,000+ economic time series (GDP, CPI, unemployment, Fed funds rate, yield curve, PMI, etc.)
- **Cost:** Free
- **Best For:** Macro overlays, economic indicators, yield curve tracking
- **Usage:** `pip install fredapi` with API key from FRED website

### Alpha Vantage
- **URL:** https://www.alphavantage.co
- **Data:** Real-time quotes, daily/adjusted history, technicals (SMA, EMA, RSI, MACD, ADX), fundamentals, sector performance
- **Cost:** Free tier (25 calls/day) / Premium ($50+/month for more)
- **Best For:** Beginners wanting free technical + fundamental data via clean API

### Finnhub
- **URL:** https://finnhub.io
- **Data:** Real-time quotes, news, insider transactions, earnings calendar, IPO calendar, economic calendar, company fundamentals
- **Cost:** Free tier (60 calls/min) / paid premium
- **Best For:** News aggregation and earnings calendar

### Tiingo
- **URL:** https://www.tiingo.com
- **Data:** Real-time prices, IEX historical data, news, fundamentals
- **Cost:** Free tier for end-of-day history; paid tier for intraday
- **Best For:** Historical price data for backtesting

### Financial Modeling Prep (FMP)
- **URL:** https://financialmodelingprep.com
- **Data:** Financial statements (10+ years), real-time quotes, stock screeners, insider trades, institutional holdings, DCF model inputs
- **Cost:** Free tier (250 calls) / Starter ($19/mo)
- **Best For:** Pre-built financial data API for DCF and valuation models

---

## 2. Broker APIs (For Execution)

### Alpaca
- **URL:** https://alpaca.markets
- **Data:** Real-time + historical data, paper trading API
- **Cost:** Free paper trading, commission-free live trading
- **Best For:** Algorithmic trading execution and paper testing

### Interactive Brokers (IBKR)
- **URL:** https://www.interactivebrokers.com
- **Data:** Full market data, options chains, advanced charting
- **Cost:** $0 commissions on stocks, monthly data subscriptions vary
- **Best For:** Professional-level market access, options trading, international exposure

### TradeStation
- **URL:** https://www.tradestation.com
- **Data:** Charting, fundamentals, options analytics
- **Cost:** Commissions vary
- **Best For:** Technical analysis toolset combined with execution

### Robinhood
- **URL:** https://robinhood.com
- **Data:** Limited (no official API)
- **Cost:** Commission-free
- **Best For:** Simple retail execution (avoid for algorithmic use)

---

## 3. Sentiment & Alternative Data

### CNN Fear & Greed Index
- **URL:** https://edition.cnn.com/markets/fear-and-greed
- **Data:** Daily Fear & Greed reading (0-100)
- **Cost:** Free
- **Best For:** Daily sentiment gauge

### AAII Sentiment Survey
- **URL:** https://www.aaii.com/sentimentsurvey
- **Data:** Weekly bullish/bearish % from retail investors
- **Cost:** Free summary
- **Best For:** Weekly contrarian signal

### Put/Call Ratio (CBOE)
- **URL:** https://www.cboe.com/us/options/market_statistics/
- **Data:** Daily put/call volume ratio
- **Cost:** Free
- **Best For:** Daily fear gauge

### Finviz
- **URL:** https://finviz.com
- **Data:** Stock screener (66+ filters), heatmaps, charts, news, insider trading
- **Cost:** Free (limited) / Elite ($39.50/mo)
- **Best For:** Visual screening and quick filtering by 52W low, insider ownership, FCF yield, etc.

### Quiver Quant
- **URL:** https://www.quiverquant.com
- **Data:** Alternative data: politician trading, insider trades, hedge fund 13F mimicking, crowdfunding data, government contracts
- **Cost:** Free tier / Premium
- **Best For:** Alternative data signals, copy-trading research

### Sentix / Market Vane
- **Data:** Investor sentiment surveys (Europe/global)
- **Cost:** Subscription
- **Best For:** International sentiment

---

## 4. Stock Screening Platforms

### Finviz (mentioned above)
Screener with 66+ filter criteria including fundamentals, technicals, descriptions

### TradingView
- **URL:** https://www.tradingview.com
- **Data:** Charts, screeners, PineScript for custom indicators
- **Cost:** Free / Pro ($14.95/mo) / Premium
- **Best For:** Charting, custom indicators, screener across asset classes

### Simply Wall St
- **URL:** https://simplywall.st
- **Data:** Visual snowflake valuation model for stocks
- **Cost:** Free basic / Pro for detailed
- **Best For:** Visual fundamental analysis at a glance

### Zacks
- **URL:** https://www.zacks.com
- **Data:** Zacks Rank system, analyst estimates
- **Cost:** Free basic
- **Best For:** Analyst estimate revisions and ranking

---

## 5. Macro & Economic Data

### FRED (covered above)
### Trading Economics
- **URL:** https://tradingeconomics.com
- **Data:** 196 countries economic indicators, forecasts
- **Cost:** Free limited / Premium
- **Best For:** International macro comparison

### IBKR TWS
- **Data:** Real-time fundamentals via Reuters
- **Cost:** With brokerage account
- **Best For:** Live fundamental estimates

### Quandl / Nasdaq Data Link
- **URL:** https://data.nasdaq.com
- **Data:** Alternative datasets, macro indicators, futures history
- **Cost:** Free / Premium
- **Best For:** Bulk historical data pulls

---

## 6. Options Data

### Yahoo Finance (options chain via yfinance)
- **Data:** Call/put chains, IV, open interest, volume
- **Cost:** Free
- **Usage:** `t.option_chain(date)` returns calls and puts DataFrame

### CBOE
- **URL:** https://www.cboe.com
- **Data:** VIX, put/call volume, open interest data
- **Cost:** Free
- **Best For:** Volatility and sentiment data

### Unusual Whales
- **URL:** https://unusualwhales.com
- **Data:** Unusual options flow, dark pool prints, congressional trades
- **Cost:** Subscription
- **Best For:** Options flow tracking

---

## 7. Real-Time WebSocket Data

### Polygon.io
- **URL:** https://polygon.io
- **Data:** Real-time websocket quotes, fundamentals
- **Cost:** Free tier / Paid
- **Best For:** Live data feed for algorithmic trading

### IEX Cloud
- **URL:** https://iexcloud.io
- **Data:** Real-time with SSE streams
- **Cost:** Free tier / Paid
- **Best For:** Live SMB-level data

### Alpaca Streams
- **Data:** Real-time price updates via WebSocket
- **Cost:** Free for paper account users
- **Best For:** Live paper trading integration

---

## 8. Recommended Scion-Bot Stack

For a complete Burry-inspired swing trading agent, the recommended stack:

| Need | Recommended Source | Cost |
|------|-------------------|------|
| Historical OHLCV + fundamentals | yfinance | Free |
| Insider trading + 13F | SEC EDGAR API | Free |
| Economic indicators | FRED | Free |
| Real-time news | yfinance .news / Finnhub | Free |
| Options chains + IV | yfinance / CBOE | Free |
| Sentiment | CNN Fear & Greed / AAII | Free |
| Screener manual validation | Finviz | Free |
| Paper trading execution | Alpaca | Free |
| Historical backtest | yfinance + custom scripts | Free |
| Live notifications | WhatsApp via zappy-mcp | Free |

### Total cost: $0
This proves you don't need premium data to do Burry-style value investing research. All the core data is freely available.

---

## 9. API Code Examples

### Fetching insider transactions from SEC EDGAR
```python
import requests

# Get Form 4 (insider trades) for AAPL
url = "https://efts.sec.gov/LATEST/search-index?q=Apple&dateRange=custom&startdt=2026-01-01&enddt=2026-12-31&forms=4"
headers = {'User-Agent': 'ScionBot/1.0 your-email@example.com'}
response = requests.get(url, headers=headers)
data = response.json()
```

### Fetching a macro indicator from FRED
```python
from fredapi import Fred
fred = Fred(api_key='YOUR_FRED_KEY')
gdp = fred.get_series('GDP')  # Quarterly GDP
vix = fred.get_series('VIXCLS')  # Daily VIX close
```

---

## Related Notes
- Key Economic Indicators
- Michael Burry Methodology
- Market Sentiment Indicators
- Financial Research Database
