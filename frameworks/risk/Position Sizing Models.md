# Position Sizing Models

> **Created:** 2026-07-06
> **Purpose:** Mathematical frameworks for determining how much capital to allocate per trade

---

## 1. Fixed Fractional Position Sizing

The simplest and most robust method. Risk a fixed percentage of equity per trade.

### Formula
```
Position Size = (Account Equity × Risk %) / (Entry Price - Stop Loss)
```

### Example
- Account: $100,000
- Risk: 1% ($1,000)
- Entry: $25.00
- Stop Loss: $23.50 (6% drop)
- Position Size = $1,000 / ($25.00 - $23.50) = 333 shares × $25 = $8,333

### Properties
- **Natural anti-martingale:** After losses, position shrinks automatically
- **No overfitting:** Doesn't depend on historical win rate or R/R
- **Scalable:** Works at $1,000 or $10,000,000
- **Disadvantage:** Doesn't optimize growth (slower than Kelly)
- **Recommended for:** Beginners, simple strategies, no hard edge data

### Burry Application
Burry uses a variant of fixed fractional with 5-8% max per position, but he adds fundamental conviction weighting. A higher Scion Score gets closer to the 8% cap.

---

## 2. Kelly Criterion

Mathematically optimal bet size that maximizes long-term geometric growth rate.

### Classic Kelly Formula (Binary Outcome)
```
f* = (b × p - q) / b
```
Where:
- `f*` = optimal fraction of capital to bet
- `p` = probability of winning
- `q` = 1 - p (probability of losing)
- `b` = win/loss ratio (payout odds)

### Example
- Win rate: 55% (p = 0.55)
- Win/loss ratio: 1.5:1 (b = 1.5)
- Kelly = (1.5 × 0.55 - 0.45) / 1.5 = 0.22 → 22% of capital

### Continuous Kelly (for trading returns)
```
f* = (μ - r) / σ²
```
Where:
- `μ` = expected annual return
- `r` = risk-free rate
- `σ` = annual volatility

### Kelly and Sharpe Ratio
```
f* = Sharpe / σ
```
A strategy with Sharpe 1.0 and 20% annual volatility → Kelly leverage = 5x.

### Fractional Kelly (CRITICAL — Always Use This)
| Kelly Fraction | Growth (vs Full) | Max Drawdown | Use Case |
|---------------|-------------------|-------------|----------|
| Full Kelly (100%) | 100% | 60-80% | Never recommended |
| Half Kelly (50%) | 75% | ~30-35% | Aggressive traders |
| Third Kelly (33%) | ~60% | ~20-25% | Moderate |
| Quarter Kelly (25%) | ~50% | ~15% | Conservative |

### Why Never Use Full Kelly
- 50-80% drawdowns in simulations
- Extremely sensitive to parameter estimation error
- Over-betting past the edge threshold → negative growth
- Under-betting just means slower growth, not ruin

### Multi-Asset Kelly
```
f* = Σ⁻¹ (μ - r·1)
```
Where Σ = covariance matrix. This is the Markowitz tangency portfolio without normalization.

**Problems:** Σ⁻¹ is unstable in high dimensions. Use shrinkage estimator (Ledoit-Wolf) + weight constraints.

---

## 3. Volatility-Adjusted Position Sizing (ATR-Based)

Adjusts position size based on current market volatility.

### Formula
```
Position Size = (Account Equity × Risk %) / (ATR × Multiplier)
```
Where:
- ATR = Average True Range (14 periods default)
- Multiplier = how many ATRs for your stop (typically 1.5-2.5)

### Example
- Account: $100,000
- Risk: 1.5% ($1,500)
- ATR(14): $1.20
- Stop: 2 × ATR = $2.40
- Position Size = $1,500 / $2.40 = 625 shares

### Properties
- Automatically shrinks position in volatile markets
- Enlarges position in calm markets
- Natural adaptation to changing market conditions
- Requires ATR calculation (extra step)

### ATR Calculation (Python)
```python
def atr(high, low, close, period=14):
    tr = pd.DataFrame({
        'hl': high - low,
        'hc': abs(high - close.shift(1)),
        'lc': abs(low - close.shift(1))
    }).max(axis=1)
    return tr.rolling(period).mean()
```

---

## 4. Risk Parity

Each position contributes equal risk to the portfolio, regardless of expected return.

### Formula
```
Position Weight_i = (1/σ_i) / Σ(1/σ_j)
```
Where σ_i = volatility of asset i.

### Example (3-asset portfolio):
- Stock A: vol 20%, Stock B: vol 15%, Stock C: vol 30%
- Inverse vol: A=5, B=6.67, C=3.33
- Total = 15
- Weights: A=33%, B=44%, C=22%

---

## 5. Portfolio Heat (Total Risk Budget)

### Concept
Monitor total risk across all open positions, not just per-trade risk.

```
Portfolio Heat = Σ (risk_per_position_i / total_equity)
```

### Rules
- Max portfolio heat: 6-8% (aggressive: 10-12%)
- If adding a new position would exceed heat limit, skip it
- Equally weighted (Burry): ~0.5% per position × 18 positions = ~9% max heat

### Correlation Adjustments
If positions are correlated (same sector), effective heat is higher:
```
Effective Heat = Portfolio Heat × (1 + avg_correlation)
```

---

## 6. Risk of Ruin

Probability of losing a defined fraction of capital over N trades.

### Formula (Simplified)
```
ROR = ((1 - edge) / (1 + edge))^N
```
Where:
- edge = (win_rate × avg_win) - (loss_rate × avg_loss)
- N = number of trades until ruin threshold

### Key Insight
A trader with 55% win rate and 1.5:1 R/R is profitable. The same trader risking 8% per trade instead of 1% faces 60-90% probability of ruin over 500 trades.

### Risk by Position Size (55% WR, 1.5:1 R/R)
| Risk per Trade | Ruin Probability (500 trades) |
|----------------|-------------------------------|
| 1% | < 1% |
| 2% | ~5% |
| 5% | ~30% |
| 8% | 60-90% |
| 10% | > 90% |

---

## 7. Burry-Inspired Sizing Framework

### Scion Scoring-Based Allocation

| Scion Score | Position Size (% of Capital) | Risk per Trade |
|-------------|------------------------------|----------------|
| 25-40 | 3% | 0.5-0.8% |
| 40-60 | 5% | 0.8-1.2% |
| 60-80 | 6% | 1.0-1.5% |
| 80-100+ | 8% (max) | 1.5-2.0% |

### Additional Rules
- Max 18 concurrent positions
- If 18 positions are filled with average 5-6% sizing, total exposure = 90-108% (slight leverage or near fully invested)
- Cash buffer maintained for opportunistic entries
- Sector limits: no more than 3 positions in the same sector

---

## 8. Practical Implementation (Python)

```python
def kelly_fractional(win_rate, avg_win, avg_loss, fraction=0.5):
    """Calculate fractional Kelly position size."""
    b = avg_win / avg_loss  # win/loss ratio
    p = win_rate
    q = 1 - p
    kelly = (b * p - q) / b
    return kelly * fraction

def fixed_fractional(equity, risk_pct, entry, stop):
    """Calculate fixed fractional position size."""
    risk_amount = equity * risk_pct
    risk_per_share = entry - stop
    shares = int(risk_amount / risk_per_share)
    return shares, shares * entry

def volatility_adjusted(equity, risk_pct, atr, multiplier=2.0):
    """Calculate ATR-based position size."""
    risk_amount = equity * risk_pct
    stop_distance = atr * multiplier
    shares = int(risk_amount / stop_distance)
    return shares
```

---

## Related Notes
- Risk Management Ruleset
- Michael Burry Methodology
- Swing Trading Technical Patterns
- Financial Research Database
