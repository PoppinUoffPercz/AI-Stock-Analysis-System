"""Permutation test against random entries with a fixed holding-period exit."""

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
    market_returns: pd.Series,
    real_entries: pd.Series,
    metric_fn,
    *,
    n_entries: int | None = None,
    holding_period: int = 1,
    n_trials: int = 1000,
    rng_seed: int = 17,
    metric_name: str = "total_return",
) -> PermutationResult:
    """Compare observed entries with random market entries.

    Args:
      market_returns: per-bar buy-and-hold returns available to any entry.
      real_entries: boolean Series marking the observed strategy entries.
      metric_fn: callable(equity: pd.Series, returns: pd.Series) -> float.
      n_entries: number of random entries per trial; defaults to observed count.
      holding_period: explicit exit rule in bars for every random entry.
      n_trials: number of randomized trials.

    Returns:
      PermutationResult with p_value, real_metric, and the distribution.
    """
    rng = np.random.default_rng(rng_seed)
    if holding_period < 1:
        raise ValueError("holding_period must be at least 1")
    market_returns = market_returns.astype("float64").fillna(0.0)
    entries = real_entries.reindex(market_returns.index, fill_value=False).astype(bool)
    real_positions = np.flatnonzero(entries.to_numpy())
    random_count = len(real_positions) if n_entries is None else n_entries
    if random_count < 0:
        raise ValueError("n_entries must be non-negative")
    if len(market_returns) == 0 or random_count == 0:
        return PermutationResult(0, 1.0, 0.0, np.array([]), metric_name)
    candidate_positions = np.arange(len(market_returns) - holding_period)
    if random_count > len(candidate_positions):
        raise ValueError("n_entries exceeds available full holding-period entry bars")

    real_strategy_returns = _returns_for_entries(market_returns, real_positions, holding_period)
    real_metric_value = metric_fn(_equity(real_strategy_returns), real_strategy_returns)
    rand_metrics = np.zeros(n_trials)
    for i in range(n_trials):
        random_positions = rng.choice(candidate_positions, size=random_count, replace=False)
        random_strategy_returns = _returns_for_entries(
            market_returns, random_positions, holding_period
        )
        rand_metrics[i] = metric_fn(_equity(random_strategy_returns), random_strategy_returns)
    extreme = int((rand_metrics >= real_metric_value).sum())
    p = float((extreme + 1) / (n_trials + 1))
    return PermutationResult(
        n_trials=n_trials,
        p_value=p,
        real_metric=real_metric_value,
        random_metrics=rand_metrics,
        metric_name=metric_name,
    )


def _returns_for_entries(
    market_returns: pd.Series, entry_positions: np.ndarray, holding_period: int
) -> pd.Series:
    strategy_returns = np.zeros(len(market_returns), dtype="float64")
    market_array = market_returns.to_numpy()
    for entry in entry_positions:
        start = int(entry) + 1
        stop = min(start + holding_period, len(strategy_returns))
        if start >= stop:
            continue
        strategy_returns[start:stop] += market_array[start:stop]
    return pd.Series(strategy_returns, index=market_returns.index)


def _equity(returns: pd.Series) -> pd.Series:
    return (1 + returns.fillna(0.0)).cumprod() * 1.0
