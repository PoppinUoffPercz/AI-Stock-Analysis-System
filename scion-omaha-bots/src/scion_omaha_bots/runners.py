"""Stable runner functions backed by the existing bot entrypoints."""

from __future__ import annotations

from collections.abc import Sequence

from ._legacy import load_entrypoint as _load_legacy_entrypoint


def _result_code(result: object) -> int:
    return result if isinstance(result, int) else 0


def scion_main(argv: Sequence[str] | None = None) -> int:
    module = _load_legacy_entrypoint("main.py", "scion_omaha_bots._legacy_scion_main")
    return _result_code(module.main(argv))


def omaha_main(argv: Sequence[str] | None = None) -> int:
    module = _load_legacy_entrypoint(
        "buffett_main.py", "scion_omaha_bots._legacy_omaha_main"
    )
    return _result_code(module.main(argv))
