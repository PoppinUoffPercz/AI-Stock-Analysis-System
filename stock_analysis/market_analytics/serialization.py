"""JSON-safe round trips for analytics dataclasses and snapshots."""

from __future__ import annotations

import importlib
import math
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return {
            "__enum__": f"{value.__class__.__module__}:{value.__class__.__qualname__}",
            "value": value.value,
        }
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite floats are not JSON-safe")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite decimals are not JSON-safe")
        return {"__decimal__": str(value)}
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, timedelta):
        return {"__timedelta__": value.total_seconds()}
    if isinstance(value, date):
        return {"__date__": value.isoformat()}
    if is_dataclass(value):
        return {
            "__type__": f"{value.__class__.__module__}:{value.__class__.__qualname__}",
            "fields": {
                field.name: to_jsonable(getattr(value, field.name))
                for field in fields(value)
            },
        }
    if isinstance(value, dict):
        return {
            "__mapping__": [
                [to_jsonable(key), to_jsonable(item)] for key, item in value.items()
            ]
        }
    if isinstance(value, tuple):
        return {"__tuple__": [to_jsonable(item) for item in value]}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, set):
        return {"__set__": [to_jsonable(item) for item in value]}
    raise TypeError(f"unsupported JSON conversion type: {type(value).__name__}")


def from_jsonable(value: Any, expected_type: type[Any] | None = None) -> Any:
    if isinstance(value, list):
        return [from_jsonable(item) for item in value]
    if not isinstance(value, dict):
        if expected_type is not None and isinstance(expected_type, type):
            try:
                if issubclass(expected_type, Enum):
                    return expected_type(value)
            except TypeError:
                pass
        return value
    if "__datetime__" in value:
        return datetime.fromisoformat(value["__datetime__"])
    if "__date__" in value:
        return date.fromisoformat(value["__date__"])
    if "__timedelta__" in value:
        return timedelta(seconds=value["__timedelta__"])
    if "__decimal__" in value:
        return Decimal(value["__decimal__"])
    if "__enum__" in value:
        enum_type = _resolve_type(value["__enum__"])
        return enum_type(value["value"])
    if "__tuple__" in value:
        return tuple(from_jsonable(item) for item in value["__tuple__"])
    if "__set__" in value:
        return {from_jsonable(item) for item in value["__set__"]}
    if "__mapping__" in value:
        return {
            from_jsonable(item[0]): from_jsonable(item[1])
            for item in value["__mapping__"]
        }
    if "__type__" in value:
        data_type = _resolve_type(value["__type__"])
        decoded_fields = {
            name: from_jsonable(item) for name, item in value["fields"].items()
        }
        return data_type(**decoded_fields)
    return {key: from_jsonable(item) for key, item in value.items()}


def _resolve_type(path: str) -> type[Any]:
    module_name, separator, qualified_name = path.partition(":")
    if not separator:
        raise ValueError(f"invalid serialized type path: {path}")
    allowed_market_modules = {
        "config",
        "asof",
        "credit",
        "dom",
        "features",
        "levels",
        "models",
        "options",
        "order_flow",
        "pipeline",
        "positioning",
        "profiles",
        "providers",
        "sessions",
        "streaming",
        "volatility",
        "vwap",
    }
    market_type = module_name.startswith("stock_analysis.market_analytics.") and (
        module_name.rsplit(".", 1)[-1] in allowed_market_modules
    )
    intelligence_type = module_name == "stock_analysis.intelligence.models"
    paper_type = module_name == "stock_analysis.paper"
    if (
        not market_type and not intelligence_type and not paper_type
    ) or "." in qualified_name:
        raise ValueError(f"unsupported serialized type: {path}")
    resolved: Any = importlib.import_module(module_name)
    for name in qualified_name.split("."):
        resolved = getattr(resolved, name)
    if not isinstance(resolved, type):
        raise TypeError(f"serialized path does not resolve to a type: {path}")
    if not (is_dataclass(resolved) or issubclass(resolved, Enum)):
        raise ValueError(f"unsupported serialized type: {path}")
    return resolved
