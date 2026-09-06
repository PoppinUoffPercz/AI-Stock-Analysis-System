"""Shared persisted-title state for the Scion and Omaha news engines."""

from __future__ import annotations

import json
from pathlib import Path

from stock_analysis.persistence import atomic_write_json


def load_seen_titles(path: str | Path) -> dict[str, set[str]]:
    target = Path(path)
    if not target.exists():
        return {}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"news state {target}: invalid JSON at line {exc.lineno}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"news state {target}: expected an object keyed by symbol")
    seen: dict[str, set[str]] = {}
    for symbol, titles in raw.items():
        if not isinstance(symbol, str) or not isinstance(titles, list) or not all(
            isinstance(title, str) for title in titles
        ):
            raise ValueError(f"news state {target}: invalid titles for {symbol!r}")
        seen[symbol] = set(titles)
    return seen


def save_seen_titles(path: str | Path, seen_titles: dict[str, set[str]]) -> None:
    atomic_write_json(path, {symbol: sorted(titles) for symbol, titles in seen_titles.items()})
