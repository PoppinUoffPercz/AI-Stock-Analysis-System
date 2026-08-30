"""Universe membership: as-of point-in-time ticker set + survivorship handling.

The plan calls for an explicit universe membership file (CSV) listing each
ticker's `list_date` / `delist_date` / `delist_reason`, and an as-of loader
that refuses a ticker after its delist date (prevents look-ahead via dead-name
persistence).

Schema (CSV at `data/universe/<name>.csv`):

    symbol,list_date,delist_date,delist_reason

Either date may be empty: empty list_date = unknown/beginning; empty
delist_date = still trading.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pandas as pd

BOUNDARY_SUFFIX: Final[str] = "_boundary.csv"


class Universe:
    """A universe membership table loaded from CSV. Provides:

    - `as_of(date)`: returns the live set of tickers tradable on `date`.
    - `is_delisted(symbol, date)`: True if `symbol` delisted on/before `date`.
    """

    def __init__(self, df: pd.DataFrame) -> None:
        if "symbol" not in df.columns:
            raise ValueError("universe CSV must contain 'symbol' column")
        df = df.copy()
        df["symbol"] = df["symbol"].astype(str).str.upper()
        for c in ("list_date", "delist_date"):
            values = df[c] if c in df.columns else pd.Series(pd.NaT, index=df.index)
            df[c] = pd.to_datetime(values, utc=True, errors="coerce")
        if "delist_reason" in df.columns:
            df["delist_reason"] = df["delist_reason"].astype(str)
        else:
            df["delist_reason"] = ""
        self._df = df

    @classmethod
    def from_csv(cls, path: str | Path) -> Universe:
        return cls(pd.read_csv(path))

    @staticmethod
    def _utc_date(date: str | pd.Timestamp) -> pd.Timestamp:
        d = pd.Timestamp(date)
        return d.tz_localize("UTC") if d.tz is None else d

    def _is_member(self, symbol: str, date: str | pd.Timestamp) -> bool:
        """Return whether a known symbol was listed and not yet delisted."""
        d = self._utc_date(date)
        rows = self._df[self._df["symbol"] == symbol.upper()]
        if rows.empty:
            return False
        member = (rows["list_date"].isna() | (rows["list_date"] <= d)) & (
            rows["delist_date"].isna() | (rows["delist_date"] > d)
        )
        return bool(member.any())

    def as_of(self, date: str | pd.Timestamp) -> list[str]:
        return sorted(sym for sym in self._df["symbol"].unique() if self._is_member(sym, date))

    def is_delisted(self, symbol: str, date: str | pd.Timestamp) -> bool:
        d = self._utc_date(date)
        rows = self._df[self._df["symbol"].str.upper() == symbol.upper()]
        if rows.empty:
            return False
        dlist = rows["delist_date"].iloc[0]
        return bool(pd.notna(dlist) and dlist <= d)

    def filter_panel(
        self, panel: pd.DataFrame, symbol_col: str = "symbol", date_col: str = "timestamp"
    ) -> pd.DataFrame:
        """Keep only rows for symbols active on each row's date."""
        if panel.empty:
            return panel
        out = panel.copy()
        out[symbol_col] = out[symbol_col].astype(str).str.upper()
        out[date_col] = pd.to_datetime(out[date_col], utc=True)
        keep_mask = []
        for sym, ts in zip(out[symbol_col], out[date_col], strict=False):
            keep_mask.append(self._is_member(sym, ts))
        return out.loc[keep_mask].reset_index(drop=True)


def write_spx_sample(universe_dir: Path, tickers: list[str]) -> Path:
    """Write a minimal S&P 500-style sample universe file.

    v1 uses a small hand-curated sample (no free survivorship-free dataset).
    Each ticker is marked tradable from `2008-01-01` onward (list_date set,
    delist_date empty). Real historical membership is the documented upgrade path.
    """
    universe_dir.mkdir(parents=True, exist_ok=True)
    path = universe_dir / "spx_sample.csv"
    pd.DataFrame(
        [
            {"symbol": t.upper(), "list_date": "2008-01-01", "delist_date": "", "delist_reason": ""}
            for t in tickers
        ]
    ).to_csv(path, index=False)
    return path
