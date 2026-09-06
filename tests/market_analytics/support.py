from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

T0 = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)


def ny_utc(hour: int, minute: int, *, day: int = 2) -> datetime:
    return datetime(
        2026, 1, day, hour, minute, tzinfo=ZoneInfo("America/New_York")
    ).astimezone(UTC)


def raw_option(**overrides):
    from stock_analysis.market_analytics.models import CallPut, OptionContractInput

    values = {
        "underlying": "AAA",
        "expiration": date(2026, 1, 16),
        "strike": 100.0,
        "call_put": CallPut.CALL,
        "contract_multiplier": 100,
        "bid": 1.0,
        "ask": 1.1,
        "last": 1.05,
        "volume": 10.0,
        "open_interest": 100.0,
        "iv": 0.20,
        "delta": 0.50,
        "gamma": 0.02,
        "theta": -0.01,
        "vega": 0.10,
        "quote_timestamp": T0,
        "trade_timestamp": T0,
        "oi_as_of": T0,
        "greeks_source": "fixture",
        "iv_source": "fixture",
        "bid_size": None,
        "ask_size": None,
        "adjusted": False,
        "adjustment_reason": None,
    }
    return OptionContractInput(**(values | overrides))
