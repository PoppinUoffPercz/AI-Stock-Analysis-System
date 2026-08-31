"""Source adapters: yfinance + Stooq. Each adapter pulls OHLCV into the
canonical raw schema and is throttled/retried per Settings.

All adapters return a frame with columns:
    timestamp (tz-aware UTC), open, high, low, close, volume,
    adj_open, adj_high, adj_low, adj_close, dividend, split_ratio
plus any transforms from the source toward our clean schema. The cleaner
normalizes/validates downstream.

Adapters are deliberately thin — they wrap a single library and return DataFrames.
Anything fancy (cross-source dedupe, gap-fill) happens in `ingest.py`.
"""

from __future__ import annotations

import csv
import io
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd
import requests

from backtest_engine.config import Settings

SOURCE_YFINANCE: Final[str] = "yfinance"
SOURCE_STOOQ: Final[str] = "stooq"
SOURCE_CSV: Final[str] = "csv"

RAW_FILE_COLUMNS: Final[tuple[str, ...]] = (
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
)


class Source(ABC):
    """Abstract market-data source."""

    name: str

    @abstractmethod
    def fetch(self, symbol: str, start: str | None, end: str | None) -> pd.DataFrame: ...


class CsvSource(Source):
    """Offline local CSV adapter for common Date/Open/High/Low/Close/Volume files."""

    name = SOURCE_CSV

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def fetch(self, symbol: str, start: str | None, end: str | None) -> pd.DataFrame:
        if not self.path.is_file():
            raise ValueError(f"CSV input does not exist: {self.path}")
        try:
            frame = pd.read_csv(self.path)
        except (OSError, pd.errors.ParserError) as exc:
            raise ValueError(f"could not read CSV input {self.path}: {exc}") from exc
        frame = frame.rename(columns={column: column.strip().lower() for column in frame.columns})
        if "date" in frame.columns and "timestamp" not in frame.columns:
            frame = frame.rename(columns={"date": "timestamp"})
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"missing required columns: {missing}")
        try:
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid timestamp values in CSV input") from exc
        for column in required - {"timestamp"}:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if start:
            frame = frame[frame["timestamp"] >= pd.Timestamp(start, tz="UTC")]
        if end:
            frame = frame[frame["timestamp"] <= pd.Timestamp(end, tz="UTC")]
        return frame


# ---------------------------------------------------------------------------
# yfinance
# ---------------------------------------------------------------------------


class YFinanceSource(Source):
    """yfinance adapter. Uses back-adjusted prices; persists corp-action facts.

    yfinance auto-adjusts splits + dividends when auto_adjust=False returns raw;
    we explicitly request auto_adjust=False so adj_* are available alongside raw.
    """

    name = SOURCE_YFINANCE

    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or Settings()
        # Importing yfinance eagerly at construction lets the test gate skip
        # by raising ImportError in __init__ instead of mid-fetch.
        import yfinance as yf  # noqa: PLC0415

        self._yf = yf

    @staticmethod
    def _stooq_to_clean(symbol, df) -> pd.DataFrame:
        # Helper kept for symmetry; Stooq uses its own class.
        raise NotImplementedError

    def fetch(self, symbol: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        """Fetch OHLCV for `symbol`. Throttles + retries per Settings."""
        last_err: Exception | None = None
        for _ in range(max(1, self.s.yf_retries)):
            try:
                # auto_adjust=False so we get both raw OHLV and adj OHLC in one shot
                t = self._yf.Ticker(symbol)
                df = t.history(start=start, end=end, auto_adjust=False, actions=True)
                if df is None or df.empty:
                    return pd.DataFrame(columns=RAW_FILE_COLUMNS)
                return self._normalize(df)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(self.s.yf_sleep_sec)
        raise RuntimeError(f"yfinance fetch failed for {symbol}: {last_err}") from last_err

    @staticmethod
    def _normalize(df: pd.DataFrame) -> pd.DataFrame:
        # yfinance index is tz-aware NYSE time; convert to UTC.
        df = df.copy()
        idx = pd.DatetimeIndex(df.index)
        if idx.tz is not None:
            df.index = idx.tz_convert("UTC")
        else:
            df.index = idx.tz_localize("UTC")
        df.index.name = "timestamp"
        df = df.reset_index()

        # Renaming collisions: yfinance uses 'Stock Splits' / 'Dividends' / 'Open' etc.
        rename = {
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "source_adj_close",
            "Volume": "volume",
            "Date": "timestamp",
            "Dividends": "dividend",
            "Stock Splits": "split_ratio",
        }
        df = df.rename(columns=rename)

        if "split_ratio" not in df.columns:
            df["split_ratio"] = 1.0
        if "dividend" not in df.columns:
            df["dividend"] = 0.0
        if "volume" not in df.columns:
            df["volume"] = 0.0

        df["split_ratio"] = pd.to_numeric(df["split_ratio"], errors="coerce").fillna(1.0)
        df.loc[df["split_ratio"] == 0, "split_ratio"] = 1.0
        df["dividend"] = pd.to_numeric(df["dividend"], errors="coerce").fillna(0.0)

        # yfinance's adjusted close already contains the correct backward
        # corporate-action factor for each row. Use it for every OHLC field.
        close = pd.to_numeric(df["close"], errors="coerce")
        source_adj_close = (
            pd.to_numeric(df["source_adj_close"], errors="coerce")
            if "source_adj_close" in df.columns
            else pd.Series(np.nan, index=df.index)
        )
        adj_factor = source_adj_close / close
        valid_factor = (
            source_adj_close.notna()
            & close.notna()
            & close.ne(0)
            & np.isfinite(source_adj_close)
            & np.isfinite(adj_factor)
            & adj_factor.gt(0)
        )

        # Fallback for missing/invalid adjusted-close values. An action on row
        # T adjusts rows strictly before T, so walk actions backward in time.
        fallback = pd.Series(1.0, index=df.index, dtype="float64")
        future_factor = 1.0
        for i in range(len(df) - 1, -1, -1):
            fallback.iloc[i] = future_factor
            ratio = float(df["split_ratio"].iloc[i])
            div = float(df["dividend"].iloc[i])
            close_i = float(close.iloc[i])
            if np.isfinite(ratio) and ratio > 0:
                future_factor /= ratio
            if np.isfinite(div) and 0 < div < close_i:
                future_factor *= (close_i - div) / close_i

        adj_factor = adj_factor.where(valid_factor, fallback)
        adj_factor = adj_factor.where(np.isfinite(adj_factor) & adj_factor.gt(0), 1.0)
        for raw in ("open", "high", "low", "close"):
            df[f"adj_{raw}"] = pd.to_numeric(df[raw], errors="coerce") * adj_factor

        cols = [c for c in RAW_FILE_COLUMNS if c in df.columns]
        out = df[cols]
        # Fill any remaining optional cols
        for c in RAW_FILE_COLUMNS:
            if c not in out.columns:
                out[c] = 0.0
        return out[list(RAW_FILE_COLUMNS)]


# ---------------------------------------------------------------------------
# Stooq (CSV download, no SDK)
# ---------------------------------------------------------------------------


class StooqSource(Source):
    """Stooq historical CSV downloader. Bulk EOD; good for cross-checking yfinance.

    URL: https://stooq.com/q/d/l/?s={symbol}&i=d
    Returns OHLCV only (no corp-action information).
    """

    name = SOURCE_STOOQ
    BASE_URL: Final[str] = "https://stooq.com/q/d/l/"
    SYMBOL_MAP = {
        # US equities typically use '.us' suffix on Stooq
        "^sp500": "^spx",
    }

    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or Settings()
        self._sess = requests.Session()
        self._sess.headers.update({"User-Agent": "backtest-engine/0.1"})

    def fetch(self, symbol: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        stooq_sym = self.SYMBOL_MAP.get(symbol.lower(), symbol.lower())
        if not stooq_sym.endswith(".us") and stooq_sym.isalpha() and not stooq_sym.startswith("^"):
            # US equity tickers conventionally get '.us'
            stooq_sym = f"{stooq_sym}.us"
        last_err: Exception | None = None
        for _ in range(max(1, self.s.yf_retries)):
            try:
                r = self._sess.get(
                    self.BASE_URL,
                    params={"s": stooq_sym, "i": "d", **(self._date_params(start, end))},
                    timeout=30,
                )
                r.raise_for_status()
                df = self._parse_csv(r.text)
                if df.empty:
                    time.sleep(0.5)
                    continue
                return df
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(self.s.yf_sleep_sec)
        raise RuntimeError(
            f"stooq fetch failed for {symbol} ({stooq_sym}): {last_err}"
        ) from last_err

    @staticmethod
    def _date_params(start: str | None, end: str | None) -> dict[str, str]:
        d: dict[str, str] = {}
        if start:
            d["d1"] = pd.Timestamp(start).strftime("%Y%m%d")
        if end:
            d["d2"] = pd.Timestamp(end).strftime("%Y%m%d")
        return d

    @staticmethod
    def _parse_csv(text: str) -> pd.DataFrame:
        # Stooq CSV: Date,Open,High,Low,Close,Volume  (no corp actions)
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            return pd.DataFrame(columns=RAW_FILE_COLUMNS)
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["Date"], utc=True)
        for c in ("Open", "High", "Low", "Close", "Volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        out = pd.DataFrame()
        out["timestamp"] = df["timestamp"]
        out["open"] = df["Open"].astype("float64")
        out["high"] = df["High"].astype("float64")
        out["low"] = df["Low"].astype("float64")
        out["close"] = df["Close"].astype("float64")
        out["volume"] = df["Volume"].astype("float64")
        # No corp-action info; adj = raw
        for c in ("adj_open", "adj_high", "adj_low", "adj_close"):
            out[c] = out[c.replace("adj_", "")]
        out["dividend"] = 0.0
        out["split_ratio"] = 1.0
        return out[list(RAW_FILE_COLUMNS)]
