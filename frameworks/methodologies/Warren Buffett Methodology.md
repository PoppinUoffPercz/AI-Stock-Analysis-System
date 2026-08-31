# Warren Buffett Methodology

> **Agent:** Omaha-Bot (Quality Compounder Agent)
> **Strategy:** Buy wonderful businesses at fair prices, hold forever
> **Horizon:** Years to decades

## The Four Filters

Every potential investment must pass ALL FOUR:

### 1. Circle of Competence
- Can I understand this business?
- Can I project its economics 10 years forward?
- Avoid: rapid-change industries, complex financials, constant reinvention

### 2. Durable Competitive Advantage (Moat)
- Will the moat be WIDER in 10 years?
- Types: Brand power, switching costs, network effects, cost advantages, regulatory barriers
- Avoid: commodity businesses, narrowing moats

### 3. Honest & Competent Management
- Skin in the game (meaningful insider ownership)
- Capital allocation discipline (reinvest vs return capital)
- Transparent communication
- Avoid: empire builders, aggressive accounting

### 4. Reasonable Price
- Price vs intrinsic value (Owner Earnings DCF)
- Margin of safety required
- Better to miss than overpay

## Owner Earnings (1986 Formula)

**Owner Earnings = Net Income + D&A - Maintenance CapEx - ΔWorking Capital**

Owner Earnings > Reported Earnings for capital-intensive businesses.
Represents the cash that can be withdrawn annually without impairing competitive position.

## Key Screening Metrics

| Metric | Target | Weight in Screener |
| :--- | :--- | :--- |
| ROE | > 15% (ideally > 20%) | 20% (moat component) |
| Gross Margins | > 40% | 20% (moat component) |
| Operating Margins | > 20% | 15% (moat component) |
| Debt/Equity | < 0.50 | 20% (financial health) |
| P/E | < 25 (flexible) | 20% (valuation) |
| PEG | < 2.0 | 15% (valuation) |
| FCF/Owner Earnings Yield | > 5% | 15% (valuation) |
| Revenue Growth | > 7% | 15% (growth quality) |
| Insider Ownership | > 5% | 5% (bonus) |

## Portfolio Construction

- **5-12 positions** (concentrated conviction)
- **Max 25% per position** (Berkshire routinely 40-50% in single stock)
- **No price-based stop-loss** — hold through volatility
- **Exit triggers:** Thesis break, moat erosion, management degradation, extreme overvaluation
- **Cash as strategic asset:** Hold 30%+ waiting for fat pitches
- **VIX > 30:** BUY signal — deploy cash into quality names
- **VIX < 15:** SLOWDOWN — don't initiate at euphoric prices

## Contrast with Scion-Bot (Burry)

| Dimension | Omaha-Bot (Buffett) | Scion-Bot (Burry) |
| :--- | :--- | :--- |
| Horizon | Years to decades | Days to weeks |
| Universe | Quality compounders | Beaten-down "ick" stocks |
| Entry | Fair price for wonderful business | Near 52W low + catalyst |
| Positions | 5-12 (max 25% each) | 12-18 (max 8% each) |
| Exit | Thesis break | Stop-loss + profit targets |
| Turnover | 5-15% | 100-200% |
| Risk mgmt | Quality assessment | Technical stop-loss |

## Related Notes

- Michael Burry Methodology
- Financial Research Database
- Owner Earnings Formula
- Economic Moat Types
- Buffett's Circle of Competence

## Source Files

- `../agents/Omaha-Bot Agent Profile.md`
- `./scion-omaha-bots\buffett_screener.py`
- `./scion-omaha-bots\buffett_analyzer.py`
- `./scion-omaha-bots\buffett_portfolio.py`
- `./scion-omaha-bots\buffett_main.py`
