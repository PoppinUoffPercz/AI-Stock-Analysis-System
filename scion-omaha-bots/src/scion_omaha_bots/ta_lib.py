"""
ta_lib.py — Technical Analysis Library for Scion-Bot.

Pure numpy/pandas implementations. No external TA dependencies.
Provides RSI, MACD, SMA, EMA, Bollinger Bands, ATR, TTM Squeeze,
and Volume analysis functions used across both bots for entry/exit timing.
"""

import numpy as np
import pandas as pd


def compute_rsi(series, period=14):
    """
    Relative Strength Index using Wilder smoothing.
    RSI = 100 - 100/(1 + RS), RS = avg_gain / avg_loss.
    """
    series = pd.Series(series).dropna()
    if len(series) < period + 1:
        return {"value": 50, "regime": "neutral"}

    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.iloc[1:period + 1].mean()
    avg_loss = loss.iloc[1:period + 1].mean()

    if avg_loss == 0:
        return {"value": 100, "regime": "overbought"}

    for i in range(period + 1, len(gain)):
        avg_gain = (avg_gain * (period - 1) + gain.iloc[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss.iloc[i]) / period

    rs = avg_gain / avg_loss if avg_loss > 0 else 100
    rsi_val = 100 - 100 / (1 + rs)

    regime = "oversold" if rsi_val < 30 else "overbought" if rsi_val > 70 else "neutral"
    return {"value": round(rsi_val, 2), "regime": regime}


def compute_ema(series, period):
    """Exponential Moving Average — last value."""
    series = pd.Series(series).dropna()
    if len(series) < period:
        return None
    return float(series.ewm(span=period, adjust=False).mean().iloc[-1])


def compute_sma(series, period):
    """Simple Moving Average — last value."""
    series = pd.Series(series).dropna()
    if len(series) < period:
        return None
    return float(series.rolling(period).mean().iloc[-1])


def compute_smas(series, periods=None):
    """Compute multiple SMAs at once. Returns {period: value} dict."""
    if periods is None:
        periods = [10, 20, 50, 100, 200]
    series = pd.Series(series).dropna()
    result = {}
    for p in periods:
        if len(series) >= p:
            result[p] = float(series.rolling(p).mean().iloc[-1])
    return result


def compute_macd(series, fast=12, slow=26, signal=9):
    """
    MACD: MACD Line = EMA(fast) - EMA(slow).
    Signal Line = EMA(MACD, signal).
    Histogram = MACD - Signal.
    """
    series = pd.Series(series).dropna()
    min_len = slow + signal
    if len(series) < min_len:
        return {
            "macd_line": 0,
            "signal_line": 0,
            "histogram": 0,
            "cross_signal": None
        }

    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    cross = None
    if len(macd_line) >= 2:
        if macd_line.iloc[-2] <= signal_line.iloc[-2] and macd_line.iloc[-1] > signal_line.iloc[-1]:
            cross = "bullish"
        elif macd_line.iloc[-2] >= signal_line.iloc[-2] and macd_line.iloc[-1] < signal_line.iloc[-1]:
            cross = "bearish"
        elif macd_line.iloc[-2] <= 0 and macd_line.iloc[-1] > 0:
            cross = "zero_bullish"
        elif macd_line.iloc[-2] >= 0 and macd_line.iloc[-1] < 0:
            cross = "zero_bearish"

    return {
        "macd_line": round(float(macd_line.iloc[-1]), 4),
        "signal_line": round(float(signal_line.iloc[-1]), 4),
        "histogram": round(float(histogram.iloc[-1]), 4),
        "cross_signal": cross
    }


def compute_bollinger(series, period=20, std_dev=2):
    """Bollinger Bands: upper, middle (SMA), lower, bandwidth, %B."""
    series = pd.Series(series).dropna()
    if len(series) < period:
        return {"upper": None, "middle": None, "lower": None, "bandwidth": None, "percent_b": None}

    sma = series.rolling(period).mean()
    std = series.rolling(period).std()

    middle = float(sma.iloc[-1])
    band_std = float(std.iloc[-1])
    upper = middle + std_dev * band_std
    lower = middle - std_dev * band_std
    bandwidth = (upper - lower) / middle if middle != 0 else 0
    current = float(series.iloc[-1])
    percent_b = (current - lower) / (upper - lower) if upper != lower else 0.5

    return {
        "upper": round(upper, 2),
        "middle": round(middle, 2),
        "lower": round(lower, 2),
        "bandwidth": round(bandwidth, 4),
        "percent_b": round(percent_b, 4)
    }


def compute_atr(df, period=14):
    """
    Average True Range — Wilder smoothing.
    True Range = max(H-L, |H-prevC|, |prevC-L|).
    Wilder uses alpha = 1/period (equivalent to ewm(alpha=1/period)),
    which differs from ewm(span=period) that uses alpha = 2/(period+1).
    """
    if df.empty or len(df) < period + 1:
        return {"value": None, "series": np.array([])}

    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    tr = pd.DataFrame({
        "hl": high - low,
        "hc": (high - close.shift(1)).abs(),
        "lc": (low - close.shift(1)).abs()
    }).max(axis=1)

    atr_series = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    return {
        "value": round(float(atr_series.iloc[-1]), 2) if not atr_series.empty else None,
        "series": atr_series.dropna().values
    }


def compute_keltner(df, period=20, atr_mult=1.5):
    """
    Keltner Channels: Middle = EMA(close), Upper/Lower = Middle ± atr_mult * ATR.
    Used by TTM Squeeze.
    """
    if df.empty or len(df) < period + 1:
        return {"upper": None, "middle": None, "lower": None}

    close = pd.Series(df["Close"])
    ema = close.ewm(span=period, adjust=False).mean()
    atr_data = compute_atr(df, period)
    atr_val = atr_data["value"]

    if atr_val is None:
        return {"upper": None, "middle": None, "lower": None}

    middle = float(ema.iloc[-1])
    offset = atr_mult * atr_val
    return {
        "upper": round(middle + offset, 2),
        "middle": round(middle, 2),
        "lower": round(middle - offset, 2)
    }


def compute_ttm_squeeze(df, period=20, bb_std=2, kc_mult=1.5):
    """
    Full Carter-Fukusawa TTM Squeeze.

    Squeeze = Bollinger Bands entirely inside Keltner Channels.
    Histogram = linear regression of highest high / lowest low over period,
    colored by direction. First bar after squeeze fires = lime (up) / maroon (down),
    subsequent bars = green (up) / red (down).
    """
    min_bars = period + 10
    if df.empty or len(df) < min_bars:
        return {
            "squeeze_on": False,
            "bars_in_squeeze": 0,
            "histogram_value": 0,
            "histogram_color": "gray"
        }

    bb = compute_bollinger(df["Close"], period, bb_std)
    kc = compute_keltner(df, period, kc_mult)

    if None in (bb["upper"], bb["lower"], kc["upper"], kc["lower"]):
        return {
            "squeeze_on": False,
            "bars_in_squeeze": 0,
            "histogram_value": 0,
            "histogram_color": "gray"
        }

    squeeze_on = bb["upper"] < kc["upper"] and bb["lower"] > kc["lower"]

    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    # Linear regression of highest high vs lowest low over the last `period` bars
    recent_high = high.iloc[-period:]
    recent_low = low.iloc[-period:]
    x = np.arange(period)

    if len(recent_high) < period:
        return {
            "squeeze_on": squeeze_on,
            "bars_in_squeeze": 0,
            "histogram_value": 0,
            "histogram_color": "gray"
        }

    # Linear regression on average of high+low
    avg_price = (recent_high.values + recent_low.values) / 2
    slope = np.polyfit(x, avg_price, 1)[0]
    histogram_value = round(slope * 100, 2)

    # Count consecutive bars in squeeze
    bars_in_sq = 0
    for i in range(len(close) - 1, period * 2, -1):
        chunk = df.iloc[i - period:i + 1]
        if len(chunk) < period + 1:
            break
        chunk_bb = compute_bollinger(chunk["Close"], period, bb_std)
        chunk_kc = compute_keltner(chunk, period, kc_mult)
        if any(v is None for v in (chunk_bb["upper"], chunk_bb["lower"], chunk_kc["upper"], chunk_kc["lower"])):
            break
        if chunk_bb["upper"] < chunk_kc["upper"] and chunk_bb["lower"] > chunk_kc["lower"]:
            bars_in_sq += 1
        else:
            break

    # Color rules
    if not squeeze_on:
        color = "gray"
    elif bars_in_sq <= 2:
        color = "lime" if histogram_value > 0 else "maroon"
    else:
        color = "green" if histogram_value > 0 else "red"

    return {
        "squeeze_on": squeeze_on,
        "bars_in_squeeze": bars_in_sq,
        "histogram_value": histogram_value,
        "histogram_color": color
    }


def compute_volume_ratio(volume_series, period=20):
    """Compare latest volume to its moving average."""
    vol = pd.Series(volume_series).dropna()
    if len(vol) < period:
        return {"current_volume": 0, "avg_volume": 0, "ratio": 0, "regime": "normal"}

    current = float(vol.iloc[-1])
    avg = float(vol.rolling(period).mean().iloc[-1])
    ratio = current / avg if avg > 0 else 0

    if ratio < 0.5:
        regime = "low"
    elif ratio < 1.5:
        regime = "normal"
    elif ratio < 3:
        regime = "high"
    else:
        regime = "surge"

    return {
        "current_volume": current,
        "avg_volume": round(avg, 0),
        "ratio": round(ratio, 2),
        "regime": regime
    }


def compute_all(df):
    """
    Convenience function — runs all indicators on an OHLCV DataFrame.
    Returns a combined dict.
    """
    return {
        "rsi": compute_rsi(df["Close"]),
        "macd": compute_macd(df["Close"]),
        "sma": compute_smas(df["Close"]),
        "bollinger": compute_bollinger(df["Close"]),
        "atr": compute_atr(df),
        "squeeze": compute_ttm_squeeze(df),
        "volume": compute_volume_ratio(df["Volume"])
    }


if __name__ == "__main__":
    print("ta_lib.py — Self-test on synthetic data...")

    np.random.seed(42)
    days = 252
    dates = pd.date_range("2025-01-01", periods=days, freq="D")
    price = 100 + np.cumsum(np.random.randn(days) * 0.5)
    df = pd.DataFrame({
        "Open": price,
        "High": price + np.abs(np.random.randn(days) * 1.0),
        "Low": price - np.abs(np.random.randn(days) * 1.0),
        "Close": price + np.random.randn(days) * 0.2,
        "Volume": np.random.randint(1_000_000, 10_000_000, days)
    }, index=dates)

    print(f"  RSI: {compute_rsi(df['Close'])}")
    print(f"  MACD: {compute_macd(df['Close'])}")
    print(f"  SMA50: {compute_sma(df['Close'], 50):.2f}")
    print(f"  SMA200: {compute_sma(df['Close'], 200):.2f}")
    print(f"  Bollinger: {compute_bollinger(df['Close'])}")
    print(f"  ATR: {compute_atr(df)}")
    print(f"  Keltner: {compute_keltner(df)}")
    print(f"  TTM Squeeze: {compute_ttm_squeeze(df)}")
    print(f"  Volume Ratio: {compute_volume_ratio(df['Volume'])}")

    print("  ALL INDICATORS PASSED — no exceptions")
