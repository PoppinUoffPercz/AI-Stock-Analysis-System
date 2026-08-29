# Market Sentiment Indicators

> **Created:** 2026-07-06
> **Purpose:** Indicators and frameworks for measuring market fear, greed, and crowd positioning — essential for contrarian trading

---

## 1. VIX (Volatility Index)

### What It Measures
VIX is the CBOE Volatility Index — measures implied volatility of S&P 500 options over the next 30 days. Often called the "Fear Gauge."

### Interpretation

| VIX Level | Market State | Contrarian Signal |
|-----------|-------------|-------------------|
| < 13 | Extreme Complacency | Potential market top — sell signal |
| 13-18 | Calm / Normal | Neutral — no strong signal |
| 18-25 | Elevated Concern | Mild fear — watch for setups |
| 25-30 | High Fear | Begin looking for bottoms |
| > 30 | Extreme Fear | Strong contrarian buy signal |
| > 40 | Panic | Historically excellent buying opportunities |

### VIX Relative to 50-Day MA
- VIX well above 50-day MA = elevated fear spike
- VIX well below 50-day MA = complacency
- Burry uses VIX spikes as confirming signals when looking for entry points

### VIX Percentile (from TradingView Script)
```
VIX Percentile = rank of current VIX vs last 252 trading days
> 80th percentile = Extreme fear zone
< 20th percentile = Extreme greed zone
```

---

## 2. Put/Call Ratio (P/C Ratio)

### What It Measures
Ratio of put options volume (or open interest) to call options. High ratio = investors buying protection (bearish expectation). Low ratio = investors are bullish.

### CBOE Equity Put/Call Ratio (PCCE)

| P/C Ratio | Market State | Contrarian Signal |
|-----------|-------------|-------------------|
| < 0.6 | Extreme Greed | Potential top — be cautious |
| 0.6-0.8 | Normal optimism | Neutral |
| 0.8-1.0 | Mild concern | Watch for setups |
| > 1.0 | Fear / Defensive | Begin contrarian search |
| > 1.2 | Extreme Fear | Strong contrarian buy zone |

### Using P/C Ratio with VIX
- PCCE > 1.2 + VIX > 80th percentile = **Extreme Fear** = potential market bottom
- PCCE < 0.6 + VIX < 20th percentile = **Extreme Greed** = potential market top

---

## 3. CNN Fear & Greed Index

### What It Measures
Composite index (0-100) combining 7 sentiment indicators:
1. **Market Momentum:** S&P 500 vs 125-day MA
2. **Stock Price Strength:** 52-week highs vs lows
3. **Stock Price Breadth:** Adv/declining issues (McClennan Oscillator)
4. **Put/Call Ratio:** Equity P/C
5. **Junk Bond Demand:** Spread between junk and investment grade bonds
6. **Market Volatility:** VIX
7. **Safe Haven Demand:** Stocks vs. Treasury bonds (10-year)

### Interpretation

| Reading | Category | Signal |
|---------|----------|--------|
| 0-25 | Extreme Fear | Buying opportunity |
| 25-45 | Fear | Watch for bottom setup |
| 45-55 | Neutral | No signal |
| 55-75 | Greed | Caution |
| 75-100 | Extreme Greed | Sell/reduce risk |

### Historical Performance
- Sub-40 readings have coincided with better-than-average next-month S&P 500 returns
- The Fear & Greed Index is most useful as a **contextual** indicator, not a standalone signal

---

## 4. AAII Investor Sentiment Survey

### What It Measures
Weekly survey by American Association of Individual Investors asking members their 6-month market outlook: Bullish, Bearish, or Neutral.

### Contrarian Interpretation

| Bull % | Signal | Action |
|--------|--------|--------|
| > 55% | Extreme bullishness | Be cautious — potential top |
| 40-55%| Normal optimism | Neutral |
| 25-40%| Cautious | Start looking for setups |
| < 25% | Extreme bearishness | Strong contrarian buy signal |

| Bear % | Signal | Action |
|--------|--------|--------|
| > 50% | Extreme fear | Contrarian buy zone |
| 40-50%| Elevated fear | Watch for bottoms |
| 25-40%| Normal | Neutral |
| < 25% | Complacency | Potential top warning |

### Bull-Bear Spread
```
Spread = Bullish % - Bearish %
```
- Strongly negative spread (< -20%) = contrarian buy signal
- Strongly positive spread (> +30%) = contrarian sell/caution

---

## 5. Short Interest

### What It Measures
Number of shares sold short (not yet covered). High short interest indicates bearish positioning.

### Key Metrics

| Metric | Formula | Contrarian Signal |
|--------|---------|-------------------|
| Short Interest % of Float | Short Shares / Float | > 20% = squeeze potential |
| Days to Cover (Short Ratio) | Short Shares / Avg Daily Volume | > 10 days = high squeeze risk |
| Short Interest Ratio (SIR) | Total Short Interest / Avg Daily Volume | > 5 = elevated |

### Short Squeeze Mechanics
1. High short interest (> 20% of float)
2. Stock gets positive catalyst news
3. Short sellers rush to cover
4. Buying pressure from covering + regular buyers
5. Rapid price spike (20-50%+ in days)

### Burry Connection
Burry looks for stocks with high short interest AND strong fundamentals near 52-week lows. If shorts are wrong about a fundamentally sound company, the squeeze potential adds a second return catalyst on top of mean reversion.

---

## 6. BofA Fund Manager Survey (FMSA)

### Monthly survey of ~250 institutional fund managers:
- Cash allocation levels: > 5% = elevated fear, < 3.5% = greed
- Equity allocation vs bonds: extreme = contrarian signal
- Most crowded trade: when 50%+ agree on a trade, it's often wrong

---

## 7. Credit Spreads (Junk Bond Demand)

### ICE BofA US High Yield Index (option-adjusted spread)

| Spread (bps) | Signal | Market State |
|---------------|--------|---------------|
| < 300 | Extreme greed | Risk-on, complacency |
| 300-450 | Normal | Neutral |
| 450-600 | Elevated fear | Watch for bottoms |
| > 600 | Extreme fear | Contrarian buy zone |
| > 1000 | Panic | Crisis-level, strong buy |

**Interpretation:** Narrow spreads = risk appetite (greed). Wide spreads = risk aversion (fear). Credit markets often signal before equity markets.

---

## 8. Safe Haven Demand

### 10-Year Treasury vs Stocks
- When money flows from stocks to bonds (Treasury yields drop), it signals fear
- Burry monitors "flight to safety" as a capitulation indicator
- Extreme safe haven demand + fundamental support = contrarian buy setup

---

## 9. Combined Sentiment Framework for Scion-Bot

```python
def calculate_sentiment_signal(vix, put_call, fear_greed, aaii_bull, short_int_pct, credit_spread):
    """Combine all sentiment indicators into a single -100 to +100 score."""
    score = 0
    
    # VIX (weight: 25%)
    if vix > 30: score -= 25
    elif vix > 25: score -= 15
    elif vix < 13: score += 20
    
    # Put/Call (weight: 20%)
    if put_call > 1.2: score -= 20
    elif put_call > 1.0: score -= 10
    elif put_call < 0.6: score += 15
    
    # Fear & Greed (weight: 20%)
    if fear_greed < 25: score -= 20
    elif fear_greed < 40: score -= 10
    elif fear_greed > 75: score += 15
    
    # AAII Bullish (weight: 15%)
    if aaii_bull < 25: score -= 15
    elif aaii_bull > 55: score += 10
    
    # Short Interest (weight: 10%)
    if short_int_pct > 20: score -= 10  # High shorts = squeeze potential
    
    # Credit Spread (weight: 10%)
    if credit_spread > 600: score -= 10
    elif credit_spread < 300: score += 8
    
    return score
```

| Score | Signal | Action |
|-------|--------|--------|
| < -60 | Extreme Fear | Aggressive contrarian buying |
| -30 to -60 | Fear Zone | Begin screening for setups |
| -30 to +30 | Neutral | Normal market conditions |
| +30 to +60 | Greed Zone | Reduce risk, sell into strength |
| > +60 | Extreme Greed | Consider hedging or cash |

---

## Data Sources
- VIX: Yahoo Finance (`^VIX`), CBOE website
- Put/Call: CBOE data, Yahoo Finance
- Fear & Greed: CNN Business (edition.cnn.com/markets/fear-and-greed)
- AAII: aaii.com/sentimentsurvey
- Short Interest: Yahoo Finance, Finviz, Nasdaq.com
- Credit Spreads: FRED (St. Louis Fed), ICE BofA indices

---

## Related Notes
- Michael Burry Methodology
- Contrarian Trading Framework
- Key Economic Indicators
- Swing Trading Technical Patterns
- Financial Research Database
