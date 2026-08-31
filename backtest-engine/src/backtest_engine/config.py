"""Pydantic settings for shared data paths and yfinance behavior."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    """Engine-wide settings. Loaded once at startup; passed where needed."""

    # Paths (resolved relative to project root at runtime by the CLI)
    data_dir: Path = Field(default_factory=lambda: Path("data"))
    universe_dir: Path = Field(default_factory=lambda: Path("data/universe"))
    outputs_dir: Path = Field(default_factory=lambda: Path("outputs"))

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
