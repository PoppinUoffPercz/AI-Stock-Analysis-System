"""Pydantic settings + engine configuration. Single source of truth for all knobs.

The plan calls for pydantic schemas on `StrategySpec` and `CostModel`. This file
holds the project-level config: data dirs, default capital, default cost model.
Strategy-specific settings live in `backtest_engine.strategy.spec`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class Settings(BaseModel):
    """Engine-wide settings. Loaded once at startup; passed where needed."""

    # Paths (resolved relative to project root at runtime by the CLI)
    data_dir: Path = Field(default_factory=lambda: Path("data"))
    raw_dir: Path = Field(default_factory=lambda: Path("data/raw"))
    clean_dir: Path = Field(default_factory=lambda: Path("data/clean"))
    universe_dir: Path = Field(default_factory=lambda: Path("data/universe"))
    outputs_dir: Path = Field(default_factory=lambda: Path("outputs"))

    # Defaults
    default_capital: float = 100_000.0
    default_cost: Literal["us_equity_flat", "us_equity_pershare", "zero"] = "us_equity_pershare"
    default_slippage: Literal["zero", "fixed_bps", "linear_impact", "sqrt_impact"] = "linear_impact"
    annualize_factor: int = 252

    # Data fetcher
    yf_sleep_sec: float = 1.5  # yfinance rate-limit throttle
    yf_retries: int = 3

    model_config = {"frozen": False, "extra": "forbid"}


def resolve_settings(**overrides: object) -> Settings:
    """Build settings with optional overrides; absolute-izes paths against CWD."""
    s = Settings(**overrides)  # type: ignore[arg-type]
    # Normalize to absolute so callers don't have to track CWD
    for name in ("data_dir", "raw_dir", "clean_dir", "universe_dir", "outputs_dir"):
        p = getattr(s, name)
        if not p.is_absolute():
            setattr(s, name, Path.cwd() / p)
    return s
