"""
Strategy Adjustment Recommendation Engine

Reads report_card.py metrics and applies a rule engine to produce
actionable strategy tweaks. Each rule checks for statistical significance
(minimum trade count) before firing. Interactive CLI prompts for approval.

Rules implemented:
  - STOP_WIDTH:   Avg stop distance on winners > 12% over 15+ trades → tighten stops on next entries
  - TARGET_LOWER: T1 hit rate < 25% over 10+ trades → lower T1 to +15%
  - POSITION_CAP: Scion win rate < 40% in credit stress → cap at 3%
  - REGIME_PAUSE: VIX > 25 AND last 5 trades < 30% win → pause entries
  - SECTOR_AVOID: Any sector with 3+ losses, 0 wins → flag to avoid
  - OMAHA_PULLBACK: Omaha picks consistently > DCF value → raise pullback threshold
  - THESIS_CAP:    Any closed trade below -6% → flag thesis-break discipline breach

Excluded rules (per user request):
  - SCORE_FLOOR: NOT applied
"""
import datetime
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from credit_monitor import CreditMonitor
from report_card import compute_metrics
from tracker import Tracker

VAULT_DIR = os.path.join(os.path.expanduser("~"),
    "OneDrive", "Documents", "Obsidian Vault",
    "Stock Research", "Performance")


def _ensure_vault_dir():
    os.makedirs(VAULT_DIR, exist_ok=True)
    return VAULT_DIR


def _get_vix():
    try:
        import yfinance as yf
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="5d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


class FeedbackEngine:
    def __init__(self, tracker=None):
        self.tracker = tracker or Tracker()
        self.metrics = compute_metrics(self.tracker)
        self.open_positions = self.tracker.get_open_positions_summary()
        self.vix = _get_vix()
        self.credit_score = self._get_credit_score()
        self.recommendations = []
        self.rules_metadata = {
            "TARGET_LOWER": {"name": "Lower Target 1 to +15%", "applied": False},
            "STOP_WIDTH": {"name": "Tighten Stops on Next Entries", "applied": False},
            "POSITION_CAP": {"name": "Cap Scion Positions at 3%", "applied": False},
            "REGIME_PAUSE": {"name": "Pause New Scion Entries", "applied": False},
            "SECTOR_AVOID": {"name": "Flag Sector to Avoid", "applied": False},
            "OMAHA_PULLBACK": {"name": "Raise Omaha Pullback Threshold", "applied": False},
            "THESIS_CAP": {"name": "Review Thesis-Break Loss Cap Breaches", "applied": False},
        }

    def _get_credit_score(self):
        try:
            _, cs, _, _ = CreditMonitor().quick_pulse()
            return cs
        except Exception:
            return None

    def check_target_lower(self):
        """TARGET_LOWER: If T1 hit rate < 25% over 10+ trades, recommend lowering T1 to +15%."""
        closed = self.metrics.get("closed_trades", [])
        if len(closed) < 10:
            return

        t1_hits = [r for r in closed if r.get("exit_reason") in ("target1", "target2")]
        hit_rate = len(t1_hits) / len(closed) * 100

        if hit_rate < 25:
            self.recommendations.append({
                "rule": "TARGET_LOWER",
                "evidence": f"Only {len(t1_hits)} of {len(closed)} trades hit T1/T2 ({hit_rate:.0f}% hit rate). "
                           f"Target: Lower T1 from +20% to +15% to increase probability of partial exits.",
                "action_fn": self._apply_target_lower,
            })

    def check_stop_width(self):
        """STOP_WIDTH: If avg stop distance on winners > 12% over 15+ trades, tighten stops."""
        closed = self.metrics.get("closed_trades", [])
        if len(closed) < 15:
            return

        # ponytail: stop distance = (entry - stop) / entry, from the CSV's stop_loss column
        stops = []
        for r in closed:
            if float(r.get("pnl_pct", 0)) > 0 and r.get("stop_loss"):
                entry = float(r.get("entry_price", 0))
                stop = float(r.get("stop_loss"))
                if entry > 0 and 0 < stop < entry:
                    stops.append((entry - stop) / entry * 100)

        if not stops:
            return

        avg_stop_dist = sum(stops) / len(stops)
        if avg_stop_dist > 12.0:
            self.recommendations.append({
                "rule": "STOP_WIDTH",
                "evidence": f"Avg stop distance on {len(stops)} winning trades is {avg_stop_dist:.1f}% (> 12%). "
                           f"Recommendation: Tighten stops on next entries (ATR multiplier 3x → 2x) to cut wider risk.",
                "action_fn": self._apply_stop_width,
            })

    def check_position_cap(self):
        """POSITION_CAP: If Scion win rate < 40% in credit-stress regime, cap at 3%."""
        scion_closed = self.tracker.get_closed_trades(bot="scion")
        if len(scion_closed) < 10:
            return

        scion_metrics = compute_metrics(self.tracker, bot="scion")
        win_rate = scion_metrics.get("win_rate", 100)
        in_credit_stress = self.credit_score is not None and self.credit_score >= 30

        if in_credit_stress and win_rate < 40:
            self.recommendations.append({
                "rule": "POSITION_CAP",
                "evidence": f"Scion win rate is {win_rate}% with Credit Stress at {self.credit_score:.0f}/100. "
                           f"Recommendation: Cap Scion position size from 5% to 3% max until credit stress drops below 30.",
                "action_fn": self._apply_position_cap,
            })

    def check_regime_pause(self):
        """REGIME_PAUSE: If VIX > 25 AND last 5 trades < 30% win, pause new entries."""
        if self.vix is None or self.vix <= 25:
            return

        closed = self.metrics.get("closed_trades", [])
        recent = sorted(closed, key=lambda x: x.get("exit_date", ""), reverse=True)[:5]
        if len(recent) < 5:
            return

        recent_wins = [r for r in recent if float(r.get("pnl_pct", 0)) > 0]
        recent_win_rate = len(recent_wins) / len(recent) * 100

        if recent_win_rate < 30:
            self.recommendations.append({
                "rule": "REGIME_PAUSE",
                "evidence": f"VIX is {self.vix:.1f} (>25) and last 5 trades have {recent_win_rate:.0f}% win rate. "
                           f"Recommendation: Pause new Scion entries until VIX drops below 20 or win rate recovers above 40%.",
                "action_fn": self._apply_regime_pause,
            })

    def check_sector_avoid(self):
        """SECTOR_AVOID: Flag any sector with 3+ losses and 0 wins."""
        sector_perf = self.metrics.get("sector_perf", {})
        for sector, data in sector_perf.items():
            losses = data["trades"] - data["wins"]
            if losses >= 3 and data["wins"] == 0 and data["trades"] >= 3:
                self.recommendations.append({
                    "rule": "SECTOR_AVOID",
                    "evidence": f"Sector '{sector}': {losses} losses, 0 wins in {data['trades']} trades. "
                               f"Recommendation: Flag '{sector}' as AVOID until a winning trade closes.",
                    "action_fn": lambda s=sector: self._apply_sector_avoid(s),
                })

    def check_omaha_pullback(self):
        """OMAHA_PULLBACK: If Omaha picks consistently trade above DCF, recommend waiting for larger pullback."""
        omaha_closed = self.tracker.get_closed_trades(bot="omaha")
        if len(omaha_closed) < 5:
            return

        omaha_wins = [r for r in omaha_closed if float(r.get("pnl_pct", 0)) > 0]
        omaha_losses = [r for r in omaha_closed if float(r.get("pnl_pct", 0)) <= 0]

        if len(omaha_losses) >= len(omaha_wins):
            self.recommendations.append({
                "rule": "OMAHA_PULLBACK",
                "evidence": f"Omaha-Bot has {len(omaha_wins)} wins vs {len(omaha_losses)} losses. "
                           f"Recommendation: Increase Omaha pullback requirement from -10% to -15% below DCF value before entry.",
                "action_fn": self._apply_omaha_pullback,
            })

    def _apply_target_lower(self):
        from portfolio import ScionPortfolioManager
        pm = ScionPortfolioManager()
        old, pm.target_1_pct = pm.target_1_pct, 0.15
        pm.save_state()
        self.rules_metadata["TARGET_LOWER"]["applied"] = True
        print(f"  [feedback] APPLIED TARGET_LOWER: T1 changed from +{old*100:.0f}% to +15%")

    def _apply_stop_width(self):
        print("  [feedback] STOP_WIDTH: Tighten stops — update ATR multiplier in portfolio logic (3x → 2x)")
        self.rules_metadata["STOP_WIDTH"]["applied"] = True

    def _apply_position_cap(self):
        from portfolio import ScionPortfolioManager
        pm = ScionPortfolioManager()
        old = pm.max_position_pct
        pm.max_position_pct = 0.03
        pm.save_state()
        self.rules_metadata["POSITION_CAP"]["applied"] = True
        print(f"  [feedback] APPLIED POSITION_CAP: Max position from {old*100:.0f}% to 3%")

    def _apply_regime_pause(self):
        print("  [feedback] REGIME_PAUSE: Scion entries paused. Set `scion_paused = True` in state.")
        self.rules_metadata["REGIME_PAUSE"]["applied"] = True

    def _apply_sector_avoid(self, sector):
        print(f"  [feedback] SECTOR_AVOID: Flagging '{sector}' as AVOID.")
        self.rules_metadata["SECTOR_AVOID"]["applied"] = True

    def _apply_omaha_pullback(self):
        print("  [feedback] OMAHA_PULLBACK: Raise pullback threshold — update buffett_portfolio config.")
        self.rules_metadata["OMAHA_PULLBACK"]["applied"] = True

    def check_thesis_cap(self):
        """THESIS_CAP: Flag any closed trade that breached the -6% hard loss cap (rule 2026-08-05)."""
        closed = self.metrics.get("closed_trades", [])
        breached = [r for r in closed if float(r.get("pnl_pct", 0)) < -6.0]
        if not breached:
            return

        names = ", ".join(f"{r.get('ticker', '?')} ({r.get('pnl_pct', 0)}%)" for r in breached)
        self.recommendations.append({
            "rule": "THESIS_CAP",
            "evidence": f"Loss cap breached: {names}. Hard rule (2026-08-05): close at -5% to -6% "
                       f"on thesis break — do not hold beyond -6%. Gap-downs may exceed the cap; "
                       f"flag for thesis review and consider tighter sizing if repeated.",
            "action_fn": self._apply_thesis_cap,
        })

    def _apply_thesis_cap(self):
        print("  [feedback] THESIS_CAP: Review flagged trades for thesis-break discipline (close at -5% to -6%).")
        self.rules_metadata["THESIS_CAP"]["applied"] = True

    def run_all_checks(self):
        self.check_target_lower()
        self.check_stop_width()
        self.check_position_cap()
        self.check_regime_pause()
        self.check_sector_avoid()
        self.check_omaha_pullback()
        self.check_thesis_cap()
        return self.recommendations

    def generate_report_markdown(self):
        lines = []
        lines.append("---")
        lines.append(f'title: "Strategy Feedback — {datetime.datetime.now().strftime("%Y-%m-%d")}"')
        lines.append(f'date: {datetime.datetime.now().strftime("%Y-%m-%d")}')
        lines.append("tags:")
        lines.append("  - feedback")
        lines.append("  - strategy")
        lines.append("---")
        lines.append("")
        lines.append(f"# Strategy Feedback — {datetime.datetime.now().strftime('%Y-%m-%d')}")
        lines.append("")

        if not self.recommendations:
            lines.append("No adjustments recommended at this time. All checks passed.")
            report = "\n".join(lines)
            filepath = os.path.join(_ensure_vault_dir(), f'{datetime.datetime.now().strftime("%Y-%m-%d")} Feedback.md')
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(report)
            return report

        lines.append("## Context")
        lines.append("| Metric | Value |")
        lines.append("| :--- | :--- |")
        lines.append(f"| **VIX** | {self.vix or 'N/A'} |")
        lines.append(f"| **Credit Stress** | {self.credit_score or 'N/A'}/100 |")
        lines.append(f"| **Total Closed Trades** | {self.metrics['total_closed']} |")
        lines.append(f"| **Current Win Rate** | {self.metrics['win_rate'] or 'N/A'}% |")
        lines.append(f"| **Open Positions** | {self.metrics['total_open']} |")
        lines.append("")

        lines.append("## Recommendations")
        lines.append("")
        for rec in self.recommendations:
            lines.append(f"### [{rec['rule']}] {self.rules_metadata[rec['rule']]['name']}")
            lines.append("")
            lines.append(f"**Evidence:** {rec['evidence']}")
            lines.append(f"**Status:** {'✅ Applied' if self.rules_metadata[rec['rule']]['applied'] else '⏳ Pending review'}")
            lines.append("")

        lines.append("---")
        lines.append(f"*Feedback generated at {datetime.datetime.now().strftime('%H:%M')}.*")

        report = "\n".join(lines)
        filepath = os.path.join(_ensure_vault_dir(), f'{datetime.datetime.now().strftime("%Y-%m-%d")} Feedback.md')
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report)

        return report

    def interactive_apply(self):
        if not self.recommendations:
            print("\n  No adjustments recommended.")
            return

        for rec in self.recommendations:
            rule = rec["rule"]
            meta = self.rules_metadata[rule]

            print(f"\n  === [{rule}] {meta['name']} ===")
            print(f"  Evidence: {rec['evidence']}")

            if meta["applied"]:
                print("  Status: Already applied. Skipping.")
                continue

            try:
                response = input("  Apply? (y/n): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                response = "n"

            if response == "y":
                rec["action_fn"]()
                print("  ✅ Applied.\n")
            else:
                print("  ⏳ Skipped.\n")


def cmd_feedback(interactive=True):
    tracker = Tracker()
    engine = FeedbackEngine(tracker=tracker)
    engine.run_all_checks()
    report = engine.generate_report_markdown()
    print(report)

    if interactive:
        engine.interactive_apply()
        for rule, meta in engine.rules_metadata.items():
            if meta["applied"]:
                print(f"  [{rule}] {meta['name']}: ✅ APPLIED")
    else:
        print("\n  Feedback report saved. Run with --apply to interactively apply.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Strategy Feedback Engine")
    parser.add_argument("--no-interactive", action="store_true", help="Generate report without prompts")
    args = parser.parse_args()
    cmd_feedback(interactive=not args.no_interactive)
