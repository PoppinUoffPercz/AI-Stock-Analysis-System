"""Compatibility loader name backed by ordinary package imports."""
from importlib import import_module
from types import ModuleType


def load_entrypoint(filename: str, module_name: str) -> ModuleType:
    """Keep the runner seam without loading files or modifying sys.path."""
    entrypoints = {"main.py": "main", "buffett_main.py": "buffett_main"}
    return import_module(f"scion_omaha_bots.{entrypoints[filename]}")
