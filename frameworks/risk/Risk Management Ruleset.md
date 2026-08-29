# Risk Management Ruleset

> **Created:** 2026-07-06
> **Purpose:** Non-negotiable risk rules for protecting trading capital

---

## 1. The #1 Rule: Capital Survival

*"On a percentage basis it is much harder to replace lost dollars than gained dollars are to lose." — Michael Burry*

### The Math of Recovery
| Drawdown | Gain Needed to Recover |
|----------|----------------------|
| 10% | 11% |
| 20% | 25% |
| 30% | 43% |
| 40% | 67% |
| 50% | 100% |
| 60% | 150% |
| 70% | 233% |
| 80% | 400% |
| 90% | 900% |

A 50% drawdown requires a 100% gain just to get back to even. This is why loss mitigation is more important than profit maximization.

---

## 2. Position-Level Risk Rules

### The Hard Stop-Loss (Burry's Rule)
"If a stock breaks to a new low, in most cases I cut the loss."

- **Entry:** Only enter when within 10-15% of 52-week low
- **Stop Loss Place:** 3% below the 52-week low
- **Action on Trigger:** LIQUIDATE IMMEDIATELY. No rationalization, no "waiting for bounce."
- **No Averaging Down:** Never add to a losing position that is heading toward or has broken the stop

### Max Risk Per Trade
| Risk Tolerance | Max Risk per Position | Portfolio Context |
|----------------|----------------------|-------------------|
| Conservative | 0.5-1.0% | Large portfolio, capital preservation focus |
| Moderate (Burry default) | 1.0-1.5% | Swing trading, 12-18 positions |
| Aggressive | 1.5-2.5% | High conviction, smaller portfolio |
| Reckless (AVOID) | > 3% | Gamble-sized risk, high ruin probability |

### Risk-Adjusted Position Sizing Formula
```
Shares = (Account Equity × Max Risk per Trade) / (Entry Price - Stop Loss Price)
```

**Example:**
- Equity: $100,000
- Risk: 1.5% = $1,500
- Entry: $25.00
- Stop: $23.50
- Risk per Share: $1.50
- Shares = $1,500 / $1.50 = 1,000 shares = $25,000 position

---

## 3. Portfolio-Level Risk Rules

### Max Concurrent Positions
- **Burry approach:** 12-18 positions
- **Conservative:** 20-30 positions (more diversification)
- **Aggressive:** 8-12 positions (high concentration)

### Max Position Size
- Burry: 5-8% of capital per position
- The 8% cap is non-negotiable even for the highest conviction trades
- A Scion Score of 100+ unlocks the 8% cap; lower scores get proportionally less

### Max Sector Exposure
- No more than 25-30% of portfolio in one sector
- Diversification across depressed industries is the Burry approach
- This prevents a single sector cataclysm from wiping out multiple positions

### Portfolio Heat (Total Mapped Risk)
```
Portfolio Heat = Σ (Risk per Position) / Total Equity
```

| Portfolio Heat | Signal |
|----------------|--------|
| < 6% | Under-risked, leaving capital idle |
| 6-12% | Moderate, in Burry's sweet spot |
| 12-18% | Aggressive |
| > 18% | Over-leveraged, reduce positions |

### Cash Buffer
- Always maintain 5-15% cash for opportunistic entries
- If no candidates score above 25, sit in cash — don't force trades
- Burry: "If I have difficulty finding opportunities, I will allocate capital to simple cash."

---

## 4. Drawdown Management

### Max Acceptable Drawdown
- **Individual Position:** Max loss = stop-loss distance (typically 5-15%)
- **Portfolio Monthly Drawdown:** Max acceptable = 5-8%
- **Portfolio Peak-to-Trough Drawdown:** Max acceptable = 15-20%
- **Catastrophic Drawdown:** > 25% — triggers full portfolio review

### Drawdown Response Protocol

| Drawdown Level | Response |
|---------------|----------|
| 0-5% | Normal variance, keep trading |
| 5-10% | Reduce position sizes by 25% |
| 10-15% | Reduce position sizes by 50%, review all positions |
| 15-20% | Only new entries with Scion Score > 80 |
| > 20% | Pause trading, review strategy, go to cash |

---

## 5. Profit-Taking Rules

### Burry's Active Profit-Taking
*"I am not afraid to sell when a stock has a quick 40% to 50% a pop."*

| Profit Level | Action | Rationale |
|-------------|--------|-----------|
| +15% | Set trailing stop at -5% from peak | Lock in minimal gains |
| +20% | Sell 50% of position | Lock in significant profit |
| +30% | Move trailing stop to -8% from peak | Give rest room to run but protect |
| +40% | Sell remaining 100% | Burry's full liquidation target |
| +50%+ | Already exited | Short-term spikes are imbalances |

### When to Let a Winner Run (Exceptions)
- Scion Score was > 100 (exceptional setup)
- News catalysts keep improving (sentiment still rising)
- Price is trending up with ATR but not hitting extreme overbought
- Still below DCF intrinsic value (fundamental case intact)

---

## 6. Correlation Risk

### Understanding Correlation
If all 18 positions are in depressed retail stocks, a negative macro event for retail affects all 18. Effective portfolio risk is HIGHER than the sum of individual risks.

### Correlation Adjustment
```
Effective Risk = Portfolio Heat × (1 + Average Pairwise Correlation)
```

If average correlation = 0.5, effective risk = 1.5× the nominal portfolio heat.

### Burry's Approach: Sector Diversification
Burry "diversifies among various depressed industries" to keep correlation low:
- Having healthcare + retail + energy + fintech + defense ensures at most moderate correlation
- Confession: some topics like "recession" will still move all stocks down together (macro correlation)

### How to Check in Code
```python
import pandas as pd
import numpy as np

returns = pd.DataFrame(...)  # columns = symbols, rows = daily returns
correlation_matrix = returns.corr()
n = len(symbols)
# Extract upper triangle (excluding diagonal)
upper_tri = correlation_matrix.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
avg_corr = upper_tri.stack().mean()

# If avg_corr > 0.6, positions are too correlated — diversify more
```

---

## 7. Threading the Risk

### What is Threading?
Gradually building or exiting a position in "threads" (partial sizes) rather than entering a full position all at once.

### Scaling In (Burry rarely does this, but useful for risk reduction)
1. Enter 30% of full position
2. Add 30% if support holds for 1 week
3. Add remaining 40% if first window of good news comes
4. If the stock breaks support at any point, exit all

### Scaling Out (Burry does this at targets)
1. At +20%: sell 50% (locking profits)
2. At +35%: sell 25% more (letting rest ride)
3. At +40% or trend break: sell final 25%

---

## 8. Special Risk Considerations

### Earnings Risk
- If a swing position has earnings coming up within 2 weeks, reduce position by 50% or exit
- Earnings volatility can blow through stop loss due to gap-down
- Options positions can hedge earnings gap risk

### Macro/Tail Risk
- Maintain a "modified cash" buffer (e.g., short-term treasury ETF like SHY)
- During VIX > 40 spikes, reduce all positions by 20-30%
- Never be 100% invested in equities during regime change (rate hike cycles, recession signals)

### Liquidity Risk
- Only trade stocks with average daily volume > 500,000 shares
- Max position size should be < 1% of 20-day ADV (average daily volume) to avoid market impact
- Penny stocks and micro-caps have hidden exit difficulty

---

## 9. Daily Risk Checklist

- [ ] Check all open positions against their stop-loss levels
- [ ] Review portfolio heat (total mapped risk)
- [ ] Scan news for thesis-breaking developments on open positions
- [ ] Update 52-week low levels — if any stock creates a new 52W low, liquidate
- [ ] Check sector concentration (no single sector > 30%)
- [ ] Verify cash buffer is maintained (5-15%)
- [ ] Track portfolio drawdown from peak — if >10%, reduce sizing by 50%
- [ ] Check profit targets — execute scale-outs at +20% and liquidate at +40%

---

## Related Notes
- Position Sizing Models
- Michael Burry Methodology
- Contrarian Trading Framework
- Financial Research Database
