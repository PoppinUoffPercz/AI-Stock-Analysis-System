from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from stock_analysis.artifacts import ArtifactRef
from stock_analysis.market_analytics.features import FeatureRecord
from stock_analysis.market_analytics.models import (
    AnalyticsSnapshot,
    _require_finite,
    _require_utc,
)


class RegimeLabel(StrEnum):
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    MEAN_REVERTING = "mean_reverting"
    RISK_OFF = "risk_off"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class TrendState(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    FLAT = "flat"
    UNKNOWN = "unknown"


class VolatilityRegime(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    UNKNOWN = "unknown"


class LiquidityRegime(StrEnum):
    GOOD = "good"
    NORMAL = "normal"
    STRESSED = "stressed"
    UNKNOWN = "unknown"


class OpportunityFamily(StrEnum):
    TREND_CONTINUATION = "trend_continuation"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    FUNDAMENTAL_VALUE = "fundamental_value"
    OPTIONS_VOLATILITY = "options_volatility_relative_value"


class Direction(StrEnum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class RiskDecisionStatus(StrEnum):
    APPROVED = "approved"
    RESIZED = "approved_with_resized_allocation"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class RegimePolicyConfig:
    version: str = "regime-v1"
    trend_z_threshold: float = 0.35
    high_iv_rank: float = 70.0
    low_iv_rank: float = 30.0
    tight_spread_bps: float = 5.0
    stressed_spread_bps: float = 15.0
    min_known_dimensions: int = 2

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("regime policy version must not be empty")
        for value, label in (
            (self.trend_z_threshold, "trend_z_threshold"),
            (self.high_iv_rank, "high_iv_rank"),
            (self.low_iv_rank, "low_iv_rank"),
            (self.tight_spread_bps, "tight_spread_bps"),
            (self.stressed_spread_bps, "stressed_spread_bps"),
        ):
            _require_finite(float(value), label)
        if self.trend_z_threshold < 0:
            raise ValueError("trend_z_threshold must be nonnegative")
        if not 0 <= self.low_iv_rank <= self.high_iv_rank <= 100:
            raise ValueError("IV-rank thresholds must satisfy 0 <= low <= high <= 100")
        if not 0 <= self.tight_spread_bps <= self.stressed_spread_bps:
            raise ValueError("spread thresholds must satisfy 0 <= tight <= stressed")
        if (
            isinstance(self.min_known_dimensions, bool)
            or not isinstance(self.min_known_dimensions, int)
            or not 0 <= self.min_known_dimensions <= 3
        ):
            raise ValueError("min_known_dimensions must be an integer between 0 and 3")


@dataclass(frozen=True, slots=True)
class RegimeAssessment:
    as_of: datetime
    label: RegimeLabel
    trend: TrendState
    volatility: VolatilityRegime
    liquidity: LiquidityRegime
    quality_score: float
    missing_dimensions: tuple[str, ...]
    reasons: tuple[str, ...]
    eligible_families: tuple[OpportunityFamily, ...]
    policy_version: str

    def __post_init__(self) -> None:
        _require_utc(self.as_of, "regime as_of")
        _require_finite(self.quality_score, "regime quality_score")
        if not 0 <= self.quality_score <= 100:
            raise ValueError("regime quality_score must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class ScreenConfig:
    version: str = "screen-v1"
    min_feature_coverage: float = 2 / 3
    min_ranking_score: float = 50.0
    legacy_weight: float = 0.15

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("screen config version must not be empty")
        for value, label in (
            (self.min_feature_coverage, "min_feature_coverage"),
            (self.min_ranking_score, "min_ranking_score"),
            (self.legacy_weight, "legacy_weight"),
        ):
            _require_finite(float(value), label)
        if not 0 <= self.min_feature_coverage <= 1:
            raise ValueError("min_feature_coverage must be between 0 and 1")
        if not 0 <= self.min_ranking_score <= 100:
            raise ValueError("min_ranking_score must be between 0 and 100")
        if not 0 <= self.legacy_weight <= 1:
            raise ValueError("legacy_weight must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ScoreComponent:
    name: str
    value: float
    weight: float
    contribution: float
    source_features: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScreenCandidate:
    symbol: str
    direction: Direction
    family: OpportunityFamily
    as_of: datetime
    ranking_score: float
    score_components: tuple[ScoreComponent, ...]
    raw_features: Mapping[str, float | None]
    regime: RegimeLabel
    data_quality: float
    warnings: tuple[str, ...]
    explanation_codes: tuple[str, ...]
    legacy_scores: Mapping[str, float] = field(default_factory=dict)
    scoring_version: str = "screen-v1"

    def __post_init__(self) -> None:
        _require_utc(self.as_of, "candidate as_of")
        _require_finite(self.ranking_score, "ranking_score")
        _require_finite(self.data_quality, "data_quality")
        if not 0 <= self.ranking_score <= 100:
            raise ValueError("ranking_score must be between 0 and 100")
        if not 0 <= self.data_quality <= 100:
            raise ValueError("data_quality must be between 0 and 100")
        object.__setattr__(self, "direction", Direction(self.direction))
        object.__setattr__(self, "family", OpportunityFamily(self.family))
        object.__setattr__(self, "raw_features", dict(self.raw_features))
        object.__setattr__(self, "legacy_scores", dict(self.legacy_scores))


@dataclass(frozen=True, slots=True)
class ScreenResult:
    as_of: datetime
    regime: RegimeAssessment
    candidates: tuple[ScreenCandidate, ...]
    exclusions: Mapping[str, tuple[str, ...]]
    unsupported_families: Mapping[str, str]
    input_snapshot_refs: Mapping[str, str]
    config_version: str
    screen_id: str

    def __post_init__(self) -> None:
        _require_utc(self.as_of, "screen as_of")
        object.__setattr__(self, "exclusions", dict(self.exclusions))
        object.__setattr__(
            self, "unsupported_families", dict(self.unsupported_families)
        )
        object.__setattr__(self, "input_snapshot_refs", dict(self.input_snapshot_refs))


@dataclass(frozen=True, slots=True)
class PositionRequest:
    symbol: str
    direction: Direction | str
    price: float
    requested_notional: float
    lot_size: float
    as_of: datetime
    stop_price: float | None = None
    volatility: float | None = None

    def __post_init__(self) -> None:
        _require_utc(self.as_of, "position request as_of")
        if not self.symbol:
            raise ValueError("position request symbol must not be empty")
        direction = Direction(self.direction)
        if direction is Direction.NEUTRAL:
            raise ValueError("position request direction must be long or short")
        object.__setattr__(self, "direction", direction)
        for value, label in (
            (self.price, "price"),
            (self.requested_notional, "requested_notional"),
            (self.lot_size, "lot_size"),
        ):
            _require_finite(value, label)
            if value <= 0:
                raise ValueError(f"{label} must be positive")


@dataclass(frozen=True, slots=True)
class TradeThesis:
    thesis_id: str
    revision: int
    created_at: datetime
    as_of: datetime
    originating_screen_id: str
    symbol: str
    direction: Direction
    family: OpportunityFamily
    intended_horizon: str
    regime: RegimeLabel
    observed_facts: tuple[str, ...]
    deterministic_calculations: tuple[str, ...]
    assumptions: tuple[str, ...]
    interpretations: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    entry_conditions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    exit_logic: tuple[str, ...]
    expected_move: float | None
    expected_move_method: str | None
    liquidity_limitations: tuple[str, ...]
    known_unknowns: tuple[str, ...]
    data_quality: float
    suggested_position: PositionRequest
    status: str = "active"
    expiry: datetime | None = None
    supersedes: str | None = None
    risk_approval_id: str | None = None

    def __post_init__(self) -> None:
        _require_utc(self.created_at, "thesis created_at")
        _require_utc(self.as_of, "thesis as_of")
        if self.expiry is not None:
            _require_utc(self.expiry, "thesis expiry")
        if self.revision <= 0:
            raise ValueError("thesis revision must be positive")
        object.__setattr__(self, "direction", Direction(self.direction))
        object.__setattr__(self, "family", OpportunityFamily(self.family))


@dataclass(frozen=True, slots=True)
class PositionState:
    symbol: str
    quantity: float
    price: float

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("position symbol must not be empty")
        _require_finite(self.quantity, "position quantity")
        _require_finite(self.price, "position price")
        if self.price <= 0:
            raise ValueError("position price must be positive")

    @property
    def notional(self) -> float:
        return self.quantity * self.price


@dataclass(frozen=True, slots=True)
class PendingOrderState:
    symbol: str
    signed_notional: float

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("pending order symbol must not be empty")
        _require_finite(self.signed_notional, "pending order signed_notional")


@dataclass(frozen=True, slots=True)
class PortfolioState:
    as_of: datetime
    equity: float
    cash: float
    positions: tuple[PositionState, ...]
    pending_orders: tuple[PendingOrderState, ...]

    def __post_init__(self) -> None:
        _require_utc(self.as_of, "portfolio as_of")
        _require_finite(self.equity, "portfolio equity")
        _require_finite(self.cash, "portfolio cash")
        if self.equity <= 0 or self.cash < 0:
            raise ValueError("portfolio equity must be positive and cash nonnegative")


@dataclass(frozen=True, slots=True)
class ReturnObservation:
    as_of: datetime
    value: float

    def __post_init__(self) -> None:
        _require_utc(self.as_of, "return observation as_of")
        _require_finite(self.value, "return observation value")


@dataclass(frozen=True, slots=True)
class PortfolioRiskContext:
    """Point-in-time trailing returns and sector labels used by advanced risk gates."""

    as_of: datetime
    returns_by_symbol: Mapping[str, tuple[ReturnObservation, ...]]
    sector_by_symbol: Mapping[str, str]

    def __post_init__(self) -> None:
        _require_utc(self.as_of, "portfolio risk context as_of")
        returns = {
            symbol: tuple(values) for symbol, values in self.returns_by_symbol.items()
        }
        for symbol, values in returns.items():
            if not symbol:
                raise ValueError("risk return symbol must not be empty")
            timestamps = [item.as_of for item in values]
            if timestamps != sorted(timestamps) or len(timestamps) != len(
                set(timestamps)
            ):
                raise ValueError(
                    "risk return observations must be unique and increasing"
                )
        sectors = dict(self.sector_by_symbol)
        if any(not symbol or not sector for symbol, sector in sectors.items()):
            raise ValueError(
                "risk sector mappings must use nonempty symbols and sectors"
            )
        object.__setattr__(self, "returns_by_symbol", returns)
        object.__setattr__(self, "sector_by_symbol", sectors)


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    version: str = "risk-v1"
    max_single_name_fraction: float = 0.10
    max_gross_fraction: float = 1.00
    max_net_fraction: float = 1.00
    min_cash_fraction: float = 0.05
    max_state_age: timedelta = timedelta(minutes=5)
    approval_ttl: timedelta = timedelta(minutes=5)
    restricted_symbols: tuple[str, ...] = ()
    allow_short: bool = False
    max_sector_fraction: float | None = None
    max_correlated_fraction: float | None = None
    max_pair_correlation: float | None = None
    max_annualized_volatility: float | None = None
    risk_lookback: int = 60
    min_risk_observations: int = 20
    annualization_factor: float = 252.0
    max_risk_data_age: timedelta = timedelta(days=7)

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("risk policy version must not be empty")
        for value, label in (
            (self.max_single_name_fraction, "max_single_name_fraction"),
            (self.max_gross_fraction, "max_gross_fraction"),
            (self.max_net_fraction, "max_net_fraction"),
            (self.min_cash_fraction, "min_cash_fraction"),
        ):
            _require_finite(float(value), label)
        if (
            min(
                self.max_single_name_fraction,
                self.max_gross_fraction,
                self.max_net_fraction,
            )
            < 0
        ):
            raise ValueError("risk exposure fractions must be nonnegative")
        if not 0 <= self.min_cash_fraction <= 1:
            raise ValueError("min_cash_fraction must be between 0 and 1")
        if self.max_state_age < timedelta(0):
            raise ValueError("max_state_age must be nonnegative")
        if self.approval_ttl < timedelta(0):
            raise ValueError("approval_ttl must be nonnegative")
        for optional_value, label in (
            (self.max_sector_fraction, "max_sector_fraction"),
            (self.max_correlated_fraction, "max_correlated_fraction"),
            (self.max_pair_correlation, "max_pair_correlation"),
            (self.max_annualized_volatility, "max_annualized_volatility"),
        ):
            if optional_value is not None:
                _require_finite(float(optional_value), label)
                if optional_value < 0:
                    raise ValueError(f"{label} must be nonnegative")
        if self.max_pair_correlation is not None and self.max_pair_correlation > 1:
            raise ValueError("max_pair_correlation must be between 0 and 1")
        if self.risk_lookback <= 1:
            raise ValueError("risk_lookback must be greater than 1")
        if not 2 <= self.min_risk_observations <= self.risk_lookback:
            raise ValueError(
                "min_risk_observations must be between 2 and risk_lookback"
            )
        _require_finite(self.annualization_factor, "annualization_factor")
        if self.annualization_factor <= 0:
            raise ValueError("annualization_factor must be positive")
        if self.max_risk_data_age < timedelta(0):
            raise ValueError("max_risk_data_age must be nonnegative")


@dataclass(frozen=True, slots=True)
class RiskDecision:
    decision_id: str
    status: RiskDecisionStatus
    symbol: str
    requested_quantity: float
    approved_quantity: float
    requested_notional: float
    approved_notional: float
    binding_constraints: tuple[str, ...]
    before_exposure: Mapping[str, float]
    after_exposure: Mapping[str, float]
    request_as_of: datetime
    portfolio_as_of: datetime
    policy_version: str
    reasons: tuple[str, ...]
    approval_expiry: datetime | None

    def __post_init__(self) -> None:
        _require_utc(self.request_as_of, "risk request_as_of")
        _require_utc(self.portfolio_as_of, "risk portfolio_as_of")
        if self.approval_expiry is not None:
            _require_utc(self.approval_expiry, "risk approval_expiry")
        object.__setattr__(self, "status", RiskDecisionStatus(self.status))
        object.__setattr__(self, "before_exposure", dict(self.before_exposure))
        object.__setattr__(self, "after_exposure", dict(self.after_exposure))


@dataclass(frozen=True, slots=True)
class CheckpointResult:
    analytics: AnalyticsSnapshot
    regime: RegimeAssessment
    screen: ScreenResult
    thesis: TradeThesis | None
    risk: RiskDecision | None
    artifacts: Mapping[str, ArtifactRef]
    degraded_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifacts", dict(self.artifacts))


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    features: FeatureRecord
    legacy_scores: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CostAttribution:
    run_id: str
    units: str
    cost_basis: str
    gross_return: float | None
    gross_pnl: float | None
    modeled_commission: float | None
    modeled_slippage: float | None
    modeled_fees: float | None
    modeled_spread: float | None
    modeled_financing: float | None
    modeled_total_cost: float | None
    observed_total_cost: float | None
    net_return: float | None
    net_pnl: float
    cost_addback_pnl: float | None
    modeled_costs_by_symbol: Mapping[str, Mapping[str, float]]
    unavailable_cost_components: tuple[str, ...]
    reconciliation_difference: float | None
    reconciliation_tolerance: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "modeled_costs_by_symbol",
            {
                symbol: dict(values)
                for symbol, values in self.modeled_costs_by_symbol.items()
            },
        )


@dataclass(frozen=True, slots=True)
class ReviewProposal:
    proposal_id: str
    run_id: str
    experiment_identity: str
    intelligence_refs: Mapping[str, Mapping[str, object]]
    experiment_artifacts: Mapping[str, str]
    rationale: tuple[str, ...]
    attribution: CostAttribution
    sample_warnings: tuple[str, ...]
    proposed_action: str
    execution_status: str = "read_only_non_executing"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "intelligence_refs",
            {
                name: dict(reference)
                for name, reference in self.intelligence_refs.items()
            },
        )
        object.__setattr__(
            self, "experiment_artifacts", dict(self.experiment_artifacts)
        )
        if self.execution_status != "read_only_non_executing":
            raise ValueError("review proposals must remain read-only and non-executing")
