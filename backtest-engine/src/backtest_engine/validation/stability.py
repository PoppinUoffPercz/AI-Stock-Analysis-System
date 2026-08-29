"""Parameter-stability heatmap (plan section 6.4).

Compute the metric surface over a parameter grid; flag strategies whose
surface is a single spike (curve fit) instead of a broad plateau. Also
plot degradation of optimal parameters across walk-forward IS windows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class StabilityResult:
    surface: pd.DataFrame  # rows: param_x, columns: param_y, value: metric
    param_x: str
    param_y: str
    is_plateau: bool  # True if surface has a broad flat top (robust); False if spiked
    plateau_score: float  # 0..1, higher is more plateaued


def build_metric_surface(
    sweep_results: list,  # list[BacktestResult]
    *,
    param_x: str,
    param_y: str,
    metric: str = "total_return",
) -> StabilityResult:
    """Given BacktestResults from a param sweep, build a 2D metric surface.

    Plan: robust strategies have a broad smooth plateau; spikes = curve fit.
    Heuristic: look at the metric within 10% of the optimum; if that volume
    spans > 25% of the grid, call it a plateau.
    """
    rows = []
    for r in sweep_results:
        if param_x not in r.params or param_y not in r.params:
            continue
        # Use final_equity / capital - 1 as the metric if "total_return"
        if metric == "total_return":
            v = r.final_equity / r.capital - 1.0 if r.capital else 0.0
        else:
            v = float(r.raw_metrics.get(metric, 0.0))
        rows.append({param_x: r.params[param_x], param_y: r.params[param_y], "v": v})
    if not rows:
        return StabilityResult(
            surface=pd.DataFrame(),
            param_x=param_x,
            param_y=param_y,
            is_plateau=False,
            plateau_score=0.0,
        )
    df = pd.DataFrame(rows).pivot(index=param_x, columns=param_y, values="v")
    # Plateau score: share of grid entries within 10% of best.
    flat = df.to_numpy().flatten()
    flat = flat[~np.isnan(flat)]
    if len(flat) == 0:
        return StabilityResult(
            surface=df, param_x=param_x, param_y=param_y, is_plateau=False, plateau_score=0.0
        )
    best = float(np.nanmax(flat))
    worst = float(np.nanmin(flat))
    if best == worst:
        return StabilityResult(
            surface=df,
            param_x=param_x,
            param_y=param_y,
            is_plateau=True,
            plateau_score=1.0,
        )
    # within 10% of optimal via the [worst, best] span
    norm = (flat - worst) / (best - worst)
    near_best_share = float((norm >= 0.90).sum() / len(flat))
    is_plateau = near_best_share >= 0.25
    return StabilityResult(
        surface=df,
        param_x=param_x,
        param_y=param_y,
        is_plateau=is_plateau,
        plateau_score=near_best_share,
    )


def param_drift(fold_params: list[dict[str, Any]], param_names: list[str]) -> pd.DataFrame:
    """Show how optimal params drift across walk-forward folds.

    Drifting optimal params are fine; jumping is a red flag. Returns a DataFrame
    indexed by fold with one column per param.
    """
    rows = []
    for i, params in enumerate(fold_params):
        row = {"fold": i}
        for p in param_names:
            row[p] = params.get(p, np.nan)
        rows.append(row)
    return pd.DataFrame(rows).set_index("fold")
