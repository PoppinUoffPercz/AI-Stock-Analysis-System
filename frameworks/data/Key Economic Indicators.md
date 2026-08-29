# Key Economic Indicators

> **Created:** 2026-07-06
> **Purpose:** Macro economic indicators that affect market direction — for contextualizing swing trades

---

## 1. Interest Rates & Federal Reserve

### Federal Funds Rate
- **What:** The overnight lending rate between banks; set by FOMC
- **Why It Matters:** Sets the baseline for all borrowing costs in the economy
- **Source:** FRED (`FEDFUNDS`), Fed press releases

| Rate Environment | Impact on Stocks | Burry Context |
|-----------------|-------------------|---------------|
| Cuts (lowering) | Bullish (cheap capital) | Stats growth, but watch for euphoria |
| Holds (stable) | Neutral-positive | Normal stock-picking environment |
| Hikes (raising) | Bearish (capital costs rising) | Value stocks better, growth gets de-rated |
| Emergency cuts | Panic mode | Contrarian buy zone for quality |

### Yield Curve (10Y - 2Y Treasury)
- **What:** Spread between 10-year and 2-year Treasury yields
- **Source:** FRED (`T10Y2Y`)

| Signal | Implication |
|--------|-------------|
| Normal (positive slope) | Healthy economy, stocks generally bid |
| Flat (~0) | Late cycle, caution |
| Inverted (negative) | Recession warning, historically accurate |
| Steep (extreme positive) | Recovery from crisis mode |

### Yield Curve Inversion & Recession Probability
- 10Y-3M inversion has preceded every US recession since 1970
- Average lead time from inversion to recession: 12-18 months
- Burry tracks this as a macro overlay for positioning

---

## 2. Inflation & Prices

### CPI (Consumer Price Index)
- **What:** Change in prices of a basket of consumer goods
- **Source:** BLS, FRED (`CPIAUCSL`)
- **Release:** Monthly, around 13th of following month

| CPI Print | Market Reaction |
|-----------|----------------|
| < 2%(annualized) | Risk-on, Fed loose, stocks up |
| 2-3% | Normal, Fed steady |
| 3-5% | Concerning, rate hike expectations |
| > 5% | High inflation, bearish for stocks |
| Deflation (< 0%) | Extreme fear, recession signal |

### PCE (Personal Consumption Expenditures)
- **What:** Fed's preferred inflation measure
- **Source:** FRED (`PCEPI`, `DPCCRG1M225SBEA`)
- **Release:** Monthly
- Used by Fed to determine whether to adjust rates

---

## 3. Employment

### Unemployment Rate
- **Source:** BLS, FRED (`UNRATE`)
- **Release:** First Friday of each month (Jobs Report)

| Rate | Signal |
|------|--------|
| 3-4% | Strong economy, wage pressure |
| 4-5% | Normal, healthy |
| 5-6% | Weak economy, watch |
| > 6% | Recession zone |
| Sudden increase (> 0.5% in one month) | Strong recession warning (Sahm Rule) |

### Non-Farm Payrolls (NFP)
- **What:** Number of jobs created/lost in economy (excluding farming)
- **Source:** BLS, FRED (`PAYEMS`)
- **Release:** First Friday of each month
- **Volatile Reaction:** Markets can move 1-2% on the report if it beats/misses expectations

### Initial Jobless Claims
- **Weekly** indicator of layoffs
- **Source:** FRED (`ICSA`)
- **Spike > 400K historically = recession signal**

---

## 4. GDP & Growth

### GDP Growth Rate
- **Source:** BEA, FRED (`GDP`, `A191RL1Q225SBEA`)
- **Release:** Quarterly (3 estimates: advance, preliminary, final)

| GDP Growth (Annualized) | Signal |
|------------------------|--------|
| > 3% | Strong expansion |
| 1.5-3% | Healthy |
| 0-1.5% | Slowing, watch |
| < 0% | Contraction (2 quarters negative = recession) |

---

## 5. Business & Manufacturing

### ISM Manufacturing PMI
- **Source:** ISM, FRED (`ISM_MANUFACTURING`)
- **Release:** Monthly, first business day

| PMI Reading | Signal |
|-------------|--------|
| > 60 | Booming, but possible overheating |
| 52-60 | Expansion |
| 50 | Break-even |
| 45-50 | Contraction |
| < 40 | Recession |

### ISM Services PMI
- **Source:** ISM, FRED (`ISM_SERVICES`)
- Same scale as Manufacturing but for service sector (which is ~80% of US economy)

---

## 6. Consumer Health

### Consumer Confidence Index (Conference Board)
- **Source:** Conference Board
- **Release:** Monthly, last Tuesday

| Level | Signal |
|-------|--------|
| > 100 | Optimistic, strong consumer spending |
| 80-100 | Normal |
| 60-80 | Cautious |
| < 60 | Pessimistic, spending cuts |

### Retail Sales
- **Source:** Census Bureau
- **Release:** Monthly
- Up = consumer spending healthy; Down = economic weakness

---

## 7. Housing

### Existing Home Sales & Housing Starts
- Leading economic indicator
- **Source:** FRED (`EXISTN`, `HOUST`)
- Burry connection: He spotted the 2005 housing bubble via this data

### Case-Shiller Home Price Index
- **Source:** S&P, FRED (`CSUSHPISA`)
- Home price appreciation; crash warning if accelerating 20%+ annually without income growth

---

## 8. Financial Conditions

### Chicago Fed National Financial Conditions Index (NFCI)
- **Source:** Chicago Fed, FRED (`NFCI`)
- Positive = tighter conditions (stress)
- Negative = looser conditions (risk-on)

### TED Spread (3M LIBOR - 3M Treasury)
- **Source:** FRED (`TEDRATE`)
- Measures interbank lending stress
- Spike > 100bps = credit stress

---

## 9. Currency & Commodities

### US Dollar Index (DXY)
- Strong USD: Tougher for US exporters, better for imports
- Weak USD: Helpful for exporters, inflationary
- Source: ICE, Yahoo Finance (`DX-Y.NYB`)

### WTI Crude Oil
- Source: Yahoo Finance (`CL=F`)
- High oil = inflationary pressure + consumer drag
- Crashes = recession risk for energy sector

### Gold
- Source: Yahoo Finance (`GC=F`)
- Safe haven during equity stress; inverse correlation with real rates

---

## 10. Market Breadth (Intraday Trading Signals)

### Advance-Decline Line
- Number of advancing stocks vs declining stocks
- Divergence with price index = bearish signal (few stocks carrying the market)

### McClellan Oscillator
- **Formula:** EMA(19) of (Advancers - Decliners) - EMA(39) of (Advancers - Decliners)
- > +100: Strong bullish breadth
- < -100: Strong bearish breadth
- Crossovers signal short-term momentum shifts

---

## 11. Using Macro Indicators in Scion-Bot

### Daily Macro Check
```python
# Pseudo-code for macro overlay
if vix > 30:
    MACRO_REGIME = "FEAR"
    # Increase Scion Score weights for fundamentally strong setups
    # Reduce position sizes to 3% max
elif vix < 13:
    MACRO_REGIME = "COMPLACENCY"
    # Don't initiate new Burry "ick" positions (already late)
    # Focus on exit discipline

if yield_curve_inverted and unemployment_rising:
    # Defensive mode; cash allocation up to 30%
```

### Monthly Macro Snapshot (Manual or Scheduled)
Create a status table once a month:
| Indicator | Current Reading | Status |
|-----------|-----------------|--------|
| Fed Funds Rate | X.XX% | ___ |
| 10Y-2Y Spread | X.XX% | ___ |
| CPI YoY | X.X% | ___ |
| Unemployment | X.X% | ___ |
| GDP Growth (latest Q) | X.X% | ___ |
| ISM Manufacturing | XX.X | ___ |
| VIX | XX.X | ___ |
| TED Spread | X.XX bps | ___ |

---

## Related Notes
- Market Sentiment Indicators
- Contrarian Trading Framework
- Michael Burry Methodology
- Financial Research Database
