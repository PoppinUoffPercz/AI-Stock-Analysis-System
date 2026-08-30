"""Parquet store: schema + I/O. Partition by `symbol/year` for cheap reads.

The store is the *only* component allowed to read/write `data/clean`. Sources
write raw artifacts under `data/raw` via their own logic; everything that ends
up in `clean/` follows the schema enforced here.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Final

import pandas as pd

# Canonical clean schema (plan section 4.2)
CLEAN_COLUMNS: Final[tuple[str, ...]] = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adj_open",
    "adj_high",
    "adj_low",
    "adj_close",
    "dividend",
    "split_ratio",
    "source",
)

# columns that MUST be tz-aware UTC
TIMESTAMP_TZ = "UTC"


def clean_path(root: Path, symbol: str, year: int) -> Path:
    """Return the canonical parquet path for a symbol-year partition."""
    return Path(root) / symbol.upper() / f"{year}.parquet"


def write_clean(
    df: pd.DataFrame,
    root: Path,
    *,
    symbol: str,
    source: str,
) -> list[Path]:
    """Validate against CLEAN_COLUMNS then write one parquet per year."""
    from backtest_engine.data.clean import validate_clean

    df = validate_clean(df, source=source)
    # Defensive copy so we don't mutate caller's frame.
    df = df.copy()
    df["source"] = source

    written: list[Path] = []
    for year, group in df.groupby(df["timestamp"].dt.year, sort=True):
        out = clean_path(root, symbol, int(year))
        out.parent.mkdir(parents=True, exist_ok=True)
        incoming = group.sort_values("timestamp").reset_index(drop=True)
        if out.exists():
            existing = pd.read_parquet(out)
            merged = pd.concat([existing, incoming], ignore_index=True)
        else:
            merged = incoming
        merged = merged.drop_duplicates(subset="timestamp", keep="last")
        merged = (
            validate_clean(merged, source=source).sort_values("timestamp").reset_index(drop=True)
        )

        fd, temp_name = tempfile.mkstemp(prefix=f".{out.stem}.", suffix=".tmp", dir=out.parent)
        os.close(fd)
        temp = Path(temp_name)
        try:
            merged.to_parquet(temp, index=False)
            os.replace(temp, out)
        finally:
            temp.unlink(missing_ok=True)
        written.append(out)
    return written


def read_clean(
    root: Path, symbol: str, *, start: str | None = None, end: str | None = None
) -> pd.DataFrame:
    """Concatenate yearly parquet partitions for a symbol between [start, end].

    `start` / `end` are inclusive date strings ('YYYY-MM-DD'); either may be None.
    """
    sym_dir = Path(root) / symbol.upper()
    if not sym_dir.is_dir():
        return pd.DataFrame(columns=CLEAN_COLUMNS)

    parts: list[pd.DataFrame] = []
    start_year = pd.Timestamp(start).year if start else None
    end_year = pd.Timestamp(end).year if end else None
    for p in sorted(sym_dir.glob("*.parquet")):
        year = int(p.stem)
        if start_year is not None and year < start_year:
            continue
        if end_year is not None and year > end_year:
            continue
        parts.append(pd.read_parquet(p))
    if not parts:
        return pd.DataFrame(columns=CLEAN_COLUMNS)
    df = pd.concat(parts, ignore_index=True).sort_values("timestamp")
    if start:
        df = df[df["timestamp"] >= pd.Timestamp(start, tz=TIMESTAMP_TZ)]
    if end:
        df = df[df["timestamp"] <= pd.Timestamp(end, tz=TIMESTAMP_TZ)]
    return df.reset_index(drop=True)
