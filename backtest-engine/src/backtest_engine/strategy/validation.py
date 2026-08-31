"""Shared validation for precomputed strategy signal frames."""

from __future__ import annotations

import pandas as pd
from pandas.api.types import is_bool_dtype


class SignalValidationError(ValueError):
    """Raised when signals cannot be aligned safely with an OHLC frame."""


def validate_signal_frame(signals: pd.DataFrame, ohlc: pd.DataFrame) -> pd.DataFrame:
    """Return a defensive, canonical copy of signals aligned to ``ohlc``."""
    if not isinstance(signals, pd.DataFrame):
        raise SignalValidationError("signals must be a pandas DataFrame")
    if not isinstance(ohlc, pd.DataFrame):
        raise SignalValidationError("ohlc must be a pandas DataFrame")

    signal_index = _canonical_index(signals, "signals")
    ohlc_index = _canonical_index(ohlc, "ohlc")
    if len(signal_index) != len(ohlc_index) or not signal_index.equals(ohlc_index):
        raise SignalValidationError(
            "signals and ohlc must have the same UTC timestamps, order, and length"
        )

    missing = [name for name in ("entry",) if name not in signals.columns]
    extra = [name for name in signals.columns if name not in {"entry", "exit"}]
    if missing:
        raise SignalValidationError(f"signals missing required column(s): {missing}")
    if extra:
        raise SignalValidationError(f"signals has unsupported column(s): {extra}")

    columns = ["entry"] + (["exit"] if "exit" in signals.columns else [])
    canonical = signals.loc[:, columns].copy(deep=True)
    for column in columns:
        values = canonical[column]
        if values.isna().any():
            raise SignalValidationError(f"signals.{column} must contain no missing values")
        if not is_bool_dtype(values.dtype):
            raise SignalValidationError(f"signals.{column} must contain only real booleans")
        canonical[column] = values.astype(bool)

    canonical.index = signal_index
    return canonical


def _canonical_index(frame: pd.DataFrame, name: str) -> pd.DatetimeIndex:
    index = frame.index
    if not isinstance(index, pd.DatetimeIndex) or index.nlevels != 1:
        raise SignalValidationError(f"{name} index must be a one-dimensional DatetimeIndex")
    if index.tz is None:
        raise SignalValidationError(
            f"{name} index must be timezone-aware so UTC instants are defined"
        )
    if index.hasnans:
        raise SignalValidationError(f"{name} index must not contain NaT")
    canonical = index.tz_convert("UTC")
    if not canonical.is_unique:
        raise SignalValidationError(f"{name} index must contain unique timestamps")
    if not canonical.is_monotonic_increasing:
        raise SignalValidationError(f"{name} index must be strictly increasing")
    return canonical
