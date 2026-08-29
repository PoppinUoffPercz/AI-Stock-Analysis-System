# Scion Bot Agent Reference

> **Created:** 2026-07-06
> **Purpose:** Links to the Michael Burry trading agent codebase at `./scion-omaha-bots\`

---

## Codebase Location
`./scion-omaha-bots\`

---

## Module Inventory

| File | Purpose | Status |
|------|---------|--------|
| `burry_agent_profile.md` | Agent persona, trading ruleset, swing-trading variant with news intake | Complete |
| `screener.py` | Market scanner — finds "ick/roadkill" stocks near 52W lows with strong fundamentals | Tested |
| `analyzer.py` | Deep-dive: DCF, Graham Net-Net, balance sheet audit, technical levels, news catalyst | Tested |
| `news_engine.py` | Continuous news monitoring — detects extreme panic, reversal catalysts, thesis-breaking news | Tested |
| `portfolio.py` | Position tracking — 12-18 max, hard stop-loss on 52W low break, +20% scale-out, +40% liquidate | Tested |
| `notify.py` | WhatsApp alert bridge via zappy-mcp (stdio + WebSocket modes) | Tested |
| `main.py` | CLI orchestrator: screener, analyze, news, portfolio, check, add, run | Tested |
| `requirements.txt` | Python dependencies (yfinance, pandas, tabulate, numpy, websockets) | Created |
| `README.md` | Project documentation | Created |

---

## CLI Commands

```bash
# Run the screener on the default watchlist
python main.py screener

# Deep-dive a specific ticker
python main.py analyze PFE

# Scan watchlist for news catalysts
python main.py news

# View portfolio
python main.py portfolio

# Check all positions for stop-loss/target triggers
python main.py check

# Manually add a position
python main.py add PFE --score 90 --reasons "Near 52W low, high FCF yield"

# Full automated cycle (screen -> analyze -> check -> news -> alert)
python main.py run

# With WhatsApp notifications (requires zappy-mcp configured)
python main.py run --notify --recipient "PHONE_NUMBER@c.us"
```

---

## Burry's Trading Rulesets Implemented

### Screening Criteria
- Price within 10-15% of 52-week low
- Free Cash Flow Yield >= 5-8%
- Current Ratio >= 1.5-2.0
- Debt/Equity <= 0.5-1.0
- Insider ownership >= 10% (bonus)
- News sentiment: "ick" factor + reversal catalyst detection

### News Catalyst Detection
- **Extreme Panic ("Ick" Factor):** Negative news barrage + price holds support = capitulation buy signal
- **Reversal Catalyst:** Positive inflection in depressed stock (buyback, insider buy, contract win)
- **Thesis-Breaking News:** Bankruptcy, fraud, delisting warnings = immediate sell consideration

### Portfolio Management (Scion Ruleset)
- 12-18 concurrent positions max
- 3-8% max allocation per position (scaled by Scion Score)
- **Hard Stop-Loss:** Liquidate immediately if stock breaks to new 52-week low
- **Target 1 (+20%):** Scale out 50% of position
- **Target 2 (+40%):** Liquidate remaining position
- Expected annual turnover: 100-200%

---

## Burry's Key Numbers (Implementation)

| Metric | Code Threshold | Scion Score Points |
|--------|---------------|-------------------|
| Price vs 52W Low | <= 10% | +30 |
| Price vs 52W Low | 10-15% | +20 |
| Support Base | Low recent volatility | +20 |
| Current Ratio | >= 2.0 | +15 |
| Current Ratio | 1.5-2.0 | +10 |
| Debt/Equity | <= 0.50 | +15 |
| Debt/Equity | 0.50-1.0 | +10 |
| FCF Yield | >= 8% | +20 |
| FCF Yield | 5-8% | +10 |
| Extreme Panic News | Score < -25 + near low | +10 |
| Reversal News | Score > +25 | +10 |

Minimum threshold to appear in results: 25 points

---

## WhatsApp Notifications

To receive alerts on your phone:
1. Configure `zappy-mcp` (in `./zappy-mcp\`) with your WhatsApp
2. Find your chat ID via `list_chats`
3. Add to `.zappy-mcp.json` with `canSend: true`
4. Run commands with `--notify --recipient "YOUR_CHAT_ID"`

---

## Future Enhancements (Not Yet Built)

- [ ] Alpaca paper trading integration for auto-execution
- [ ] Backtesting engine with historical Burry screener rules
- [ ] Real-time news stream (vs daily poll)
- [ ] Multi-asset support (ETFs, bonds alongside equities)
- [ ] Options flow integration (unusual options activity alerts)
- [ ] Macro regime detection (automate daily VIX/yield curve checks)
- [ ] Machine learning sentiment classifier (vs keyword-based)

---

## Related Notes
- Michael Burry Methodology
- Contrarian Trading Framework
- Value Investing Metrics
- Swing Trading Technical Patterns
- Market Sentiment Indicators
- Position Sizing Models
- Risk Management Ruleset
- Financial Research Database
