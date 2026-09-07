"""Portable validation for one persisted identifier."""

import re

_IDENTIFIER = re.compile(r"[A-Za-z0-9^][A-Za-z0-9._^=-]*")
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def validate_identifier(value: str, *, field_name: str = "identifier") -> str:
    if (
        not isinstance(value, str)
        or not _IDENTIFIER.fullmatch(value)
        or value.endswith(".")
        or value.split(".", 1)[0].upper() in _RESERVED
    ):
        raise ValueError(
            f"invalid identifier: {field_name} must be a single safe path component"
        )
    return value
