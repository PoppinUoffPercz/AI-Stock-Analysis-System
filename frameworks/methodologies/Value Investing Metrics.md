# Value Investing Metrics

> **Created:** 2026-07-06
> **Purpose:** Formulas and frameworks for fundamental valuation used by value and contrarian investors

---

## 1. Net Current Asset Value (NCAV) / Net-Net

Benjamin Graham's most conservative valuation method. A company trading below its NCAV is priced below its liquidation value.

### Quick NCAV Formula
```
NCAV = Current Assets - Total Liabilities - Preferred Stock Value
NCAV per Share = NCAV / Shares Outstanding
```

**Graham's Rule:** Buy at no more than **2/3 of NCAV** (33%+ margin of safety)

### Strict NCAV (with off-balance sheet items)
```
NCAV = Current Assets - Total Liabilities - Preferred Stock - Off Balance Sheet Items
```
Off-balance sheet items: pension obligations, operating leases, contingent liabilities

### Net-Net Working Capital (NNWC) — Most Conservative
```
NNWC = Cash & Short-Term Investments 
     + (75% × Accounts Receivable) 
     + (50% × Inventory) 
     - Total Liabilities 
     - Preferred Stock 
     - Off Balance Sheet Items
```

**Discount rationale:**
- Accounts receivable: 25% discount (default risk, collection difficulty)
- Inventory: 50% discount (liquidation risk, obsolescence, forced sale)

**NNWC per Share = NNWC / Shares Outstanding**

### Graham's Additional NCAV Rules:
1. **Positive EPS (TTM):** Exclude companies with net losses in last 12 months
2. **Diversification:** Minimum 30 stocks, max 3.3% allocation per NCAV stock
3. **Earnings filter:** NCAV alone is not enough — must have positive earnings

---

## 2. Graham Number

```
Graham Number = sqrt(22.5 × EPS × Book Value Per Share)
```
Where 22.5 = 15 (max P/E) × 1.5 (max P/B)

Only applicable when EPS > 0 and BVPS > 0.

---

## 3. Graham Growth Formula

```
Intrinsic Value = EPS × (8.5 + 2g) × 4.4 / Y
```
Where:
- `8.5` = P/E for a zero-growth company
- `g` = expected annual growth rate (%)
- `4.4` = AAA bond yield (1962 reference)
- `Y` = current AAA bond yield

---

## 4. Discounted Cash Flow (DCF)

### Standard DCF Model
```
Intrinsic Value = Σ (FCF_t / (1 + r)^t) + TV / (1 + r)^n
```

**Terminal Value (Gordon Growth):**
```
TV = FCF_n × (1 + g) / (r - g)
```

**Conservative Burry assumptions:**
- Discount rate (r): 10%
- Growth rate (g): 4% (years 1-5)
- Terminal growth: 2%

**Margin of Safety:**
```
MOS = (Intrinsic Value - Current Price) / Intrinsic Value
```
Burry requires 30-40% MOS.

---

## 5. Free Cash Flow Yield

```
FCF Yield = Free Cash Flow / Market Cap
```
Where: `FCF = Operating Cash Flow - Capital Expenditures`

**Burry thresholds:**
- > 8%: Exceptional cash generator (strong buy signal)
- 5-8%: Adequate cash generator
- < 5%: Market may be overvaluing the business

---

## 6. Enterprise Value / EBITDA

```
EV = Market Cap + Total Debt + Preferred Stock + Minority Interest - Cash & Equivalents
EV/EBITDA = EV / EBITDA
```

**Advantages over P/E:**
- Capital-structure neutral
- Removes depreciation/amortization differences
- Better for comparing companies with different leverage

**Burry use:** Compares EV/EBITDA to historical sector median; look for companies trading at a discount

---

## 7. Key Balance Sheet Metrics

| Metric | Formula | Burry Target | Purpose |
|--------|---------|---------------|---------|
| Current Ratio | Current Assets / Current Liabilities | > 2.0 (min 1.5) | Short-term liquidity |
| Quick Ratio | (Current Assets - Inventory) / Current Liabilities | > 1.0 | Liquidation safety |
| Debt/Equity | Total Debt / Shareholders Equity | < 0.50 (max 1.0) | Solvency risk |
| Interest Coverage | EBIT / Interest Expense | > 5x | Debt serviceability |
| Net Debt / EBITDA | (Total Debt - Cash) / EBITDA | < 2.0x | Leverage normalization |
| ROE | Net Income / Shareholders Equity | 12-25% | Sustainable profitability |
| ROIC | NOPAT / Invested Capital | 12-25% | Capital allocation efficiency |

---

## 8. Return on Capital (ROC) Warning

Burry warns against companies with **ROC > 25%**:
- Super-normal profits attract competition
- Competitors enter the market and destroy margins
- High ROC is rarely sustainable long-term
- Ideal range: 12-25% (enough profit without attracting excessive competition)

---

## 9. Earnings Power Value (EPV)

```
EPV = Adjusted Earnings / Cost of Capital
```

Bruce Greenwald's method: values a company's current earnings with zero growth. If EPV > Market Cap, the stock is undervalued even without growth assumptions.

---

## 10. Sum of the Parts (SOTP)

```
SOTP = (Segment1 EV + Segment2 EV + ... + Non-operating Assets) - Corporate Overhead
```

Used when a company has multiple business units trading at different implied multiples. Compare SOTP to Market Cap for conglomerate discount.

---

## Calculation Sources
- Yahoo Finance: `info`, `financials`, `balance_sheet`, `cashflow`
- SEC EDGAR: 10-K and 10-Q filings for footnotes
- Macrotrends: Historical metric trends

## Related Notes
- Michael Burry Methodology
- Contrarian Trading Framework
- Financial Research Database
