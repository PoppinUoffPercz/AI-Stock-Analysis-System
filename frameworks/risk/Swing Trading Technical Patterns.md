# Swing Trading Technical Patterns

> **Created:** 2026-07-06
> **Purpose:** Technical analysis patterns and entry signals for swing trading, with a contrarian value focus

---

## 1. The 52-Week Low Framework

### Burry's Entry Rules
1. **Buy within 10-15% of the 52-week low** that has demonstrated price support
2. Price must have touched the bottom zone multiple times without breaking it
3. Volume should dry up during consolidation (seller exhaustion)
4. **Hard Stop:** If the stock breaks to a NEW 52-week low, exit immediately

### Distance from 52W Low Calculation
```
Pct from Low = (Current Price - 52W Low) / 52W Low
```

| Distance | Signal | Action |
|----------|--------|--------|
| 0-5% | At the bottom | High risk, but potential capitulation buy if support holds |
| 5-10% | Near bottom (Burry zone) | Premier entry zone with confirmed support |
| 10-15% | Approaching bottom | Valid entry zone, watch for support validation |
| 15-25% | Bouncing | Too far for Burry entry, may indicate reversal started |
| >25% | Recovered | No longer a contrarian setup |

---

## 2. Support and Resistance

### Horizontal Support
- Price level where a stock has repeatedly bounced
- Multiple touches without breaking = stronger support
- Support forms when buying pressure equals selling pressure at a specific price

### Identifying Support in Code
```python
# Method: Check if the last 14 trading days have low standard deviation
recent_prices = hist['Close'].iloc[-14:]
recent_std_pct = recent_prices.std() / recent_prices.mean()
if recent_std_pct < 0.04:  # Less than 4% deviation
    is_support_base = True
```

### Resistance
- Price level where a stock has repeatedly been rejected
- Former support, when broken, becomes new resistance
- For Burry swing trades: set targets at prior resistance levels

---

## 3. Reversal Patterns

### Double Bottom (W-Pattern)
- Price hits a low, bounces, returns to test the low, bounces again
- Two distinct lows at approximately the same price level
- **Entry:** After the second bounce confirms, with volume increasing
- **Target:** Equal to the distance from the bottom to the intervening peak
- **Burry twist:** Look for double bottoms near 52-week lows with fundamental support

### Inverse Head and Shoulders
- Three valleys: left shoulder, deeper head, right shoulder
- Neckline = horizontal line connecting the two intervening peaks
- **Entry:** On breakout above the neckline
- **Target:** Distance from head to neckline, projected upward
- **Confirmation:** Requires volume increase on right shoulder breakout

### Cup and Handle
- Rounded bottom (the cup) followed by a small pullback (the handle)
- Cup takes weeks to months to form
- Handle should not drop below the cup's lower third
- **Entry:** On handle breakout to new highs
- **Target:** Cup depth projected upward from the rim

### Rounding Bottom (Saucer)
- Gradual, U-shaped bottom over extended period
- Volume typically dries up in the middle, increases at the edges
- Very long-term pattern, often 3-6 months
- **Entry:** On volume increase at the right edge

---

## 4. Volume Analysis

### Volume Exhaustion (Seller Drying Up)
- Price is near 52-week low
- Daily volume declining over 2-3 weeks
- Indicates sellers are exhausted
- Any positive catalyst can spark a rapid reversal

```python
# Volume exhaustion check
recent_volume = hist['Volume'].iloc[-20:]
avg_volume = hist['Volume'].iloc[-60:-20].mean()
volume_declining = recent_volume.mean() < avg_volume * 0.7  # 30%+ drop
```

### Volume Confirmation
- Breakout from support should be accompanied by ABOVE-average volume
- Low-volume bounce = suspicious (weak conviction)
- High-volume bounce = institutional interest confirmed

### Distribution Days
- Days with high volume and price decline > 1%
- Multiple distribution days near a bottom = institutional selling pressure
- Burry checks: if a breakout to new highs comes on below-average volume, conviction is low

---

## 5. Moving Averages for Swing Trading

### Burry's Approach
Burry uses "bare-bones" technical analysis — not complex indicators. Focus on:

### 50-Day and 200-Day Moving Averages
- **MA50 above MA200:** Golden Cross (long-term bullish)
- **MA50 below MA200:** Death Cross (long-term bearish)
- Price below both = depressed (Burry's hunting ground)
- Crossing above MA50 = short-term momentum shift

### 20-Day Moving Average
- Short-term trend filter
- Price crossing above MA20 after long decline = potential swing entry signal
- Price breaking below MA20 after a run = exit consideration

### Moving Average Stack (Bullish)
```
MA5 > MA10 > MA20 > MA50 > MA100 > MA200
```
All pointing upward = strong confirmed trend. NOT a Burry setup (too far from lows).

---

## 6. RSI (Relative Strength Index)

### Standard RSI(14) Interpretation
| RSI Level | Signal | Burry Context |
|-----------|--------|---------------|
| < 30 | Oversold | Potential contrarian buy (if support holds) |
| 30-50 | Weak | Still bearish, wait for confirmation |
| 50-70 | Neutral/Bullish | Trend forming, may be entering |
| 70-100 | Overbought | Exit signal for Burry (take profits) |

### RSI Divergence
- **Bullish divergence:** Price makes lower low, RSI makes higher low = momentum shifting
- **Bearish divergence:** Price makes higher high, RSI makes lower high = losing steam
- Divergence near 52-week low = strong contrarian entry signal

---

## 7. Bollinger Bands

- 20-period MA with 2 standard deviation bands
- Price touching lower band = oversold
- Price breaking below lower band with volume = capitulation (Burry buy signal if support holds)
- Band squeeze (narrowing) = volatility compression, breakout pending

---

## 8. Entry Signal Checklist (Burry Swing Trade)

- [ ] Stock trades within 10-15% of 52-week low
- [ ] Price has tested the low multiple times without breaking (support confirmed)
- [ ] Volume declining during consolidation (seller exhaustion)
- [ ] RSI(14) is oversold (< 30-35) or showing bullish divergence
- [ ] Fundamental metrics pass Burry filters (FCF yield > 5%, CR > 1.5, D/E < 1.0)
- [ ] News sentiment shows extreme pessimism or a reversal catalyst
- [ ] Insider buying or buyback announced
- [ ] Hard stop-loss identified at 52-week low - 3%
- [ ] Target 1 set at +20% from entry
- [ ] Target 2 set at +40% from entry

---

## Related Notes
- Michael Burry Methodology
- Contrarian Trading Framework
- Market Sentiment Indicators
- Financial Research Database
