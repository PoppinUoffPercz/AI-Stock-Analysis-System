"""Typed defaults for the offline market-analytics pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time, timedelta
from math import isfinite

from .models import VolumeInputMode


@dataclass(frozen=True, slots=True)
class SessionConfig:
    timezone: str = "America/New_York"
    rth_start: time = time(9, 30)
    rth_end: time = time(16, 0)
    include_extended_hours: bool = False


@dataclass(frozen=True, slots=True)
class DOMConfig:
    imbalance_levels: tuple[int, ...] = (1, 3, 5, 10)
    max_age: timedelta = timedelta(seconds=5)
    velocity_window: timedelta = timedelta(seconds=60)
    heatmap_max_observations: int = 256
    heatmap_retention: timedelta = timedelta(minutes=15)
    wall_min_normalized_size: float = 2.0
    wall_min_symbol_size: float = 2.0
    wall_min_persistence_ms: int = 5_000
    wall_max_distance_bps: float = 50.0
    wall_min_reliability: float = 0.5
    wall_target_replenishments: int = 2
    wall_target_appearances: int = 2
    wall_reliability_weights: tuple[float, ...] = (0.25, 0.2, 0.15, 0.2, 0.2)


@dataclass(frozen=True, slots=True)
class FlowConfig:
    bar_duration: timedelta = timedelta(minutes=1)
    imbalance_ratio: float = 3.0
    min_stacked_levels: int = 3
    fallback_confidence: float = 0.5
    unknown_trade_quality_penalty: float = 20.0
    exhaustion_window_bars: int = 4
    flip_window_bars: int = 3
    exhaustion_weights: tuple[float, ...] = (0.25, 0.2, 0.2, 0.15, 0.2)
    min_confirmation_score: float = 0.5


@dataclass(frozen=True, slots=True)
class VWAPConfig:
    band_multipliers: tuple[float, ...] = (1.0, 2.0)
    slope_window: int = 3


@dataclass(frozen=True, slots=True)
class ProfileConfig:
    tpo_bracket: timedelta = timedelta(minutes=30)
    row_size: float | None = None
    value_area_percentage: float = 0.70
    rolling_windows: tuple[int, ...] = (14, 30, 60, 90, 120)
    initial_balance_brackets: int = 2
    single_print_neighbor_min_tpo: int = 2
    single_print_retention_sessions: int = 20
    cluster_tolerance_ticks: int = 2
    cluster_tolerance_bps: float = 10.0
    hvn_neighbor_multiplier: float = 1.5
    lvn_neighbor_multiplier: float = 0.5


@dataclass(frozen=True, slots=True)
class OptionsConfig:
    dealer_model: str = "classic_oi_proxy"
    option_model: str | None = "black_scholes"
    root_grid_pct: float = 0.20
    root_grid_points: int = 81
    root_residual_tolerance: float = 1e-6
    risk_free_rate: float = 0.0
    dividend_yield: float = 0.0
    high_delta_threshold: float = 0.90
    saturation_weights: tuple[float, ...] = (0.25, 0.25, 0.25, 0.25)
    max_quote_age: timedelta = timedelta(days=2)
    min_iv: float = 1e-6
    max_iv: float = 5.0


@dataclass(frozen=True, slots=True)
class VolatilityConfig:
    implied_horizons_days: tuple[int, ...] = (1, 3, 7, 14, 30, 60, 90)
    realized_windows_sessions: tuple[int, ...] = (5, 10, 20, 30, 60, 90)
    iv_history_windows: tuple[int, ...] = (20, 60, 120, 252)
    max_iv_history: int = 252
    max_relative_spread: float = 0.25
    max_timestamp_skew: timedelta = timedelta(minutes=5)
    min_open_interest: float = 1.0
    min_volume: float = 1.0
    min_surface_points: int = 3
    iv_rv_near_threshold: float = 0.05
    iv_rv_far_threshold: float = 0.20
    term_steep_threshold: float = 0.10
    event_premium_threshold: float = 0.10
    skew_put_threshold: float = 0.03
    skew_strong_threshold: float = 0.08


@dataclass(frozen=True, slots=True)
class LevelConfig:
    expected_move_sigmas: tuple[float, ...] = (0.5, 1.0, 1.5, 2.0)
    cluster_tolerance_ticks: int = 2
    cluster_tolerance_bps: float = 10.0
    cluster_atr_fraction: float = 0.10
    same_family_strength_cap: float = 1.0
    min_independent_families: int = 2
    max_zones: int = 12


@dataclass(frozen=True, slots=True)
class CreditConfig:
    component_weights: tuple[float, ...] = (0.25, 0.20, 0.20, 0.15, 0.10, 0.10)
    min_weight_coverage: float = 0.60
    active_news_days: int = 14
    stressed_threshold: float = 40.0
    crisis_threshold: float = 60.0
    systemic_threshold: float = 80.0
    complacency_iv_rank_threshold: float = 30.0
    repricing_iv_rank_threshold: float = 70.0
    repricing_iv_rv_ratio: float = 1.25


@dataclass(frozen=True, slots=True)
class AnalyticsConfig:
    session: SessionConfig = field(default_factory=SessionConfig)
    dom: DOMConfig = field(default_factory=DOMConfig)
    flow: FlowConfig = field(default_factory=FlowConfig)
    vwap: VWAPConfig = field(default_factory=VWAPConfig)
    profile: ProfileConfig = field(default_factory=ProfileConfig)
    options: OptionsConfig = field(default_factory=OptionsConfig)
    volatility: VolatilityConfig = field(default_factory=VolatilityConfig)
    levels: LevelConfig = field(default_factory=LevelConfig)
    credit: CreditConfig = field(default_factory=CreditConfig)
    volume_input_mode: VolumeInputMode = VolumeInputMode.TRADES

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "volume_input_mode", VolumeInputMode(self.volume_input_mode)
        )
        if (
            not self.dom.imbalance_levels
            or tuple(sorted(self.dom.imbalance_levels)) != self.dom.imbalance_levels
        ):
            raise ValueError("dom imbalance_levels must be sorted and nonempty")
        if any(level <= 0 for level in self.dom.imbalance_levels):
            raise ValueError("dom imbalance levels must be positive")
        if self.dom.heatmap_max_observations <= 0:
            raise ValueError("heatmap_max_observations must be positive")
        if (
            self.dom.wall_min_normalized_size <= 0
            or self.dom.wall_min_symbol_size <= 0
            or self.dom.wall_min_persistence_ms < 0
            or self.dom.wall_max_distance_bps < 0
            or not 0 <= self.dom.wall_min_reliability <= 1
            or self.dom.wall_target_replenishments <= 0
            or self.dom.wall_target_appearances <= 0
            or not _is_weight_vector(self.dom.wall_reliability_weights)
        ):
            raise ValueError("DOM wall settings are invalid")
        if (
            self.flow.bar_duration <= timedelta(0)
            or self.flow.imbalance_ratio <= 1
            or self.flow.min_stacked_levels <= 0
            or not 0 <= self.flow.unknown_trade_quality_penalty <= 100
        ):
            raise ValueError("flow imbalance settings are invalid")
        if len(self.flow.exhaustion_weights) != 5 or not _is_weight_vector(
            self.flow.exhaustion_weights
        ):
            raise ValueError(
                "exhaustion_weights must contain five nonnegative values summing to one"
            )
        if not 0 <= self.flow.fallback_confidence <= 1:
            raise ValueError("fallback_confidence must be between zero and one")
        if (
            self.profile.tpo_bracket <= timedelta(0)
            or self.profile.row_size is not None
            and self.profile.row_size <= 0
            or self.profile.initial_balance_brackets <= 0
            or self.profile.single_print_neighbor_min_tpo <= 0
            or self.profile.single_print_retention_sessions <= 0
        ):
            raise ValueError("profile row and bracket settings are invalid")
        if not 0 < self.profile.value_area_percentage < 1:
            raise ValueError("value_area_percentage must be between zero and one")
        if not self.profile.rolling_windows or any(
            window <= 0 for window in self.profile.rolling_windows
        ):
            raise ValueError("rolling_windows must be positive and nonempty")
        if (
            not self.vwap.band_multipliers
            or any(multiplier <= 0 for multiplier in self.vwap.band_multipliers)
            or self.vwap.slope_window <= 0
        ):
            raise ValueError("band_multipliers must be positive and nonempty")
        if self.options.root_grid_points < 3 or self.options.root_grid_points % 2 == 0:
            raise ValueError(
                "root_grid_points must be an odd integer of at least three"
            )
        if self.options.root_grid_pct <= 0 or self.options.root_residual_tolerance < 0:
            raise ValueError("option root settings are invalid")
        if not _is_weight_vector(self.options.saturation_weights):
            raise ValueError("saturation_weights must be nonnegative and sum to one")
        if not 0 < self.options.high_delta_threshold <= 1:
            raise ValueError("high_delta_threshold must be in (0, 1]")
        if self.options.min_iv <= 0 or self.options.max_iv <= self.options.min_iv:
            raise ValueError("IV bounds are invalid")
        if (
            not self.volatility.implied_horizons_days
            or tuple(sorted(self.volatility.implied_horizons_days))
            != self.volatility.implied_horizons_days
            or any(day <= 0 for day in self.volatility.implied_horizons_days)
            or not self.volatility.realized_windows_sessions
            or any(day <= 1 for day in self.volatility.realized_windows_sessions)
            or not self.volatility.iv_history_windows
            or any(day <= 0 for day in self.volatility.iv_history_windows)
            or self.volatility.max_iv_history < max(self.volatility.iv_history_windows)
            or not self.volatility.max_relative_spread > 0
            or self.volatility.max_timestamp_skew <= timedelta(0)
            or self.volatility.min_open_interest < 0
            or self.volatility.min_volume < 0
            or self.volatility.min_surface_points < 2
            or not 0
            < self.volatility.iv_rv_near_threshold
            < self.volatility.iv_rv_far_threshold
            or not self.volatility.term_steep_threshold > 0
            or not self.volatility.event_premium_threshold > 0
            or not 0
            < self.volatility.skew_put_threshold
            < self.volatility.skew_strong_threshold
        ):
            raise ValueError("volatility settings are invalid")
        if (
            not self.levels.expected_move_sigmas
            or any(sigma <= 0 for sigma in self.levels.expected_move_sigmas)
            or self.levels.cluster_tolerance_ticks <= 0
            or self.levels.cluster_tolerance_bps < 0
            or self.levels.cluster_atr_fraction < 0
            or self.levels.same_family_strength_cap <= 0
            or self.levels.min_independent_families <= 0
            or self.levels.max_zones <= 0
        ):
            raise ValueError("level settings are invalid")
        if (
            not _is_weight_vector(self.credit.component_weights)
            or not 0 < self.credit.min_weight_coverage <= 1
            or self.credit.active_news_days <= 0
            or not 0 <= self.credit.stressed_threshold < self.credit.crisis_threshold
            or not self.credit.crisis_threshold < self.credit.systemic_threshold
            or not 0 <= self.credit.complacency_iv_rank_threshold <= 100
            or not 0 <= self.credit.repricing_iv_rank_threshold <= 100
            or self.credit.repricing_iv_rv_ratio <= 0
        ):
            raise ValueError("credit settings are invalid")


def _is_weight_vector(values: tuple[float, ...]) -> bool:
    return (
        bool(values)
        and all(isfinite(value) and value >= 0 for value in values)
        and abs(sum(values) - 1.0) < 1e-9
    )
