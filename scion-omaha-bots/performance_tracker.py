"""
Performance Tracker

Logs every screener run, portfolio action, and full cycle result to a
time-series CSV so you can backtest whether the signals actually predicted moves.

Files created:
  performance_log.csv       — all events (screener results, actions, cycle summaries)
  performance_portfolio.csv — periodic portfolio snapshots at each cycle
"""
import csv
import datetime
import json
import os


PERF_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "performance_log.csv")
PORTFOLIO_SNAPSHOT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "performance_portfolio.csv"
)

_HEADERS = [
    "timestamp", "agent", "event_type", "symbol", "score",
    "price", "action", "reason", "extra_json",
]
_PORTFOLIO_HEADERS = [
    "timestamp", "agent", "symbol", "shares", "cost_basis",
    "current_price", "unrealized_pnl_pct", "position_pct",
]


def _ensure_file(path, headers):
    if not os.path.exists(path):
        try:
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(headers)
        except Exception:
            pass


def _append(path, headers, row):
    _ensure_file(path, headers)
    try:
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            w.writerow(row)
    except Exception as e:
        print(f"  (Could not write performance log: {e})")


def log_screener_result(agent, symbol, score, price, extra=None):
    row = [
        datetime.datetime.now().isoformat(),
        agent, "screener_result", symbol, score,
        price, "", "",
        json.dumps(extra) if extra else "",
    ]
    _append(PERF_FILE, _HEADERS, row)


def log_portfolio_action(agent, symbol, action, price, reason, score=None, extra=None):
    row = [
        datetime.datetime.now().isoformat(),
        agent, "portfolio_" + action, symbol, score or "",
        price, action, reason,
        json.dumps(extra) if extra else "",
    ]
    _append(PERF_FILE, _HEADERS, row)


def log_run_cycle(agent, top_symbol, top_score, pick_count, extra=None):
    row = [
        datetime.datetime.now().isoformat(),
        agent, "run_cycle", top_symbol, top_score,
        pick_count, "", "",
        json.dumps(extra) if extra else "",
    ]
    _append(PERF_FILE, _HEADERS, row)


def snapshot_portfolio(agent, positions):
    """positions: list of dicts with symbol, shares, cost_basis, current_price, pct_of_portfolio."""
    for p in positions:
        row = [
            datetime.datetime.now().isoformat(),
            agent,
            p.get("symbol", ""),
            p.get("shares", 0),
            p.get("cost_basis", 0),
            p.get("current_price", 0),
            p.get("unrealized_pnl_pct", 0),
            p.get("position_pct", 0),
        ]
        _append(PORTFOLIO_SNAPSHOT_FILE, _PORTFOLIO_HEADERS, row)
