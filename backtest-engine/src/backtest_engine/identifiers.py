"""Validation for external identifiers used as filesystem path components."""

from __future__ import annotations

import re

_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def validate_identifier(value: str, *, field_name: str = "identifier") -> str:
    """Return *value* when it is safe to use as one path component."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a nonempty safe identifier")
    if value in {".", ".."} or not _SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field_name} must be a single safe path component")
    return value
