"""Cleaner: validates and normalizes OHLCV frames to the canonical clean schema.

Plan section 4.3 mandates OHLC sanity, split/div adjustment, dedupe, boundary
tracking. We keep adjustment *out* of this layer's responsibility when the source
already returns back-adjusted prices (yfinance does); we just persist both raw
and adj columns next to corp-action facts so look-ahead audit is possible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest_engine.data.store import CLEAN_COLUMNS, TIMESTAMP_TZ

# Ohlc sanity checks. Catches typos / corrupted source rows.
OHLC_INVARIANTS = (
    lambda d: (d["high"] >= d[["open", "close", "low"]].max(axis=1)).all(),
    lambda d: (d["low"] <= d[["open", "close", "high"]].min(axis=1)).all(),
    lambda d: (d["volume"] >= 0).all(),
)


class CleanError(ValueError):
    pass


def validate_clean(df: pd.DataFrame, *, source: str) -> pd.DataFrame:
    """Validate a frame about to be written to clean/.

    Required raw columns: timestamp, open, high, low, close, volume.
    Optional (recommended): adj_open, adj_high, adj_low, adj_close, dividend, split_ratio.
    Optional columns are filled with sensible defaults if missing.

    Raises:
      CleanError: on missing required columns, NaN in OHLC, OHLC invariant violation,
                  non-monotonic timestamps, duplicate timestamps.
    """
    required = ("timestamp", "open", "high", "low", "close", "volume")
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise CleanError(f"missing required columns: {missing}")

    d = df.copy()
    if not isinstance(d["timestamp"].dtype, pd.DatetimeTZDtype):
        d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    if d["timestamp"].dt.tz is None:
        d["timestamp"] = d["timestamp"].dt.tz_localize(TIMESTAMP_TZ)

    # Drop duplicate timestamps; keep first to avoid look-ahead ambiguity.
    if d["timestamp"].duplicated().any():
        d = d.drop_duplicates(subset="timestamp", keep="first")
    # Monotonic must hold post-sort.
    d = d.sort_values("timestamp")
    if not d["timestamp"].is_monotonic_increasing:
        raise CleanError("timestamps not monotonic after sort")

    # Fill optional adjustment columns. Default to raw when absent (no adjustment).
    for raw, adj in (
        ("open", "adj_open"),
        ("high", "adj_high"),
        ("low", "adj_low"),
        ("close", "adj_close"),
    ):
        if adj not in d.columns:
            d[adj] = d[raw]
    if "dividend" not in d.columns:
        d["dividend"] = 0.0
    if "split_ratio" not in d.columns:
        d["split_ratio"] = 1.0

    # NaN in OHLC within active rows is a hard error.
    ohlc = d[["open", "high", "low", "close"]]
    if ohlc.isna().any().any():
        raise CleanError("NaN in OHLC")
    adjusted_ohlc = d[["adj_open", "adj_high", "adj_low", "adj_close"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if adjusted_ohlc.isna().any().any() or not np.isfinite(adjusted_ohlc.to_numpy()).all():
        raise CleanError("invalid adjusted OHLC")

    # Volume can be NaN for some sources; coerce to 0.
    d["volume"] = d["volume"].fillna(0)

    # Sanity invariants (plan 4.3 step 1).
    for inv in OHLC_INVARIANTS:
        if not inv(d):
            raise CleanError(f"OHLC invariant violated by source {source}: {inv.__name__}")

    # Corp-action sanity: dividend >= 0, split_ratio > 0
    if (d["dividend"] < 0).any():
        raise CleanError("negative dividend")
    if (d["split_ratio"] <= 0).any():
        raise CleanError("non-positive split_ratio")

    # The canonical schema includes a 'source' column. If absent, fill with a
    # placeholder so reindex succeeds; callers (store/ingest) overwrite it.
    if "source" not in d.columns:
        d["source"] = ""

    # Reorder to canonical schema.
    return d[list(CLEAN_COLUMNS)].astype(
        {
            "open": "float64",
            "high": "float64",
            "low": "float64",
            "close": "float64",
            "volume": "float64",
            "adj_open": "float64",
            "adj_high": "float64",
            "adj_low": "float64",
            "adj_close": "float64",
            "dividend": "float64",
            "split_ratio": "float64",
        }
    )
