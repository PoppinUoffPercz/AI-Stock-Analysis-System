"""Cost models: commission + slippage. The plan mandates a CostModel on every
strategy spec; ad-hoc models are forbidden downstream.

`CostModel` produces, for each (order_size_shares, bar_volume, bar_price):
    commission: currency charged by broker per order
    slippage_in_bps: basis points added to fill price against the trader

We support four named presets wired to plan section 5:
    - us_equity_pershare: $0.005/share (Alpaca/ZeroPro-style) + linear-impact slippage (DEFAULT)
    - us_equity_flat:     $1/order + linear-impact
    - zero:               debugging only

The Phase 1 (vectorized) path maps a preset name to scalar fits/fees via
build_cost_funcs(); the Phase 2 (event-driven) path calls compute() per fill
and accumulates the cash check directly in the broker.

Slippage models (plan 5.2):
    - linear_impact: slip_bps = base_bps + k * (size / volume)
    - sqrt_impact:   slip_bps = base_bps + k * sqrt(size / volume)
    - fixed_bps:     slip_bps = base_bps
    - zero:          slip_bps = 0

All slippage is computed against a hypothetical full-size order to avoid
making an unrealistic mid-price assumption. The slippage *cost* (currency)
is returned for accounting; the simulator applies the bps to the fill.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

SlipModel = Literal["zero", "fixed_bps", "linear_impact", "sqrt_impact"]
CostPreset = Literal[
    "us_equity_pershare",
    "us_equity_flat",
    "us_equity_proportional",
    "zero",
]


@dataclass(frozen=True)
class CostModel:
    """Single source of truth for commission + slippage on a backtest run.

    All rates are in *fraction-of-trade-notional* for vbt fees (commission_fn)
    and basis-point (bps) for slippage.
    """

    preset: CostPreset
    slippage_model: SlipModel
    # Commission params
    per_share: float  # currency per share
    flat_fee: float  # currency per order
    min_commission: float
    max_commission: float | None
    # Slippage params
    base_bps: float  # bps added to every fill
    impact_k: float  # coefficient for impact models
    # Proportional commission as a fraction of executed notional.
    fees_fraction: float

    def commission(self, shares: float, price: float) -> float:
        size = abs(shares)
        if size == 0:
            return 0.0
        c = self.flat_fee + self.per_share * size + self.fees_fraction * size * price
        c = max(c, self.min_commission)
        if self.max_commission is not None:
            c = min(c, self.max_commission)
        return c

    def slippage_bps(self, shares: float, bar_volume: float) -> float:
        if self.slippage_model == "zero":
            return 0.0
        if self.slippage_model == "fixed_bps":
            return self.base_bps
        if bar_volume <= 0:
            # Avoid div-by-zero; back off to base bps.
            return self.base_bps
        size = abs(shares)
        if self.slippage_model == "linear_impact":
            return self.base_bps + self.impact_k * (size / bar_volume)
        if self.slippage_model == "sqrt_impact":
            return self.base_bps + self.impact_k * math.sqrt(size / bar_volume)
        raise ValueError(f"unknown slippage_model: {self.slippage_model!r}")

    def slippage_cost(self, shares: float, price: float, bar_volume: float) -> float:
        bps = self.slippage_bps(shares, bar_volume)
        return abs(shares) * price * bps / 1e4


PRESETS: dict[CostPreset, CostModel] = {
    "us_equity_pershare": CostModel(
        preset="us_equity_pershare",
        slippage_model="linear_impact",
        per_share=0.005,
        flat_fee=0.0,
        min_commission=1.0,
        max_commission=None,
        base_bps=1.0,  # 1bp baseline slippage
        impact_k=20.0,  # bps per unit order-as-fraction-of-volume
        fees_fraction=0.0,  # we model per-share in Phase 2, fee=0 in vbt phase 1
    ),
    "us_equity_flat": CostModel(
        preset="us_equity_flat",
        slippage_model="linear_impact",
        per_share=0.0,
        flat_fee=1.0,
        min_commission=1.0,
        max_commission=None,
        base_bps=1.0,
        impact_k=20.0,
        fees_fraction=0.0,
    ),
    "us_equity_proportional": CostModel(
        preset="us_equity_proportional",
        slippage_model="fixed_bps",
        per_share=0.0,
        flat_fee=0.0,
        min_commission=0.0,
        max_commission=None,
        base_bps=0.0,
        impact_k=0.0,
        fees_fraction=0.001,
    ),
    "zero": CostModel(
        preset="zero",
        slippage_model="zero",
        per_share=0.0,
        flat_fee=0.0,
        min_commission=0.0,
        max_commission=None,
        base_bps=0.0,
        impact_k=0.0,
        fees_fraction=0.0,
    ),
}


def get_preset(name: CostPreset) -> CostModel:
    return PRESETS[name]


def require_exact_vectorbt_costs(cost: CostModel) -> None:
    """Reject cost models VectorBT cannot apply per fill without approximation."""
    if cost.per_share and (cost.min_commission or cost.max_commission is not None):
        raise ValueError(
            f"VectorBT cannot represent {cost.preset!r} commission exactly"
        )
    if cost.slippage_model in {"linear_impact", "sqrt_impact"} and cost.impact_k:
        raise ValueError(
            f"VectorBT cannot represent {cost.preset!r} volume-impact slippage exactly"
        )


def build_cost_funcs(name: CostPreset | str) -> tuple[float, float]:
    """Return (vbt_fees_fraction, vbt_slippage_fraction) used by VBTAdapter.

    This legacy scalar helper exposes only the exactly proportional component.
    Adapters that need flat or per-share fees must use the actual execution
    price instead of inventing a representative price.
    """
    if name not in PRESETS:
        raise ValueError(f"unknown cost preset: {name!r}")
    cm = PRESETS[name]
    require_exact_vectorbt_costs(cm)
    slippage_fraction = cm.base_bps / 1e4
    return cm.fees_fraction, slippage_fraction
