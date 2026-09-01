"""Temporary loader for the legacy flat bot modules during migration."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

LEGACY_ROOT = Path(__file__).resolve().parents[2]


def load_entrypoint(filename: str, module_name: str) -> ModuleType:
    """Load one legacy entrypoint while keeping its local imports working."""
    legacy_root = str(LEGACY_ROOT)
    if legacy_root not in sys.path:
        sys.path.insert(0, legacy_root)

    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached

    path = LEGACY_ROOT / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load legacy bot entrypoint: {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module
