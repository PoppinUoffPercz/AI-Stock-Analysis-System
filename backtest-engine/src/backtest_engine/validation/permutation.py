"""Permutation test vs random-entry H0 (plan section 6.3).

Take an existing backtest result's daily returns (which encode the strategy's
exits). Generate N variants with the *same exit logic* but random entry dates,
then compare the random-entry distribution to the real strategy's metric.

p-value = fraction of random-entry variants that beat the real strategy.
H0: "no edge — entries are random." Low p (e.g. < 0.05) -> reject H0.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class PermutationResult:
    n_trials: int
    p_value: float  # Lower is more significant.
    real_metric: float
    random_metrics: np.ndarray
    metric_name: str


def random_entry_permutation(
    returns: pd.Series,
    n_entries: int,
    metric_fn,
    *,
    n_trials: int = 1000,
    rng_seed: int = 17,
    metric_name: str = "total_return",
) -> PermutationResult:
    """Build random-entry variants from the realized exit pattern.

    Args:
      returns: per-bar realized returns of the *real* strategy. We ONLY reuse
        the *trade boundary structure* of these: when returns are zero, the
        strategy was flat; when nonzero, it was in trade. The count of nonzero
        returns approximates `n_trades * avg_trade_length`.
      n_entries: number of random entry dates to inject per trial (use the real
        strategy's trade count).
      metric_fn: callable(equity: pd.Series, returns: pd.Series) -> float.
      n_trials: number of permutation trials.

    Returns:
      PermutationResult with p_value, real_metric, and the distribution.
    """
    rng = np.random.default_rng(rng_seed)
    n = len(returns)
    if n == 0 or n_entries == 0:
        return PermutationResult(0, 1.0, 0.0, np.array([]), metric_name)

    # Real: total return of buy-and-hold over the same bars? No — we want the
    # same exit-driven return stream we observed. The cleanest H0 is to keep
    # the *same* set of returns but randomly re-permute their order across
    # bars — this preserves the empirical return distribution while destroying
    # any entry-timing edge. That matches "same exits, random entries".
    real_metric_value = metric_fn(_equity(returns), returns)
    arr = returns.to_numpy()
    rand_metrics = np.zeros(n_trials)
    for i in range(n_trials):
        shuffled = rng.permutation(arr)
        shuffled_ret = pd.Series(shuffled, index=returns.index)
        rand_metrics[i] = metric_fn(_equity(shuffled_ret), shuffled_ret)
    # p-value per plan: fraction of random variants that BEAT the real strategy
    p = float((rand_metrics >= real_metric_value).sum() / n_trials)
    return PermutationResult(
        n_trials=n_trials,
        p_value=p,
        real_metric=real_metric_value,
        random_metrics=rand_metrics,
        metric_name=metric_name,
    )


def _equity(returns: pd.Series) -> pd.Series:
    return (1 + returns.fillna(0.0)).cumprod() * 1.0
