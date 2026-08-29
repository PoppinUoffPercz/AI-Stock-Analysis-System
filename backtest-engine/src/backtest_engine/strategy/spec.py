"""StrategySpec: the framework-agnostic portability contract from plan section 3.3.

A StrategySpec bundles:
  - name
  - signal factory (callable producing entry/exit from OHLC + params)
  - default params (sweeps live above these in Phase 1)
  - cost model preset name
  - default capital
  - universe reference (string pointing to a saved universe file)

The same spec executes through VBTAdapter, BTAdapter, and NautilusAdapter with
no logic rewrite — only execution mechanics differ.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

SignalFactory = Callable[[pd.DataFrame, dict[str, Any]], pd.DataFrame]


@dataclass
class StrategySpec:
    name: str
    signal_factory: SignalFactory
    cost_model: str = "zero"
    capital: float = 100_000.0
    universe_ref: str = "default"
    params: dict[str, Any] = field(default_factory=dict)

    def make_signals(
        self, ohlc: pd.DataFrame, params: dict[str, Any] | None = None
    ) -> pd.DataFrame:
        """Generate the entry/exit signal frame for `ohlc`.

        Default behavior: use `self.params`; override with `params` arg if provided
        (used by parameter sweeps where individual results come from combinations).
        """
        return self.signal_factory(ohlc, params if params is not None else self.params)
