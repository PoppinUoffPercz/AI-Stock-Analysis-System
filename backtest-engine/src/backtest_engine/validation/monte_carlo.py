"""Monte Carlo trade-order permutation (plan section 6.2).

Take a realized trade list (or per-bar returns); resample the *order* 1,000+ times
to estimate the distribution of max-DD/Sharpe/terminal wealth under the same
trade population but randomized entry order. Also block-bootstrap returns to
preserve autocorrelation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class MonteCarloResult:
    n_trials: int
    max_dd_pcts: np.ndarray  # distribution of max-DD per shuffle
    sharpe_samples: np.ndarray
    terminal_wealth: np.ndarray
    max_dd_pctile_5: float
    max_dd_pctile_95: float
    max_dd_p_realized: float  # percentile rank of realized max-DD within shuffled


def shuffle_trade_order(
    equity: pd.Series,
    trades_list_len: int | None = None,
    *,
    n_trials: int = 1000,
    rng_seed: int = 42,
) -> MonteCarloResult:
    """Shuffle the sequence of per-bar returns; reflect realistic max-DD distribution.

    Plan 6.2: keep the empirical trade distribution but reshuffle *order*. We
    interpret this at the returns layer — shuffle daily returns, then compounding
    recovers an alternate equity path. With ~252*D years of daily returns, this
    empirically estimates drawdown magnitude.

    Args:
      equity: BacktestResult.equity (tz-aware UTC, daily-ish index)
      trades_list_len: not used directly; preserved for API alignment with
        future per-trade shuffles.
      n_trials: number of remixes.
    """
    if len(equity) < 2:
        return MonteCarloResult(0, np.array([]), np.array([]), np.array([]), 0.0, 0.0, 0.0)
    rng = np.random.default_rng(rng_seed)
    rets = equity.pct_change().dropna().to_numpy()

    # Compute realized max-DD first.
    realized_mdd = _max_drawdown_from_returns(rets)

    # Storage
    max_dds = np.zeros(n_trials)
    sharpes = np.zeros(n_trials)
    terminal_wealth = np.zeros(n_trials)
    for i in range(n_trials):
        shuffled = rng.permutation(rets)
        equity_path = np.cumprod(1 + shuffled)
        terminal_wealth[i] = float(equity_path[-1])
        max_dds[i] = _max_drawdown_from_returns(shuffled)
        if shuffled.std(ddof=1) > 0:
            sharpes[i] = float(shuffled.mean() / shuffled.std(ddof=1) * np.sqrt(252))
        else:
            sharpes[i] = 0.0
    sorted_dd = np.sort(max_dds)
    # Percentile rank of realized mdd vs shuffled distribution
    pctile_realized = float((max_dds <= realized_mdd).sum() / n_trials)
    return MonteCarloResult(
        n_trials=n_trials,
        max_dd_pcts=max_dds,
        sharpe_samples=sharpes,
        terminal_wealth=terminal_wealth,
        max_dd_pctile_5=float(np.percentile(sorted_dd, 5)),
        max_dd_pctile_95=float(np.percentile(sorted_dd, 95)),
        max_dd_p_realized=pctile_realized,
    )


def block_bootstrap_returns(
    returns: pd.Series,
    *,
    block_size: int = 21,
    n_trials: int = 1000,
    rng_seed: int = 7,
) -> MonteCarloResult:
    """Block bootstrap preserving short-lag autocorrelation. Returns the same shape."""
    r = returns.dropna().to_numpy()
    if len(r) < block_size * 2:
        return shuffle_trade_order(
            (1 + pd.Series(r)).cumprod(), n_trials=n_trials, rng_seed=rng_seed
        )
    rng = np.random.default_rng(rng_seed)
    realized_mdd = _max_drawdown_from_returns(r)
    max_dds, sharpes, terminal = (np.zeros(n_trials), np.zeros(n_trials), np.zeros(n_trials))
    for i in range(n_trials):
        # Number of blocks needed, with replacement
        n_blocks = int(np.ceil(len(r) / block_size))
        starts = rng.integers(0, len(r) - block_size + 1, n_blocks)
        boot = np.concatenate([r[s : s + block_size] for s in starts])[: len(r)]
        equity_path = np.cumprod(1 + boot)
        terminal[i] = float(equity_path[-1])
        max_dds[i] = _max_drawdown_from_returns(boot)
        sharpes[i] = (
            float(boot.mean() / boot.std(ddof=1) * np.sqrt(252)) if boot.std(ddof=1) else 0.0
        )
    sorted_dd = np.sort(max_dds)
    pctile_realized = float((max_dds <= realized_mdd).sum() / n_trials)
    return MonteCarloResult(
        n_trials=n_trials,
        max_dd_pcts=max_dds,
        sharpe_samples=sharpes,
        terminal_wealth=terminal,
        max_dd_pctile_5=float(np.percentile(sorted_dd, 5)),
        max_dd_pctile_95=float(np.percentile(sorted_dd, 95)),
        max_dd_p_realized=pctile_realized,
    )


def _max_drawdown_from_returns(rets: np.ndarray) -> float:
    """Compute max drawdown of a returns array as a single float (negative or 0)."""
    if len(rets) == 0:
        return 0.0
    wealth = np.cumprod(1 + rets)
    running_max = np.maximum.accumulate(wealth)
    dd = (wealth - running_max) / running_max
    return float(dd.min())
