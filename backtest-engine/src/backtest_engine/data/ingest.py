"""Ingest orchestrator: fetch from sources, validate via cleaner, write parquet.

`ingest_symbol(symbol, source)` is the public entry point in the data layer. It:
  1. Pulls the raw frame via the source adapter.
  2. Cross-checks against Stooq when available (warn only; flags > 0.5% disagreement).
  3. Validates via cleaner.
  4. Writes parquet partitions to `clean/`.
  5. Records symbol boundary (first/last active date) in the configured
     universe root.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import pandas as pd

from backtest_engine.data.clean import validate_clean
from backtest_engine.data.sources.base import (
    SOURCE_YFINANCE,
    CsvSource,
    StooqSource,
    YFinanceSource,
)
from backtest_engine.data.store import read_clean, write_clean
from backtest_engine.identifiers import validate_identifier

log = logging.getLogger(__name__)

SourceName = Literal["csv", "yfinance", "stooq"]

_DISAGREEMENT_THRESHOLD = 0.005  # 0.5%


def ingest_symbol(
    symbol: str,
    *,
    source: SourceName = "yfinance",
    start: str | None = None,
    end: str | None = None,
    clean_root: Path,
    universe_root: Path,
    cross_check: bool = True,
    input_path: Path | None = None,
) -> tuple[int, Path | None]:
    """Fetch, clean, write parquet. Returns rows and an optional boundary file."""
    symbol = validate_identifier(symbol, field_name="symbol")
    if source == "csv":
        if input_path is None:
            raise ValueError("CSV source requires an input path")
        df = CsvSource(input_path).fetch(symbol, start=start, end=end)
    elif source == SOURCE_YFINANCE:
        df = YFinanceSource().fetch(symbol, start=start, end=end)
    else:
        df = StooqSource().fetch(symbol, start=start, end=end)

    if df.empty:
        log.warning("no rows for %s via %s", symbol, source)
        return 0, None

    cleaned = validate_clean(df, source=source)

    # Cross-check with Stooq close prices (warn-only).
    if cross_check and source == SOURCE_YFINANCE:
        _cross_check_stooq(symbol, cleaned)

    written = write_clean(cleaned, clean_root, symbol=symbol, source=source)
    log.debug("wrote %d parquet partitions for %s", len(written), symbol)
    return len(cleaned), _write_boundary(cleaned, clean_root, symbol, universe_root)


def _cross_check_stooq(symbol: str, yf_df: pd.DataFrame) -> None:
    """Warn if yfinance close and Stooq close disagree beyond threshold."""
    try:
        stooq_df = StooqSource().fetch(symbol, start=None, end=None)
    except Exception as exc:  # noqa: BLE001
        log.warning("stooq cross-check unavailable for %s: %s", symbol, exc)
        return
    if stooq_df.empty:
        return
    merged = pd.merge(
        yf_df[["timestamp", "close"]],
        stooq_df[["timestamp", "close"]],
        on="timestamp",
        suffixes=("_yf", "_stooq"),
    )
    if merged.empty:
        return
    rel = (merged["close_yf"] - merged["close_stooq"]).abs() / merged["close_yf"]
    if (rel > _DISAGREEMENT_THRESHOLD).any():
        max_rel = rel.max()
        log.warning("%s: stooq/yfinance close disagreement max=%.2f%%", symbol, max_rel * 100)


def _write_boundary(df: pd.DataFrame, clean_root: Path, symbol: str, universe_root: Path) -> Path:
    """Write the symbol's first/last active date to a sidecar boundary file."""
    symbol = validate_identifier(symbol, field_name="symbol")
    universe_root = Path(universe_root)
    universe_root.mkdir(parents=True, exist_ok=True)
    bfile = universe_root / f"{symbol.upper()}_boundary.csv"
    timestamps = [df["timestamp"]]
    persisted = read_clean(clean_root, symbol)
    if not persisted.empty:
        timestamps.append(persisted["timestamp"])
    if bfile.exists():
        prior = pd.read_csv(bfile)
        timestamps.extend(
            pd.to_datetime(prior[column], utc=True)
            for column in ("first_date", "last_date")
            if column in prior
        )
    all_timestamps = pd.concat(timestamps, ignore_index=True).dropna()
    first = all_timestamps.min()
    last = all_timestamps.max()
    pd.DataFrame([{"symbol": symbol.upper(), "first_date": first, "last_date": last}]).to_csv(
        bfile, index=False
    )
    return bfile
