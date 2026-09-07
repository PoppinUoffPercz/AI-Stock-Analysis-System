"""Date-only bounds shared by persisted-data sources and storage."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


def utc_day(value: str) -> pd.Timestamp:
    """Parse a required ISO calendar day at its UTC midnight boundary."""
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid date {value!r}; expected YYYY-MM-DD") from exc
    return pd.Timestamp(parsed, tz="UTC")


def day_after(value: str) -> str:
    """Return the ISO calendar day following an inclusive end date."""
    try:
        return (date.fromisoformat(value) + timedelta(days=1)).isoformat()
    except ValueError as exc:
        raise ValueError(f"invalid date {value!r}; expected YYYY-MM-DD") from exc
