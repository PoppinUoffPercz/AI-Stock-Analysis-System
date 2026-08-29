# Options and Short Interest for Contrarians

> **Created:** 2026-07-06
> **Purpose:** How to read options data and short interest for contrarian trading signals — and how Burry uses them

---

## 1. Burry's Options Usage

### Historical Examples
- **2005-2007:** Bought CDS (credit default swaps) on subprime MBS — option-like asymmetric bet
- **Q3 2025:** 66% of portfolio in PLTR put options, 13% in NVDA puts, 11% in PFE calls
- **Strategy:** Uses options for leverage on convictions, not for speculation
- **Common patterns:**
  - Long puts on overvalued stocks (limited downside = premium paid, large upside on crash)
  - Long calls on undervalued stocks (leverage without margin)

### Why Burry Uses Options
1. **Asymmetric exposure:** Pay small premium, potential 10x payoff
2. **Defined risk:** No margin calls, max loss = premium
3. **Capital efficiency:** Control large notional with small capital
4. **Privacy:** Options positions are harder to track than equity holdings

---

## 2. Short Interest Analysis

### Key Metrics

| Metric | Formula | Relevance |
|--------|---------|-----------|
| Short Interest | Total shares sold short | Raw bearish positioning |
| Short Interest % of Float | Short Shares / Float | Standardized bearishness |
| Days to Cover (Short Ratio) | Short Interest / Avg Daily Volume | Squeeze risk |
| Short Interest Change | Comparison period-over-period | Positioning trend |

### Thresholds

| Short % of Float | Signal | Trade Implications |
|-----------------|--------|-------------------|
| < 5% | Normal | Low squeeze risk |
| 5-15% | Elevated | Watch |
| 15-25% | High | Squeeze potential building |
| 25-40% | Very High | Strong squeeze setup (if fundamentals are sound) |
| > 40% | Extreme | Massive squeeze risk — one catalyst away from parabolic move |

### Days to Cover Benchmarks
| Days | Risk |
|------|------|
| < 3 | Low squeeze risk |
| 3-7 | Moderate |
| 7-15 | Elevated squeeze risk |
| > 15 | High squeeze risk (cant exit quickly) |

### Famous Squeeze Examples
- **VW/Porsche (2008):** Days to cover 7+, stock went from €200 to €1000+ in days
- **GameStop (Jan 2021):** 140% short interest (naked shorts), +1,600% in 2 weeks
- **TSLA (2020):** High short interest + S&P inclusion = "mother of all short squeezes"

### Burry's Stance
He looks for high short interest on stocks that are FUNDAMENTALLY SOUND near 52W lows. Shorts being wrong = binary catalyst for squeeze.

---

## 3. Put/Call Ratio Analysis

### Equity Put/Call Volume Ratio
- Buy puts = bearish positioning
- Buy calls = bullish positioning
- Ratio > 1.0 = more puts than calls (bearish sentiment)

### Interpretation

| P/C Ratio | Market State | Contrarian Signal |
|-----------|-------------|-------------------|
| < 0.6 | Complacency / Greed | Potential top |
| 0.6-0.8 | Normal optimism | Neutral |
| 0.8-1.0 | Mild concern | Begin search |
| > 1.0 | Fear | Contrarian buy setup forming |
| > 1.5 | Extreme fear | Strong contrarian buy signal |

### Individual Stock Put/Call
- High put/call on a single stock = bearish positioning
- Spike in put volume = potential capitulation OR insider info
- Watch put/call trends over weeks, not single day readings

### Put/Call Skew
- **Skew = OTM put IV / ATM call IV**
- High skew = market heavily buying downside protection
- Low skew = market not worried about crash
- Burry monitors this on the SPX (S&P 500 options) for macro fear levels

---

## 4. Implied Volatility (IV)

### IV Rank
- Rank of current IV vs 1-year IV range
- IV Rank = (Current IV - 52W Low IV) / (52W High IV - 52W Low IV)
- IV Rank > 50 = IV in upper half (options expensive)
- IV Rank < 20 = IV in lower range (options cheap)

### IV Percentile
- % of days with IV below current IV
- Less susceptible to outlier days than IV Rank

### Burry's Preferred IV Levels

| Purpose | Ideal IV Regime | Why |
|---------|----------------|-----|
| Buy puts (short) | Low IV (<30%) | Cheap premium, high leverage |
| Buy calls (long) | Low IV (<30%) | Cheap premium |
| Sell premium | High IV (>60%) | Collect rich premium |

### Calendar Events Affecting IV
- **Earnings:** IV spikes into earnings, drops after (IV crush)
- **FDA decisions:** Biotech IV spikes into PDUFA dates
- **Fed meetings:** Index IV rises before FOMC
- **Brexit/ Elections/ Wars:** Macro IV spikes

**Burry warning:** He never buys options right before earnings because of IV crush — wait until IV normalizes.

---

## 5. Max Pain Theory

### What is Max Pain?
The strike price where the most option holders lose the most money at expiration.

### Calculation
1. For each strike, calculate payout to all call holders (positive if stock > strike)
2. For each strike, calculate payout to all put holders (positive if stock < strike)
3. Find strike with maximum total payout (most loss from option holders)

### Interpretation
- Theory: Market makers will price stock toward max pain at expiration
- Empirical: Weak evidence for pinning to max pain, but clusters near it
- Best used as: confirmation of resistance/support zones, not standalone signal

### Burry Application
He doesn't actively use max pain for swing entries. He uses the options data primarily for:
1. Sentiment confirmation (high put volume = contrarian buy)
2. Squeeze identification (high short interest + high put open interest)
3. Conviction leverage (long-term OTM calls on deep value)

---

## 6. Gamma Exposure (GEX)

### What is GEX?
Total dollar value of options gamma by strike. Dealers hedge their books based on gamma, accelerating price moves.

### Signal
- **Positive GEX:** Dealers are long gamma — sell rallies, buy dips → price stabilization
- **Negative GEX:** Dealers are short gamma — buy rallies, sell dips → price acceleration
- Negative GEX environment = potential for large swings (both directions)

### Burry Connection
During the 2021 meme stock squeeze, GEX on GME was deeply negative, fueling the parabolic move. Burry (who was long GME earlier) understood this dynamic.

---

## 7. Unusual Options Flow

### What to Watch
- Large block trades (> $1M premium) on individual names
- Sweep orders (routed across multiple exchanges quickly)
- OTM calls/puts with sudden volume spikes
- Trades in EQUITIES that are heavily shorted

### Examples
- Massive OTM put purchases on a stock near highs = bearish signal
- OTM call purchases with no news = potential insider information
- Sudden put purchases against a long equity position = hedging
- Sudden call purchases on a 52W-low stock = potential bottoming signal

### Sources
- Unusual Whales (subscription)
- Options flow alert services (e.g., FlowAlgo, Cheddar Flow)
- Yahoo Finance options data (free but delayed)

---

## 8. Combining Options Data with Burry Screener

### Decision Tree
```
1. Stock passes fundamental screen (FCF yield > 8%, low debt)
2. Stock within 10-15% of 52W low
3. CHECK OPTIONS:
   - Short Interest > 15%? → Squeeze potential
   - Days to Cover > 7? → Squeeze risk elevated
   - Strong put volume recently? → Capitulation
   - Recent call buying? → Reversal catalyst emerging
4. iv_rank < 30? → Cheap to buy calls (leverage up)
5. iv_rank > 60? → Avoid buying options, use equity

PREMIUM PLAY:
- Buy OTM calls (~6mo expiry) if IV is low and squeeze potential is high
- Risk: 1-2% of capital on premium
- Reward: 5-10x if catalyst materializes

STOCK PLAY:
- Buy shares if IV is neutral, standard entry
- Risk: stop-loss at 52W low
- Reward: +20-40% mean reversion
```

---

## 9. Python Code for Options Analysis

```python
import yfinance as yf

def analyze_options(symbol):
    """Get IV and short interest data for contrarian analysis."""
    t = yf.Ticker(symbol)
    info = t.info
    
    # Short interest
    short_pct = info.get('shortPercentOfFloat', 0)
    short_ratio = info.get('shortRatio', 0)
    
    # Options dates
    dates = t.options
    
    # Get nearest expiration chain
    if dates:
        chain = t.option_chain(dates[0])
        calls = chain.calls
        puts = chain.puts
        
        # Implied volatility of ATM options
        atm_call_iv = calls[calls['inTheMoney'] == True].iloc[-1]['impliedVolatility'] if not calls.empty else 0
        atm_put_iv = puts[puts['inTheMoney'] == False].iloc[0]['impliedVolatility'] if not puts.empty else 0
        
        # Put/Call volume ratio
        put_vol = puts['volume'].sum()
        call_vol = calls['volume'].sum()
        pc_ratio = put_vol / call_vol if call_vol > 0 else 0
        
        return {
            'short_pct': short_pct,
            'short_ratio': short_ratio,
            'atm_call_iv': atm_call_iv,
            'atm_put_iv': atm_put_iv,
            'put_call_ratio': pc_ratio,
            'squeeze_setup': short_pct > 0.20 and short_ratio > 7
        }
    return None
```

---

## Related Notes
- Market Sentiment Indicators
- Contrarian Trading Framework
- Risk Management Ruleset
- Michael Burry Methodology
- Financial Research Database
