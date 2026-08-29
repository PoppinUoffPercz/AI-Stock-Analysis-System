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
from typing import Final

import pandas as pd
import requests

from backtest_engine.config import Settings

SOURCE_YFINANCE: Final[str] = "yfinance"
SOURCE_STOOQ: Final[str] = "stooq"

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
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            df.index = idx.tz_convert("UTC")  # type: ignore[attr-defined]
        else:
            df.index = idx.tz_localize("UTC")  # type: ignore[attr-defined]
        df.index.name = "timestamp"
        df = df.reset_index()

        # Renaming collisions: yfinance uses 'Stock Splits' / 'Dividends' / 'Open' etc.
        rename = {
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
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

        # Compute back-adjusted OHLC via cumulative adjustment factor.
        # For a position-holding backtest on US daily equities, we default to the
        # back-adjusted series for signals to prevent future corp-action look-ahead.
        # Build cumulative adj factor using split_ratio and dividend yield.
        ratio = df["split_ratio"].astype(float)
        adj_factor = (1.0 / ratio).cumprod().shift(1, fill_value=1.0)

        # dividend back-adjustment (multiplicative close): r_t = 1 - div/close_t-1
        # For simplicity and predictability we use additive dividend on close.
        # This matches yfinance's default Adjusted Close convention (close adjusted
        # for both splits and dividends).
        close_for_div = df["close"].where(df["close"] > 0, pd.NA)
        # dividend-divisor at time t applies to all bars at and before t.
        div_ratio = (df["close"] - df["dividend"]) / close_for_div
        div_ratio = div_ratio.fillna(1.0).cumprod()
        adj_factor = adj_factor * div_ratio

        df["adj_open"] = df["open"] * adj_factor
        df["adj_high"] = df["high"] * adj_factor
        df["adj_low"] = df["low"] * adj_factor
        df["adj_close"] = df["close"] * adj_factor

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
            df[c] = pd.to_numeric(df.get(c), errors="coerce")  # type: ignore[call-overload]
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
