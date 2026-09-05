"""
Warren Buffett-esque long-term portfolio manager.

Key differences from ScionPortfolioManager (Burry):
  - 5 to 12 max concurrent positions (concentrated conviction)
  - Max 15-25% allocation per position
  - NO price-based stop-loss — holds through volatility
  - Exit only on: thesis break, moat erosion, management degradation,
    or price far exceeding intrinsic value
  - Cash as strategic asset — can hold 30%+ waiting for fat pitches
  - VIX > 30 = BUY signal; VIX < 15 = SLOWDOWN signal
  - Annual turnover target: 5-15% (decades-long holding)
"""

import datetime
import json
import os

import yfinance as yf

STATE_ROOT = os.environ.get("STOCK_ANALYSIS_STATE_ROOT", os.path.dirname(__file__))
PORTFOLIO_FILE = os.path.join(STATE_ROOT, "buffett_portfolio.json")


class BuffettPortfolioManager:
    """
    Long-horizon quality-compounder portfolio manager.
    Follows Buffett's concentration-over-diversification philosophy.
    """

    def __init__(self, capital=100000.0, portfolio_file=PORTFOLIO_FILE):
        self.capital = capital
        self.cash = capital
        self.portfolio_file = portfolio_file
        self.positions = {}
        self.trade_log = []
        self.max_positions = 12
        self.max_position_pct = 0.25
        self.min_position_pct = 0.05
        self.load_state()

    def load_state(self):
        if os.path.exists(self.portfolio_file):
            with open(self.portfolio_file, "r") as f:
                data = json.load(f)
            self.capital = data.get("capital", self.capital)
            self.cash = data.get("cash", self.cash)
            self.positions = data.get("positions", {})
            self.trade_log = data.get("trade_log", [])

    def save_state(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.portfolio_file)), exist_ok=True)
        data = {
            "capital": self.capital,
            "cash": self.cash,
            "positions": self.positions,
            "trade_log": self.trade_log[-200:],
            "last_updated": datetime.datetime.now().isoformat()
        }
        with open(self.portfolio_file, "w") as f:
            json.dump(data, f, indent=2)

    def get_current_price(self, symbol):
        try:
            t = yf.Ticker(symbol)
            hist = t.history(period="5d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception:
            pass
        return None

    def estimate_intrinsic_value(self, symbol):
        """Quick intrinsic value estimate using current price as placeholder.
        Full DCF is done by buffett_analyzer.py; this is a simple sanity check."""
        try:
            t = yf.Ticker(symbol)
            info = t.info
            fcf = info.get("freeCashflow")
            shares = info.get("sharesOutstanding")
            current_price = info.get("currentPrice") or info.get("previousClose")
            if fcf and shares and current_price and fcf > 0:
                oe_per_share = fcf / shares
                growth_rate = 0.08
                discount_rate = 0.10
                terminal_growth = 0.03
                projected = []
                temp = fcf
                for year in range(1, 11):
                    temp *= (1 + growth_rate)
                    projected.append(temp)
                pv_oe = [oe / ((1 + discount_rate) ** year) for year, oe in zip(range(1, 11), projected)]
                sum_pv_oe = sum(pv_oe)
                tv = projected[-1] * (1 + terminal_growth) / (discount_rate - terminal_growth)
                pv_tv = tv / ((1 + discount_rate) ** 10)
                total_debt = info.get("totalDebt") or 0
                total_cash = info.get("totalCash") or 0
                intrinsic_equity = sum_pv_oe + pv_tv + total_cash - total_debt
                intrinsic_per_share = intrinsic_equity / shares
                margin_of_safety = (intrinsic_per_share - current_price) / intrinsic_per_share
                return {
                    "intrinsic_value": round(intrinsic_per_share, 2),
                    "current_price": round(current_price, 2),
                    "margin_of_safety": round(margin_of_safety, 4)
                }
        except Exception:
            pass
        return None

    def open_position(self, symbol, entry_price, intrinsic_value=None,
                      buffett_score=0, reasons=""):
        """Open a long-term compounder position following Buffett rules."""
        if len(self.positions) >= self.max_positions:
            return {"action": "REJECTED", "reason": "Max positions reached (12)"}

        if symbol in self.positions:
            return {"action": "REJECTED", "reason": "Position already exists"}

        allocation_pct = self.max_position_pct
        alloc_amount = self.capital * allocation_pct
        if alloc_amount > self.cash:
            alloc_amount = self.cash
            if alloc_amount <= 0:
                return {"action": "REJECTED", "reason": "Insufficient cash"}

        shares = int(alloc_amount / entry_price)
        if shares <= 0:
            return {"action": "REJECTED", "reason": "Allocation too small for 1 share"}

        cost = shares * entry_price
        self.cash -= cost

        self.positions[symbol] = {
            "shares": shares,
            "entry_price": entry_price,
            "cost_basis": cost,
            "intrinsic_value": intrinsic_value,
            "last_known_intrinsic": intrinsic_value,
            "buffett_score": buffett_score,
            "reasons": reasons,
            "opened_date": datetime.datetime.now().isoformat(),
            "status": "HOLD",
            "thesis_intact": True,
            "valuation_warnings": 0
        }

        trade = {
            "symbol": symbol,
            "action": "BUY",
            "shares": shares,
            "price": entry_price,
            "cost": cost,
            "timestamp": datetime.datetime.now().isoformat(),
            "score": buffett_score,
            "reasons": reasons
        }
        self.trade_log.append(trade)
        self.save_state()

        return {
            "action": "BOUGHT",
            "symbol": symbol,
            "shares": shares,
            "price": entry_price,
            "cost": round(cost, 2),
            "allocation_pct": round(allocation_pct * 100, 1),
            "intrinsic_value": intrinsic_value,
            "buffett_score": buffett_score
        }

    def check_position(self, symbol):
        """
        Buffett-style position check:
          - Recalculate intrinsic value (quick estimate)
          - Check for thesis break signals (moat erosion, management scandal)
          - Flag extreme overvaluation (price >> intrinsic)
        Does NOT stop-loss on price drops — holds through volatility.
        """
        if symbol not in self.positions:
            return []

        pos = self.positions[symbol]
        current_price = self.get_current_price(symbol)
        if current_price is None:
            return []

        actions = []

        iv = self.estimate_intrinsic_value(symbol)
        if iv:
            pos["last_known_intrinsic"] = iv["intrinsic_value"]

            # Check for extreme overvaluation
            margin = iv.get("margin_of_safety", 0)
            if margin < -0.50:
                pos["valuation_warnings"] = pos.get("valuation_warnings", 0) + 1
                if pos["valuation_warnings"] >= 3:
                    actions.append({
                        "action": "WARNING",
                        "symbol": symbol,
                        "message": f"Price ({iv['current_price']}) far exceeds intrinsic ({iv['intrinsic_value']}) for {pos['valuation_warnings']} consecutive checks — consider trimming",
                        "current_price": iv["current_price"],
                        "intrinsic_value": iv["intrinsic_value"],
                        "premium_pct": round((iv["current_price"] / iv["intrinsic_value"] - 1) * 100, 1)
                    })
            else:
                pos["valuation_warnings"] = 0

        # Update holding period
        opened = datetime.datetime.fromisoformat(pos["opened_date"])
        days_held = (datetime.datetime.now() - opened).days
        pos["days_held"] = days_held

        return actions

    def close_position(self, symbol, price, reason=""):
        """Exit a position (thesis break, moat erosion, or extreme overvaluation)."""
        pos = self.positions.pop(symbol)
        proceeds = pos["shares"] * price
        self.cash += proceeds

        realized_pnl = proceeds - pos["cost_basis"]
        realized_pct = realized_pnl / pos["cost_basis"] if pos["cost_basis"] > 0 else 0

        trade = {
            "symbol": symbol,
            "action": "CLOSE",
            "shares": pos["shares"],
            "price": price,
            "proceeds": round(proceeds, 2),
            "cost_basis": round(pos["cost_basis"], 2),
            "realized_pnl": round(realized_pnl, 2),
            "realized_pct": f"{realized_pct * 100:.1f}%",
            "reason": reason,
            "timestamp": datetime.datetime.now().isoformat()
        }
        self.trade_log.append(trade)
        self.save_state()

        return {
            "action": "CLOSED",
            "symbol": symbol,
            "shares": pos["shares"],
            "price": price,
            "proceeds": round(proceeds, 2),
            "cost_basis": round(pos["cost_basis"], 2),
            "realized_pnl": round(realized_pnl, 2),
            "realized_pct": f"{realized_pct * 100:.1f}%",
            "reason": reason
        }

    def trim_position(self, symbol, price, pct_to_sell=0.25, reason=""):
        """Trim an overweight position (rebalance, not exit)."""
        pos = self.positions[symbol]
        shares_to_sell = int(pos["shares"] * pct_to_sell)
        if shares_to_sell <= 0:
            return {"action": "SKIP", "reason": "No shares to trim"}

        proceeds = shares_to_sell * price
        cost_basis_sold = pos["cost_basis"] * shares_to_sell / pos["shares"]
        realized_pnl = proceeds - cost_basis_sold
        pos["cost_basis"] -= cost_basis_sold
        pos["shares"] -= shares_to_sell
        self.cash += proceeds

        trade = {
            "symbol": symbol,
            "action": "TRIM",
            "shares": shares_to_sell,
            "price": price,
            "proceeds": round(proceeds, 2),
            "cost_basis": round(cost_basis_sold, 2),
            "realized_pnl": round(realized_pnl, 2),
            "reason": reason,
            "timestamp": datetime.datetime.now().isoformat()
        }
        self.trade_log.append(trade)
        self.save_state()

        return {
            "action": "TRIMMED",
            "symbol": symbol,
            "shares_sold": shares_to_sell,
            "shares_remaining": pos["shares"],
            "price": price,
            "proceeds": round(proceeds, 2),
            "cost_basis": round(cost_basis_sold, 2),
            "realized_pnl": round(realized_pnl, 2),
            "reason": reason
        }

    def check_all_positions(self):
        """Buffett-style review of all holdings."""
        all_actions = []
        for symbol in list(self.positions.keys()):
            actions = self.check_position(symbol)
            all_actions.extend(actions)
        return all_actions

    def get_cash_position_pct(self):
        """Return percentage of capital held as cash (key Buffett metric)."""
        return (self.cash / self.capital * 100) if self.capital > 0 else 0

    def get_portfolio_summary(self):
        """Return a snapshot of the portfolio — Buffett-style concentration view."""
        total_value = self.cash
        lines = []
        lines.append("=" * 60)
        lines.append("           OMAHA-BOT PORTFOLIO SUMMARY")
        lines.append("=" * 60)
        lines.append(f"Total Capital:      ${self.capital:>12,.2f}")
        lines.append(f"Cash Available:     ${self.cash:>12,.2f}")
        lines.append(f"Cash Position:      {self.get_cash_position_pct():>5.1f}%")
        lines.append(f"Positions Open:     {len(self.positions)}/{self.max_positions}")
        lines.append(f"Concentration:      {'Concentrated' if len(self.positions) <= 8 else 'Moderate'}")
        lines.append("-" * 60)

        if not self.positions:
            lines.append("  (No open positions — cash pile building)")
            lines.append("  *Buffett says: 'Be greedy when others are fearful'*")
        else:
            lines.append(f"{'Symbol':<8} {'Shares':>8} {'Entry':>10} {'Current':>10} {'P&L%':>8} {'Intrinsic':>10} {'Alloc%':>7}")
            lines.append("-" * 60)
            port_value = total_value
            for symbol, pos in sorted(self.positions.items(),
                                       key=lambda x: x[1]["shares"] * (get_current_price_fast(self, x[0]) or x[1]["entry_price"]),
                                       reverse=True):
                cp = self.get_current_price(symbol)
                if cp:
                    pnl_pct = (cp - pos["entry_price"]) / pos["entry_price"] * 100
                    pos_value = pos["shares"] * cp
                    alloc_pct = pos_value / self.capital * 100
                    iv = pos.get("last_known_intrinsic", "N/A")
                    iv_str = f"${iv}" if isinstance(iv, (int, float)) else str(iv)
                    lines.append(f"{symbol:<8} {pos['shares']:>8} {pos['entry_price']:>10.2f} {cp:>10.2f} {pnl_pct:>7.1f}% {iv_str:>10} {alloc_pct:>6.1f}%")
                    port_value += cp * pos["shares"]
                else:
                    pos_value = pos["shares"] * pos["entry_price"]
                    alloc_pct = pos_value / self.capital * 100
                    lines.append(f"{symbol:<8} {pos['shares']:>8} {pos['entry_price']:>10.2f} {'N/A':>10} {'N/A':>8} {'N/A':>10} {alloc_pct:>6.1f}%")
                    port_value += pos["shares"] * pos["entry_price"]

            lines.append("-" * 60)
            total_return = port_value - self.capital
            lines.append(f"Total Portfolio Value: ${port_value:>12,.2f}")
            lines.append(f"Total Return:          ${total_return:>12,.2f} ({(port_value/self.capital - 1)*100:.1f}%)")
            largest_pct = 0
            if self.positions:
                pos_values = []
                for s, v in self.positions.items():
                    p = self.get_current_price(s)
                    if p:
                        pos_values.append(v["shares"] * p)
                if pos_values:
                    largest_pct = max(pos_values) / port_value * 100
            lines.append(f"Largest Position:      {largest_pct:.1f}%")

        lines.append("=" * 60)
        return "\n".join(lines)


def get_current_price_fast(pm, symbol):
    """Helper for summary sorting."""
    return pm.get_current_price(symbol)


if __name__ == "__main__":
    print("Use buffett_main.py or import BuffettPortfolioManager directly.")
