"""Walk-forward analysis (plan section 6.1).

Rolling-window: optimize on in-sample (IS), apply fixed params on out-of-sample
(OOS), stitch OOS equity curves, report WFE = OOS-CAGR / IS-CAGR. Flag < 50%.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from backtest_engine.metrics.core import annualized_return
from backtest_engine.strategy.spec import StrategySpec


@dataclass
class WalkForwardResult:
    oos_equity: pd.Series  # stitched OOS equity
    is_cagrs: list[float]  # per-fold IS CAGR
    oos_cagrs: list[float]  # per-fold OOS CAGR
    wfe: float  # aggregate OOS-CAGR / IS-CAGR
    fold_params: list[dict[str, Any]]
    is_intervals: list[tuple[pd.Timestamp, pd.Timestamp]]
    oos_intervals: list[tuple[pd.Timestamp, pd.Timestamp]]


def walk_forward(
    spec: StrategySpec,
    ohlc: pd.DataFrame,
    *,
    run_engine: Callable[..., Any],
    optimize: Callable[..., dict[str, Any]],
    is_windows: list[tuple[pd.Timestamp, pd.Timestamp]],
    oos_windows: list[tuple[pd.Timestamp, pd.Timestamp]],
    engine_name: str = "vectorbt",
) -> WalkForwardResult:
    """Run walk-forward over half-open ``[start, end)`` IS/OOS windows.

    Args:
      optimise(is_ohlc) -> dict[str, Any]: returns best params from IS data
      run_engine(spec, oos_ohlc, signal_ohlc=history_through_oos_end, ...):
        ``signal_ohlc`` may warm indicators, but execution starts flat on
        ``oos_ohlc``. Optimisation never receives OOS observations.

    Returns:
      WalkForwardResult with stitched OOS equity and WFE.
    """
    if len(is_windows) != len(oos_windows):
        raise ValueError("IS and OOS windows must align 1:1")
    _validate_is_windows(is_windows)
    _validate_oos_windows(oos_windows)
    for (_, is_end), (oos_start, _) in zip(is_windows, oos_windows, strict=True):
        if is_end > oos_start:
            raise ValueError(
                "IS window contaminates paired OOS window; IS end must be <= OOS start"
            )
    folds = sorted(zip(is_windows, oos_windows, strict=True), key=lambda fold: fold[1])
    is_cagrs: list[float] = []
    oos_cagrs: list[float] = []
    fold_params: list[dict[str, Any]] = []
    oos_equity_parts: list[pd.Series] = []
    is_intervals: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    oos_intervals: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for (is_s, is_e), (oos_s, oos_e) in folds:
        is_ohlc = _slice(ohlc, is_s, is_e)
        oos_ohlc = _slice(ohlc, oos_s, oos_e)
        if is_ohlc.empty or oos_ohlc.empty:
            continue
        params = optimize(spec, is_ohlc)
        fold_params.append(params)
        # Compute IS CAGR via a single in-sample run (no futurity leak to OOS)
        is_res = run_engine(
            spec,
            is_ohlc,
            engine=engine_name,
            params=params,
            run_id=f"wf-is-{is_s.date()}-{is_e.date()}",
        )
        is_cagrs.append(annualized_return(is_res.equity))
        is_intervals.append((is_s, is_e))
        # OOS run with FROZEN params from IS
        oos_res = run_engine(
            spec,
            oos_ohlc,
            engine=engine_name,
            params=params,
            run_id=f"wf-oos-{oos_s.date()}-{oos_e.date()}",
            signal_ohlc=_slice(ohlc, ohlc.index.min(), oos_e),
        )
        oos_equity = _slice_series(oos_res.equity, oos_s, oos_e)
        if oos_equity.index.has_duplicates:
            raise ValueError("duplicate OOS equity dates")
        oos_equity = oos_equity.sort_index()
        oos_cagrs.append(annualized_return(oos_equity))
        oos_intervals.append((oos_s, oos_e))
        # Stitch OOS equity (continuing from prior stitched value for continuity)
        offset = oos_equity_parts[-1].iloc[-1] if oos_equity_parts else 1.0
        offset_factor = offset / oos_equity.iloc[0]
        stitched = oos_equity * offset_factor
        oos_equity_parts.append(stitched)
    oos_equity = (
        pd.concat(oos_equity_parts).sort_index() if oos_equity_parts else pd.Series(dtype=float)
    )
    if oos_equity.index.has_duplicates:
        raise ValueError("duplicate OOS equity dates")
    is_cagr_mean = float(np.mean(is_cagrs)) if is_cagrs else 0.0
    oos_cagr_mean = float(np.mean(oos_cagrs)) if oos_cagrs else 0.0
    wfe = (oos_cagr_mean / is_cagr_mean) if is_cagr_mean != 0 else 0.0
    return WalkForwardResult(
        oos_equity=oos_equity,
        is_cagrs=is_cagrs,
        oos_cagrs=oos_cagrs,
        wfe=wfe,
        fold_params=fold_params,
        is_intervals=is_intervals,
        oos_intervals=oos_intervals,
    )


def rolling_windows(
    ohlc: pd.DataFrame,
    *,
    is_years: int,
    oos_years: int,
    step_years: int = 1,
) -> tuple[list[tuple[pd.Timestamp, pd.Timestamp]], list[tuple[pd.Timestamp, pd.Timestamp]]]:
    """Convenience: emit (IS, OOS) pairs over history. Aligned to calendar year-end."""
    if ohlc.empty:
        return [], []
    start = ohlc.index[0]
    end = ohlc.index[-1]
    is_windows = []
    oos_windows = []
    cursor = pd.Timestamp(start).normalize()
    while True:
        is_s = cursor
        is_e = is_s + pd.DateOffset(years=is_years)
        oos_s = is_e
        oos_e = oos_s + pd.DateOffset(years=oos_years)
        if oos_e > end + pd.Timedelta(days=1):
            break
        is_windows.append((is_s, is_e))
        oos_windows.append((oos_s, oos_e))
        cursor = cursor + pd.DateOffset(years=step_years)
    return is_windows, oos_windows


def _slice(ohlc: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return ohlc.loc[(ohlc.index >= start) & (ohlc.index < end)]


def _slice_series(series: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    return series.loc[(series.index >= start) & (series.index < end)]


def _validate_oos_windows(
    windows: list[tuple[pd.Timestamp, pd.Timestamp]],
) -> None:
    for start, end in windows:
        if start >= end:
            raise ValueError("OOS windows must be non-empty half-open intervals")
    ordered = sorted(windows)
    if any(
        start < prior_end for (_, prior_end), (start, _) in zip(ordered, ordered[1:], strict=False)
    ):
        raise ValueError("OOS windows must not overlap")


def _validate_is_windows(windows: list[tuple[pd.Timestamp, pd.Timestamp]]) -> None:
    if any(start >= end for start, end in windows):
        raise ValueError("IS windows must be non-empty half-open intervals")
