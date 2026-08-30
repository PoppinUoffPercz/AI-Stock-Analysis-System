"""Random-entry permutation testing with a strategy-equivalent evaluator."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class EntryEvaluation:
    """The observable result of evaluating one entry series."""

    metric: float
    completed_trades: int
    exposure: pd.Series


@dataclass(frozen=True)
class PermutationResult:
    """Results from comparing real entries with comparable random entries."""

    n_trials: int
    p_value: float
    real_metric: float
    random_metrics: np.ndarray
    metric_name: str
    real_completed_trades: int
    random_completed_trades: np.ndarray
    real_max_exposure: float
    random_max_exposures: np.ndarray


def _validate_evaluation(evaluation: EntryEvaluation, index: pd.Index) -> tuple[float, int, float]:
    if not isinstance(evaluation, EntryEvaluation):
        raise TypeError("entry evaluator must return EntryEvaluation")

    metric = float(evaluation.metric)
    if not np.isfinite(metric):
        raise ValueError("entry evaluator metric must be finite")

    completed_trades = int(evaluation.completed_trades)
    if completed_trades < 0 or completed_trades != evaluation.completed_trades:
        raise ValueError("entry evaluator completed_trades must be a non-negative integer")

    exposure = evaluation.exposure
    if not isinstance(exposure, pd.Series) or not exposure.index.equals(index):
        raise ValueError("entry evaluator exposure must use the entry index")
    exposure_values = exposure.to_numpy(dtype="float64")
    if not np.isfinite(exposure_values).all() or (exposure_values < 0).any():
        raise ValueError("entry evaluator exposure must be finite and non-negative")
    max_exposure = float(exposure_values.max(initial=0.0))
    if max_exposure > 1.0 + 1e-12:
        raise ValueError("entry evaluator exposure must stay between 0 and 1")

    return metric, completed_trades, max_exposure


def random_entry_permutation(
    real_entries: pd.Series,
    *,
    evaluator: Callable[[pd.Series], EntryEvaluation],
    n_trials: int = 1000,
    rng_seed: int = 17,
    max_resamples: int = 100,
    metric_name: str = "total_return",
) -> PermutationResult:
    """Compare real entries with random entries under the same strategy policy.

    The evaluator owns fills, exits, costs, valuation, and exposure policy. Each
    accepted random candidate must produce the same number of completed trades
    as the real entry series.
    """
    if n_trials < 0:
        raise ValueError("n_trials must be non-negative")
    if max_resamples < 1:
        raise ValueError("max_resamples must be at least 1")

    entries = real_entries.astype(bool).copy()
    real_metric, real_completed_trades, real_max_exposure = _validate_evaluation(
        evaluator(entries), entries.index
    )

    if real_completed_trades == 0 or n_trials == 0:
        return PermutationResult(
            n_trials=0,
            p_value=1.0,
            real_metric=real_metric,
            random_metrics=np.empty(0, dtype="float64"),
            metric_name=metric_name,
            real_completed_trades=real_completed_trades,
            random_completed_trades=np.empty(0, dtype="int64"),
            real_max_exposure=real_max_exposure,
            random_max_exposures=np.empty(0, dtype="float64"),
        )

    if real_completed_trades > len(entries):
        raise ValueError("real completed trade count exceeds available entry bars")

    rng = np.random.default_rng(rng_seed)
    positions = np.arange(len(entries))
    random_metrics: list[float] = []
    random_completed_trades: list[int] = []
    random_max_exposures: list[float] = []

    for _ in range(n_trials):
        accepted = False
        for _ in range(max_resamples):
            candidate = pd.Series(False, index=entries.index, dtype=bool)
            candidate.iloc[rng.choice(positions, size=real_completed_trades, replace=False)] = True
            try:
                metric, completed_trades, max_exposure = _validate_evaluation(
                    evaluator(candidate), entries.index
                )
            except ValueError:
                continue
            if completed_trades != real_completed_trades:
                continue
            random_metrics.append(metric)
            random_completed_trades.append(completed_trades)
            random_max_exposures.append(max_exposure)
            accepted = True
            break
        if not accepted:
            raise ValueError(
                "unable to generate a comparable random-entry sample with "
                f"{real_completed_trades} completed trades after {max_resamples} attempts"
            )

    random_metric_array = np.asarray(random_metrics, dtype="float64")
    random_completed_array = np.asarray(random_completed_trades, dtype="int64")
    random_exposure_array = np.asarray(random_max_exposures, dtype="float64")
    extreme = int(np.count_nonzero(random_metric_array >= real_metric))
    p_value = (extreme + 1) / (n_trials + 1)
    return PermutationResult(
        n_trials=n_trials,
        p_value=float(p_value),
        real_metric=real_metric,
        random_metrics=random_metric_array,
        metric_name=metric_name,
        real_completed_trades=real_completed_trades,
        random_completed_trades=random_completed_array,
        real_max_exposure=real_max_exposure,
        random_max_exposures=random_exposure_array,
    )
