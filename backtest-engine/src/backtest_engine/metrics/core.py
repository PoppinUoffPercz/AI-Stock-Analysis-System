"""Core performance metrics. All inputs are returns/equity Series aligned to
a tz-aware UTC daily index.

We compute the canonical set the plan calls for: total return, CAGR, vol,
Sharpe, Sortino, Calmar, max-DD + duration, hit rate, profit factor, avg
win/loss, turnover, exposure. These serve both phase-1 vectorized results and
phase-2 event-driven results — and they're the inputs to the validation layer
and bias-audit panel.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ANNUALIZE_FACTOR = 252

MetricPanel = dict[str, float]


def total_return(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    return float(equity.iloc[-1] / equity.iloc[0] - 1.0)


def annualized_return(equity: pd.Series, periods_per_year: int = ANNUALIZE_FACTOR) -> float:
    if len(equity) < 2:
        return 0.0
    n_years = (equity.index[-1] - equity.index[0]).days / 365.25
    if n_years <= 0:
        return 0.0
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / n_years) - 1.0)


def annualized_vol(returns: pd.Series, periods_per_year: int = ANNUALIZE_FACTOR) -> float:
    if returns.std(ddof=1) == 0 or returns.empty:
        return 0.0
    return float(returns.std(ddof=1) * np.sqrt(periods_per_year))


def sharpe(returns: pd.Series, rf: float = 0.0, periods_per_year: int = ANNUALIZE_FACTOR) -> float:
    excess = returns - rf / periods_per_year
    sd = excess.std(ddof=1)
    if returns.empty or sd == 0 or not np.isfinite(sd) or sd < 1e-12:
        return 0.0
    return float(excess.mean() / sd * np.sqrt(periods_per_year))


def sortino(returns: pd.Series, rf: float = 0.0, periods_per_year: int = ANNUALIZE_FACTOR) -> float:
    excess = returns - rf / periods_per_year
    downside = excess[excess < 0]
    if len(downside) < 2:
        return 0.0
    dd_std = downside.std(ddof=1)
    if dd_std == 0 or not np.isfinite(dd_std) or dd_std < 1e-12:
        return 0.0
    return float(excess.mean() / dd_std * np.sqrt(periods_per_year))


def max_drawdown(equity: pd.Series) -> tuple[float, pd.Timedelta]:
    if len(equity) < 2:
        return 0.0, pd.Timedelta(0)
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max
    max_dd = float(dd.min())
    # duration: from peak to trough of worst drawdown
    if max_dd >= 0:
        return 0.0, pd.Timedelta(0)
    trough_idx = dd.idxmin()
    peak_idx = equity[:trough_idx].idxmax()
    dur: pd.Timedelta = pd.Timestamp(trough_idx) - pd.Timestamp(peak_idx)
    return max_dd, dur


def calmar(equity: pd.Series) -> float:
    mdd, _ = max_drawdown(equity)
    if mdd == 0:
        return 0.0
    return annualized_return(equity) / abs(mdd)


def profit_factor(returns: pd.Series) -> float:
    gross_win = returns[returns > 0].sum()
    gross_loss = -returns[returns < 0].sum()
    if gross_loss == 0:
        return float("inf") if gross_win > 0 else 0.0
    return float(gross_win / gross_loss)


def hit_rate(returns: pd.Series) -> float:
    if len(returns) == 0:
        return 0.0
    return float((returns > 0).sum() / len(returns))


def avg_win_loss_ratio(returns: pd.Series) -> float:
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    if losses.empty or wins.empty:
        return 0.0
    return float(wins.mean() / abs(losses.mean()))


def exposure(positions: pd.Series) -> float:
    if positions.empty:
        return 0.0
    return float((positions.abs() > 0).mean())


def compute_metric_panel(
    equity: pd.Series,
    returns: pd.Series,
    positions: pd.Series | None = None,
    periods_per_year: int = ANNUALIZE_FACTOR,
) -> MetricPanel:
    """All canonical metrics in one shot. The dict feed the tearsheet + bias audit.

    `positions` is optional; turnover and exposure are 0.0 when missing.
    """
    mdd, mdd_dur = max_drawdown(equity)
    panel: MetricPanel = {
        "total_return": total_return(equity),
        "cagr": annualized_return(equity, periods_per_year),
        "vol": annualized_vol(returns, periods_per_year),
        "sharpe": sharpe(returns, 0.0, periods_per_year),
        "sortino": sortino(returns, 0.0, periods_per_year),
        "calmar": calmar(equity),
        "max_drawdown": mdd,
        "max_drawdown_days": float(mdd_dur.days),
        "hit_rate": hit_rate(returns),
        "profit_factor": profit_factor(returns),
        "avg_win_loss_ratio": avg_win_loss_ratio(returns),
        "exposure": exposure(positions) if positions is not None else 0.0,
        "turnover": _turnover(positions) if positions is not None else 0.0,
        "n_trades": float(int((positions.diff().abs() > 0).sum() if positions is not None else 0)),
    }
    return panel


def _turnover(positions: pd.Series) -> float:
    if positions.empty:
        return 0.0
    return float(positions.diff().abs().sum())


# --- Bias audit (plan section 7) -------------------------------------------


def bias_audit(metric_panel: MetricPanel) -> dict[str, bool | str]:
    """Flag the four smoke guns the research called out:
    (a) Sharpe > 1.5
    (b) equity curve too smooth (vol < 5%)
    (c) trade count < 30
    (d) ratio of OOS-CAGR / IS-CAGR < 50%  (only available with walk-forward)
    """
    flags: dict[str, bool | str] = {}
    flags["high_sharpe"] = bool(metric_panel["sharpe"] > 1.5)
    flags["too_smooth"] = bool(metric_panel["vol"] < 0.05)
    flags["thin_trades"] = bool(metric_panel["n_trades"] < 30)
    if "oos_cagr" in metric_panel and "is_cagr" in metric_panel and metric_panel["is_cagr"] != 0:
        flags["low_wfe"] = bool((metric_panel["oos_cagr"] / metric_panel["is_cagr"]) < 0.5)
    else:
        flags["low_wfe"] = "n/a (requires IS/OOS)"
    flags["any_flag"] = any(v is True for v in flags.values())
    return flags


def attach_metric_panel(result) -> MetricPanel:
    """Compute and return the canonical metric dict for a BacktestResult.

    Reads `result.equity` and `result.returns` directly. Position information
    is derived from a synthetic positions Series reconstructed from trades when
    available (or empty when none — better to under-report than to fabricate).
    """
    eq = result.equity
    rr = result.returns
    # Reconstruct a position signal from trades when possible; otherwise None.
    # Phase 1 vectorized backtests typically lack per-bar positions in our schema,
    # so we leave position-dependent metrics as 0 (turnover/exposure) and compute
    # n_trades from the trades list.
    panel = compute_metric_panel(eq, rr, positions=None, periods_per_year=ANNUALIZE_FACTOR)
    panel["n_trades"] = float(result.n_trades)
    return panel
