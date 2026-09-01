import json
import os
import datetime
import yfinance as yf
from ta_lib import compute_rsi, compute_atr, compute_sma

STATE_ROOT = os.environ.get("STOCK_ANALYSIS_STATE_ROOT", os.path.dirname(__file__))
PORTFOLIO_FILE = os.path.join(STATE_ROOT, "portfolio.json")

class ScionPortfolioManager:
    """
    Michael Burry-esque swing trading portfolio manager.
    Enforces the Scion ruleset:
      - 12 to 18 max concurrent positions
      - Max 5-8% allocation per position
      - Hard stop-loss on 52-week low break
      - Active profit-taking at +20% (scale 50%) and +40% (liquidate rest)
      - Thesis-break loss cap: hard exit at -6% (decision 2026-08-05)
    """

    def __init__(self, capital=100000.0, portfolio_file=PORTFOLIO_FILE):
        self.capital = capital
        self.cash = capital
        self.portfolio_file = portfolio_file
        self.positions = {}       # symbol -> position dict
        self.trade_log = []        # list of executed trades
        self.max_positions = 18
        self.min_positions = 12
        self.max_position_pct = 0.08   # 8% max per position
        self.min_position_pct = 0.03   # 3% minimum to open
        self.target_1_pct = 0.20       # +20% scale-out
        self.target_2_pct = 0.40       # +40% full liquidation
        self.max_drawdown_pct = 0.15   # 15% max portfolio drawdown at stops
        self.thesis_break_cap_pct = 0.06   # hard loss cap: close any position down >6% (thesis-break rule 2026-08-05)

        self.load_state()

    # ---- Persistence ----

    def load_state(self):
        if os.path.exists(self.portfolio_file):
            with open(self.portfolio_file, "r") as f:
                data = json.load(f)
            self.capital = data.get("capital", self.capital)
            self.cash = data.get("cash", self.cash)
            self.positions = data.get("positions", {})
            self.trade_log = data.get("trade_log", [])
            self.max_position_pct = data.get("max_position_pct", self.max_position_pct)
            self.target_1_pct = data.get("target_1_pct", self.target_1_pct)
            self.target_2_pct = data.get("target_2_pct", self.target_2_pct)
            self.max_drawdown_pct = data.get("max_drawdown_pct", self.max_drawdown_pct)
            self.thesis_break_cap_pct = data.get("thesis_break_cap_pct", self.thesis_break_cap_pct)

    def save_state(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.portfolio_file)), exist_ok=True)
        data = {
            "capital": self.capital,
            "cash": self.cash,
            "positions": self.positions,
            "trade_log": self.trade_log[-200:],  # keep last 200 trades
            "max_position_pct": self.max_position_pct,
            "target_1_pct": self.target_1_pct,
            "target_2_pct": self.target_2_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "thesis_break_cap_pct": self.thesis_break_cap_pct,
            "last_updated": datetime.datetime.now().isoformat()
        }
        with open(self.portfolio_file, "w") as f:
            json.dump(data, f, indent=2)

    # ---- Core Methods ----

    def get_current_price(self, symbol):
        try:
            t = yf.Ticker(symbol)
            hist = t.history(period="5d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception:
            pass
        return None

    def _portfolio_drawdown_at_stops(self, new_entry_price=None, new_stop_loss=None, new_position_pct=None):
        """Compute total portfolio % drawdown if every position hits its stop."""
        total_at_risk = 0.0
        for sym, pos in self.positions.items():
            cost = pos["cost_basis"]
            stop_val = pos["shares"] * pos["stop_loss"]
            total_at_risk += max(0, cost - stop_val)

        if new_entry_price and new_stop_loss and new_position_pct:
            new_cost = self.capital * new_position_pct
            new_shares = int(new_cost / new_entry_price)
            if new_shares > 0:
                actual_cost = new_shares * new_entry_price
                new_stop_val = new_shares * new_stop_loss
                total_at_risk += max(0, actual_cost - new_stop_val)

        drawdown_pct = total_at_risk / self.capital if self.capital > 0 else 0
        return drawdown_pct

    def open_position(self, symbol, entry_price, stop_loss, target_1, target_2,
                       score=0, reasons="", position_pct=None):
        """Open a new swing position following Burry rules."""
        if len(self.positions) >= self.max_positions:
            return {"action": "REJECTED", "reason": "Max positions reached (18)"}

        if symbol in self.positions:
            return {"action": "REJECTED", "reason": "Position already exists"}

        if position_pct is None:
            position_pct = self.max_position_pct

        dd = self._portfolio_drawdown_at_stops(entry_price, stop_loss, position_pct)
        if dd > self.max_drawdown_pct:
            return {"action": "REJECTED",
                    "reason": f"Portfolio drawdown at stops would be {dd*100:.1f}% (max {self.max_drawdown_pct*100:.0f}%)"}

        alloc_amount = self.capital * position_pct
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
            "stop_loss": stop_loss,
            "target_1": target_1,
            "target_2": target_2,
            "score": score,
            "reasons": reasons,
            "position_pct": position_pct,
            "opened_date": datetime.datetime.now().isoformat(),
            "status": "OPEN",
            "partial_exit_done": False
        }

        trade = {
            "symbol": symbol,
            "action": "BUY",
            "shares": shares,
            "price": entry_price,
            "cost": cost,
            "timestamp": datetime.datetime.now().isoformat(),
            "score": score,
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
            "stop_loss": stop_loss,
            "target_1": target_1,
            "target_2": target_2
        }

    def check_position(self, symbol):
        """
        Check an open position against current price.
        Enforce stop-loss and profit-target rules.
        Returns a list of action dicts (may be empty).
        """
        if symbol not in self.positions:
            return []

        pos = self.positions[symbol]
        current_price = self.get_current_price(symbol)
        if current_price is None:
            return []

        actions = []
        gain_pct = (current_price - pos["entry_price"]) / pos["entry_price"]

        # Fetch TA data for RSI/ATR overlay
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="6mo")
            if not hist.empty and len(hist) >= 20:
                ta_rsi = compute_rsi(hist["Close"])
                ta_atr = compute_atr(hist)
                atr_val = ta_atr.get("value") or 0
                sma50 = compute_sma(hist["Close"], 50) or 0
            else:
                ta_rsi = {"value": 50, "regime": "neutral"}
                atr_val = 0
                sma50 = 0
        except Exception:
            ta_rsi = {"value": 50, "regime": "neutral"}
            atr_val = 0
            sma50 = 0

        # ATR-based dynamic stop tightening (never loosens, never moves above entry or current price)
        if atr_val > 0 and sma50 > 0:
            dynamic_stop = max(sma50 - 2 * atr_val, pos["entry_price"] - 3 * atr_val)
            # Clamp: stop must be below entry AND below current price (otherwise instant exit)
            dynamic_stop = min(dynamic_stop, pos["entry_price"] - 0.5 * atr_val, current_price - 0.5 * atr_val)
            if dynamic_stop > pos["stop_loss"]:
                pos["stop_loss"] = round(dynamic_stop, 2)

        # RSI overlay after Target 1: overbought = push to scale remaining
        if ta_rsi["value"] > 70 and pos.get("partial_exit_done"):
            actions.append({
                "action": "ADVISORY",
                "reason": f"RSI overbought ({ta_rsi['value']:.1f}) after partial exit — consider scaling rest"
            })

        # RSI oversold near stop: flag for false-breakdown review
        threshold = pos["stop_loss"] * 1.03
        if ta_rsi["value"] < 30 and current_price <= threshold and current_price > pos["stop_loss"]:
            actions.append({
                "action": "FLAG",
                "reason": f"RSI oversold ({ta_rsi['value']:.1f}) near stop — verify false breakdown before closing"
            })

        # 1. STOP-LOSS: Price broke 52-week low support -> liquidate immediately
        if current_price <= pos["stop_loss"]:
            result = self.close_position(symbol, current_price, reason="STOP-LOSS (52W low broken)")
            actions.append(result)
            return actions

        # 1b. THESIS-BREAK CAP: hard loss cap (decision 2026-08-05).
        #     Stops stay as-is; any position down past the cap exits regardless of stop width.
        if gain_pct <= -self.thesis_break_cap_pct:
            result = self.close_position(
                symbol, current_price,
                reason=f"THESIS-BREAK CAP ({self.thesis_break_cap_pct*100:.0f}% hard exit rule)"
            )
            actions.append(result)
            return actions

        # 2. TARGET 2: +40% gain -> liquidate remaining position
        if gain_pct >= self.target_2_pct:
            result = self.close_position(symbol, current_price, reason="TARGET 2 HIT (+40% full liquidation)")
            actions.append(result)
            return actions

        # 3. TARGET 1: +20% gain -> scale out 50% of shares
        if gain_pct >= self.target_1_pct and not pos["partial_exit_done"]:
            result = self.scale_out(symbol, current_price, pct_to_sell=0.50, reason="TARGET 1 HIT (+20% scale-out)")
            actions.append(result)

        return actions

    def scale_out(self, symbol, price, pct_to_sell=0.50, reason=""):
        """Sell a portion of a position at a target."""
        pos = self.positions[symbol]
        shares_to_sell = int(pos["shares"] * pct_to_sell)
        if shares_to_sell <= 0:
            return {"action": "SKIP", "reason": "No shares to scale"}

        proceeds = shares_to_sell * price
        cost_basis_sold = pos["cost_basis"] * shares_to_sell / pos["shares"]
        realized_pnl = proceeds - cost_basis_sold
        pos["cost_basis"] -= cost_basis_sold
        pos["shares"] -= shares_to_sell
        pos["partial_exit_done"] = True
        self.cash += proceeds

        trade = {
            "symbol": symbol,
            "action": "SCALE_OUT",
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
            "action": "SCALED_OUT",
            "symbol": symbol,
            "shares_sold": shares_to_sell,
            "shares_remaining": pos["shares"],
            "price": price,
            "proceeds": round(proceeds, 2),
            "cost_basis": round(cost_basis_sold, 2),
            "realized_pnl": round(realized_pnl, 2),
            "reason": reason
        }

    def close_position(self, symbol, price, reason=""):
        """Fully liquidate a position."""
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

    def check_all_positions(self):
        """Run stop-loss and target checks on all open positions."""
        all_actions = []
        for symbol in list(self.positions.keys()):
            actions = self.check_position(symbol)
            all_actions.extend(actions)
        return all_actions

    def get_portfolio_summary(self):
        """Return a snapshot of the portfolio state."""
        total_value = self.cash
        lines = []
        lines.append("=" * 60)
        lines.append("           SCION PORTFOLIO SUMMARY")
        lines.append("=" * 60)
        lines.append(f"Total Capital:      ${self.capital:>12,.2f}")
        lines.append(f"Cash Available:     ${self.cash:>12,.2f}")
        lines.append(f"Positions Open:     {len(self.positions)}/{self.max_positions}")
        lines.append("-" * 60)

        if not self.positions:
            lines.append("  (No open positions)")
        else:
            lines.append(f"{'Symbol':<8} {'Shares':>8} {'Entry':>10} {'Current':>10} {'P&L%':>8} {'Status':>12}")
            lines.append("-" * 60)
            for symbol, pos in self.positions.items():
                cp = self.get_current_price(symbol)
                if cp:
                    pnl_pct = (cp - pos["entry_price"]) / pos["entry_price"] * 100
                    status = "PARTIAL" if pos["partial_exit_done"] else "FULL"
                    lines.append(f"{symbol:<8} {pos['shares']:>8} {pos['entry_price']:>10.2f} {cp:>10.2f} {pnl_pct:>7.1f}% {status:>12}")
                    total_value += pos["shares"] * cp
                else:
                    lines.append(f"{symbol:<8} {pos['shares']:>8} {pos['entry_price']:>10.2f} {'N/A':>10} {'N/A':>8} {'ERROR':>12}")
                    total_value += pos["shares"] * pos["entry_price"]

            lines.append("-" * 60)
            lines.append(f"Total Portfolio Value: ${total_value:>12,.2f}")
            if self.capital > 0:
                lines.append(f"Total Return:          ${total_value - self.capital:>12,.2f} ({(total_value/self.capital - 1)*100:.1f}%)")
            else:
                lines.append(f"Total Cost Basis:      ${total_value:>12,.2f} (capital not set)")

        lines.append("=" * 60)
        return "\n".join(lines)


if __name__ == "__main__":
    print("Use main.py or import ScionPortfolioManager directly.")
