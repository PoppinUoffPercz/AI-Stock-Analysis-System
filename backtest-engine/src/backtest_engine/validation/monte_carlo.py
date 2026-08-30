"""Trade-order permutation and return bootstrap validation methods."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class MonteCarloResult:
    """Drawdown distribution from permuting the order of realized trades."""

    n_trials: int
    max_dd_pcts: np.ndarray
    max_dd_pctile_5: float
    max_dd_pctile_95: float
    max_dd_p_realized: float


@dataclass
class BootstrapResult:
    """Distributions from resampling realized returns with replacement."""

    n_trials: int
    max_dd_pcts: np.ndarray
    sharpe_samples: np.ndarray
    terminal_wealth: np.ndarray
    max_dd_pctile_5: float
    max_dd_pctile_95: float
    max_dd_p_realized: float


def shuffle_trade_order(
    trade_returns: pd.Series,
    *,
    n_trials: int = 1000,
    rng_seed: int = 42,
) -> MonteCarloResult:
    """Permute realized trade returns to estimate path-dependent drawdown."""
    returns = _as_returns(trade_returns)
    if len(returns) < 2 or n_trials < 1:
        return MonteCarloResult(0, np.array([]), 0.0, 0.0, 0.0)

    rng = np.random.default_rng(rng_seed)
    realized_mdd = _max_drawdown_from_returns(returns)
    max_dds = np.empty(n_trials)
    for i in range(n_trials):
        max_dds[i] = _max_drawdown_from_returns(rng.permutation(returns))
    return MonteCarloResult(
        n_trials=n_trials,
        max_dd_pcts=max_dds,
        max_dd_pctile_5=float(np.percentile(max_dds, 5)),
        max_dd_pctile_95=float(np.percentile(max_dds, 95)),
        max_dd_p_realized=float((max_dds <= realized_mdd).sum() / n_trials),
    )


def bootstrap_trade_returns(
    trade_returns: pd.Series,
    *,
    n_trials: int = 1000,
    rng_seed: int = 7,
    periods_per_year: int | None = None,
) -> BootstrapResult:
    """Bootstrap realized returns for terminal wealth and per-trade Sharpe samples.

    Sharpe is unannualized by default. Pass ``periods_per_year`` only when the
    sampled returns represent a regular period that should be annualized.
    """
    _validate_periods_per_year(periods_per_year)
    returns = _as_returns(trade_returns)
    if len(returns) == 0 or n_trials < 1:
        return _empty_bootstrap_result()

    rng = np.random.default_rng(rng_seed)
    realized_mdd = _max_drawdown_from_returns(returns)
    max_dds = np.empty(n_trials)
    sharpes = np.empty(n_trials)
    terminal = np.empty(n_trials)
    for i in range(n_trials):
        sample = rng.choice(returns, size=len(returns), replace=True)
        wealth = np.cumprod(1 + sample)
        terminal[i] = float(wealth[-1])
        max_dds[i] = _max_drawdown_from_returns(sample)
        sharpes[i] = _sharpe(sample, periods_per_year=periods_per_year)
    return _bootstrap_result(max_dds, sharpes, terminal, realized_mdd)


def block_bootstrap_returns(
    returns: pd.Series,
    *,
    block_size: int = 21,
    n_trials: int = 1000,
    rng_seed: int = 7,
    periods_per_year: int | None = None,
) -> BootstrapResult:
    """Block-bootstrap returns to preserve short-lag autocorrelation.

    Sharpe is unannualized by default; ``periods_per_year`` opts into
    annualization.
    """
    if block_size < 1:
        raise ValueError("block_size must be at least 1")
    _validate_periods_per_year(periods_per_year)
    r = _as_returns(returns)
    if len(r) == 0 or n_trials < 1:
        return _empty_bootstrap_result()
    if len(r) < block_size * 2:
        return bootstrap_trade_returns(
            pd.Series(r),
            n_trials=n_trials,
            rng_seed=rng_seed,
            periods_per_year=periods_per_year,
        )

    rng = np.random.default_rng(rng_seed)
    realized_mdd = _max_drawdown_from_returns(r)
    max_dds = np.empty(n_trials)
    sharpes = np.empty(n_trials)
    terminal = np.empty(n_trials)
    n_blocks = int(np.ceil(len(r) / block_size))
    for i in range(n_trials):
        starts = rng.integers(0, len(r) - block_size + 1, n_blocks)
        sample = np.concatenate([r[s : s + block_size] for s in starts])[: len(r)]
        wealth = np.cumprod(1 + sample)
        terminal[i] = float(wealth[-1])
        max_dds[i] = _max_drawdown_from_returns(sample)
        sharpes[i] = _sharpe(sample, periods_per_year=periods_per_year)
    return _bootstrap_result(max_dds, sharpes, terminal, realized_mdd)


def _as_returns(returns: pd.Series) -> np.ndarray:
    return returns.dropna().astype("float64").to_numpy()


def _bootstrap_result(
    max_dds: np.ndarray,
    sharpes: np.ndarray,
    terminal: np.ndarray,
    realized_mdd: float,
) -> BootstrapResult:
    return BootstrapResult(
        n_trials=len(max_dds),
        max_dd_pcts=max_dds,
        sharpe_samples=sharpes,
        terminal_wealth=terminal,
        max_dd_pctile_5=float(np.percentile(max_dds, 5)),
        max_dd_pctile_95=float(np.percentile(max_dds, 95)),
        max_dd_p_realized=float((max_dds <= realized_mdd).sum() / len(max_dds)),
    )


def _empty_bootstrap_result() -> BootstrapResult:
    empty = np.array([])
    return BootstrapResult(0, empty, empty, empty, 0.0, 0.0, 0.0)


def _sharpe(returns: np.ndarray, periods_per_year: int | None = None) -> float:
    sd = returns.std(ddof=1)
    if not np.isfinite(sd) or sd == 0:
        return 0.0
    annualization = np.sqrt(periods_per_year) if periods_per_year is not None else 1.0
    return float(returns.mean() / sd * annualization)


def _validate_periods_per_year(periods_per_year: int | None) -> None:
    if periods_per_year is not None and periods_per_year < 1:
        raise ValueError("periods_per_year must be at least 1")


def _max_drawdown_from_returns(rets: np.ndarray) -> float:
    """Compute max drawdown of a returns array as a single float (negative or 0)."""
    if len(rets) == 0:
        return 0.0
    wealth = np.concatenate(([1.0], np.cumprod(1 + rets)))
    running_max = np.maximum.accumulate(wealth)
    dd = (wealth - running_max) / running_max
    return float(dd.min())
