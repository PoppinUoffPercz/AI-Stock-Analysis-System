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
        if df["symbol"].isna().any() or df["symbol"].astype(str).str.strip().eq("").any():
            raise ValueError("universe CSV contains an empty symbol")
        df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
        for c in ("list_date", "delist_date"):
            values = df[c] if c in df.columns else pd.Series(pd.NaT, index=df.index)
            parsed = pd.to_datetime(values, utc=True, errors="coerce")
            invalid = values.notna() & values.astype(str).str.strip().ne("") & parsed.isna()
            if invalid.any():
                raise ValueError(f"universe CSV contains invalid {c}")
            df[c] = parsed
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
        if symbol_col in out.columns and date_col in out.columns:
            symbols = out[symbol_col].astype(str).str.upper()
            timestamps = pd.to_datetime(out[date_col], utc=True)
            out[symbol_col] = symbols
            out[date_col] = timestamps
        elif symbol_col not in out.columns and date_col not in out.columns:
            symbol = out.attrs.get("symbol")
            if symbol is None:
                raise ValueError(
                    f"panel must contain {symbol_col!r}/{date_col!r} columns or attrs['symbol'] "
                    "with a datetime index"
                )
            symbols = pd.Series(str(symbol).upper(), index=out.index)
            timestamps = pd.Series(pd.to_datetime(out.index, utc=True), index=out.index)
        else:
            raise ValueError(f"panel must contain both {symbol_col!r} and {date_col!r} columns")

        rows = pd.DataFrame(
            {
                "_row": range(len(out)),
                "symbol": symbols.to_numpy(),
                "timestamp": timestamps.to_numpy(),
            }
        )
        joined = rows.merge(
            self._df[["symbol", "list_date", "delist_date"]].assign(_known=True),
            on="symbol",
            how="left",
            sort=False,
        )
        active = joined["_known"].fillna(False).astype(bool)
        active &= joined["list_date"].isna() | (joined["list_date"] <= joined["timestamp"])
        active &= joined["delist_date"].isna() | (joined["delist_date"] > joined["timestamp"])
        keep = (
            active.groupby(joined["_row"], sort=False)
            .any()
            .reindex(range(len(out)), fill_value=False)
        )
        return out.iloc[keep.to_numpy()]


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
