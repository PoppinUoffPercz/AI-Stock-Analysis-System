"""Pydantic settings for shared data paths and yfinance behavior."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


def _env_path(name: str, fallback: str) -> Path:
    return Path(os.environ.get(name, fallback))


def _data_root() -> Path:
    return _env_path("STOCK_ANALYSIS_DATA_ROOT", "data")


def _universe_root() -> Path:
    return _data_root() / "universe"


def _outputs_root() -> Path:
    return _env_path("STOCK_ANALYSIS_OUTPUTS_ROOT", "outputs")


class Settings(BaseModel):
    """Engine-wide settings. Loaded once at startup; passed where needed."""

    # Paths (resolved relative to project root at runtime by the CLI)
    data_dir: Path = Field(default_factory=_data_root)
    universe_dir: Path = Field(default_factory=_universe_root)
    outputs_dir: Path = Field(default_factory=_outputs_root)

    # Data fetcher
    yf_sleep_sec: float = 1.5  # yfinance rate-limit throttle
    yf_retries: int = 3

    model_config = {"frozen": False, "extra": "forbid"}


def resolve_settings(**overrides: object) -> Settings:
    """Build settings with optional overrides; absolute-izes paths against CWD."""
    s = Settings(**overrides)  # type: ignore[arg-type]
    # Normalize to absolute so callers don't have to track CWD
    for name in ("data_dir", "universe_dir", "outputs_dir"):
        p = getattr(s, name)
        if not p.is_absolute():
            setattr(s, name, Path.cwd() / p)
    return s
