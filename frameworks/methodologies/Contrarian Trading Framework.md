# Contrarian Trading Framework

> **Created:** 2026-07-06
> **Purpose:** Framework for identifying, executing, and managing contrarian swing trades in the Burry mold

---

## 1. The Contrarian Philosophy

Contrarian trading is NOT about doing the opposite of everyone for the sake of it. It's about:
1. **Identifying when crowd consensus is wrong** — finding where the market has systematically mispriced an asset
2. **Having conviction when others are fearful** — the courage to act against the prevailing narrative
3. **Waiting for confirmation** — not bottom-fishing blindly, but waiting for evidence the market is wrong

### Burry's Quote
*"I try to buy shares of unpopular companies when they look like roadkill, and sell them when they've been rehabilitated."*

---

## 2. The "Ick" Factor System

### What is the "Ick" Factor?
The visceral disgust reaction you feel when looking at a stock. The strongest "ick" stocks:
- Are hated by analysts (mostly sell or hold ratings)
- Have recent negative news cascades
- Show price declines of 30-60%+ from highs
- Face macro or sector headwinds
- Are discussed with contempt on financial media

### Scoring System (-100 to +100)

| "Ick" Signal | Score Modifier |
|--------------|----------------|
| Analyst downgrade cascade (> 3 in 30 days) | -15 |
| "Earnings miss" headline cluster | -10 |
| Sector-wide negativity (all peers down) | -10 |
| High short interest (> 15% float) | -10 (bullish contrarian) |
| Lawsuit or investigation announcement | -15 |
| Bankruptcy/speculation chatter | -20 (bullish if unfounded) |
| Insider selling cluster | -10 |
| Social media hatred (Reddit/FinTwit bearish) | -5 |
| Dividend cut or suspension | -20 |
| Guidance reduction | -15 |

| "Reversal" Signal | Score Modifier |
|-----|----------------|
| Insider buying announcement | +20 |
| Share buyback program launched | +15 |
| New contract win (material to market cap) | +15 |
| Lawsuit resolution/settlement | +10 |
| New product launch or approval | +15 |
| Activist investor disclosed position | +20 |
| Asset sale / restructuring announced | +10 |
| CEO replacement with turnaround expert | +15 |
| Beating depressed estimates (low bar) | +10 |
| Sector showing green shoots | +5 |

---

## 3. The Contrarian Entry Framework

### Step 1: Identify Extreme Pessimism
- News sentiment score < -30 (extreme panic)
- Put/Call ratio > 1.0
- AAII Bearish > 45%
- Fear & Greed Index < 25
- Short interest > 10% of float

### Step 2: Validate Fundamental Floor
- Current Ratio > 1.5 (survival liquidity)
- Debt/Equity < 1.0 (no imminent bankruptcy)
- FCF Yield > 5% (business generates cash)
- Positive EPS (not burning through equity)

### Step 3: Confirm Technical Support
- Stock within 10-15% of 52-week low
- Multiple tests of the low without breaking
- Volume exhaustion (declining daily volume)
- RSI(14) < 35 or bullish RSI divergence

### Step 4: Identify Catalyst (Optional but Strong)
- Positive catalyst news improving sentiment
- Insider buying announced
- Sector tailwinds emerging
- Short squeeze conditions present

### Step 5: Execute with Hard Stop
- Enter position at market or limit near support
- Set stop-loss at 52-week low - 3% (non-negotiable)
- Target 1: +20% (scale out 50%)
- Target 2: +40% (liquidate rest)
- Max position size: 5-8% of capital

---

## 4. When Contrarian Trading Fails

### Value Traps
A stock is cheap because it deserves to be cheap. The business is in secular decline.

**Warning Signs:**
- Revenue declining 3+ consecutive years
- Margins shrinking with no bottom
- Industry disruption (technology replacing the business)
- Management denial or refusal to adapt
- Negative FCF for 2+ consecutive years

### Catching Falling Knives
The stock hasn't actually found support yet — it just looks like it has.

**Protection:**
- The 52-week low stop-loss rule is non-negotiable
- Wait for a double bottom confirmation (2 tests of the low)
- Volume must dry up before entering (sellers exhausted)
- Don't add to a losing position (no averaging down)

### Wrong Sector, Right Stock
The company is fine, but the entire sector is in a structural decline.

Example: Buying a great newspaper company in 2005 — cheap fundamentals, declining industry.

**Solution:** Check if sector headwinds are cyclical (temporary) or secular (permanent).

---

## 5. The Contrarian Exit Framework

### Profit-Taking Ladder (Burry Style)
| Trigger | Action | Rationale |
|---------|--------|-----------|
| +20% gain | Sell 50% of position | Lock in profits, let rest run |
| +40% gain | Sell remaining 100% | Short-term spikes are temporary imbalances |
| Break 52W low | Sell immediately | The thesis is broken — cut loss |
| Thesis invalidated | Sell regardless of P&L | New information contradicts original thesis |
| Portfolio rebalance needed | Trim or exit | Capital needed for better opportunity |

### When NOT to Exit
- Stock bouncing between +10% and -5% on normal volatility → hold
- Price above 50-day MA and trending up → hold
- News sentiment improving steadily → hold
- Position is still within 20% of 52W low → still cheap enough to hold

---

## 6. Contrarian Sectors That Frequently Produce "Ick" Setups

| Sector | Common Fear Catalysts | Typical Recovery Drivers |
|--------|----------------------|------------------------|
| **Retail** | Same-store sales decline, mall traffic drop, Amazon threat | Turnaround plan, new CEO, e-commerce pivot |
| **Energy** | Oil price crash, OPEC decisions, ESG pressure | Oil price recovery, cost cutting, M&A |
| **Biotech/Pharma** | Drug trial failure, patent cliff, pipeline concerns | Drug approval, M&A, new pipeline success |
| **Financials** | Rate decisions, credit losses, regulatory fines | Rate normalization, dividend restoration |
| **Telecom** | Subscriber loss, competitive pressure, debt | Merger, dividend cut (cleaning up), fiber buildout |
| **Semiconductors** | Inventory glut, China tension, demand cycle | Chip cycle recovery, AI demand, fab utilization |
| **Real Estate** | Interest rates, REIT dilution, occupancy rates | Rate cuts, sector consolidation, REIT buybacks |

---

## 7. Reading the Market for Contrarian Clues

### Analyst Rating Extremes
- Stock with 80%+ sell ratings → potential contrarian buy (capitulation)
- Stock with 90%+ buy ratings → potential contrarian sell (euphoria)

### Media Narrative Shifts
- "The death of retail/X" articles peaking → narrative exhausted, bottom forming
- "Can't lose" articles flowing → greed peaking, top forming
- Track keyword frequency in financial media

### Sentiment Turn Signals
- When bearish sentiment stops declining despite more bad news = capitulation
- When bullish sentiment stops rising despite good news = exhaustion
- These divergence signals often precede reversals by 1-3 months

---

## 8. Complete Workflow for Scion-Bot

```
1. SCREEN: Find stocks within 15% of 52W low
2. FILTER: Fundamental metrics pass Burry criteria (FCF, debt, liquidity)
3. ANALYZE: News sentiment for "ick" factor and reversal catalysts
4. CHECK: Technical support validated (double bottom, volume exhaustion)
5. SCORE: Calculate Scion Score (0-100+)
6. RANK: Sort all candidates by Scion Score
7. SELECT: Take top 1-3 candidates that score > 50
8. DEEP-DIVE: Run DCF and NCAV valuation analysis
9. ENTER: Open position with hard stop-loss at 52W low
10. MONITOR: Check daily for stop-loss triggers, news catalysts, and profit targets
11. SELL: Exit at +20% (partial), +40% (full), or on 52W low break
12. ROTATE: Reallocate freed capital to new candidates
```

---

## Related Notes
- Michael Burry Methodology
- Market Sentiment Indicators
- Value Investing Metrics
- Swing Trading Technical Patterns
- Position Sizing Models
- Financial Research Database
