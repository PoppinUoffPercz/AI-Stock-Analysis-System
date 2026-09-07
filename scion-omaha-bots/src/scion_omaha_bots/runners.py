"""Stable runner functions backed by the existing bot entrypoints."""

from __future__ import annotations

from collections.abc import Sequence
from importlib import import_module


def _result_code(result: object) -> int:
    return result if isinstance(result, int) else 0


def scion_main(argv: Sequence[str] | None = None) -> int:
    module = import_module("scion_omaha_bots.main")
    return _result_code(module.main(argv))


def omaha_main(argv: Sequence[str] | None = None) -> int:
    module = import_module("scion_omaha_bots.buffett_main")
    return _result_code(module.main(argv))
