from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import floor, sqrt, tanh
from typing import ClassVar

from stock_analysis.market_analytics.features import FeatureRecord
from stock_analysis.market_analytics.models import MetricStatus

from .artifacts import content_identity
from .models import (
    Direction,
    LiquidityRegime,
    OpportunityFamily,
    PendingOrderState,
    PortfolioRiskContext,
    PortfolioState,
    PositionRequest,
    PositionState,
    RegimeAssessment,
    RegimeLabel,
    RegimePolicyConfig,
    RiskDecision,
    RiskDecisionStatus,
    RiskPolicy,
    ScoreComponent,
    ScreenCandidate,
    ScreenConfig,
    ScreenResult,
    TradeThesis,
    TrendState,
    VolatilityRegime,
)


@dataclass(frozen=True, slots=True)
class CandidateInput:
    features: FeatureRecord
    legacy_scores: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        scores = dict(self.legacy_scores)
        if any(not 0 <= value <= 100 for value in scores.values()):
            raise ValueError("legacy scores must be between 0 and 100")
        object.__setattr__(self, "legacy_scores", scores)


def _reject_future_metadata(features: FeatureRecord) -> None:
    for name, metadata in features.metadata.items():
        if metadata.as_of > features.as_of:
            raise ValueError(f"feature {name} uses metadata from the future")


class RegimeEngine:
    def __init__(self, config: RegimePolicyConfig | None = None) -> None:
        self.config = config or RegimePolicyConfig()

    def assess(self, features: FeatureRecord) -> RegimeAssessment:
        _reject_future_metadata(features)

        zscore = self._usable(features, "vwap_zscore")
        slope = self._usable(features, "vwap_slope")
        if zscore is None and slope is None:
            trend = TrendState.UNKNOWN
        elif slope is not None and slope > 0:
            trend = TrendState.BULLISH
        elif slope is not None and slope < 0:
            trend = TrendState.BEARISH
        elif zscore is not None and zscore >= self.config.trend_z_threshold:
            trend = TrendState.BULLISH
        elif zscore is not None and zscore <= -self.config.trend_z_threshold:
            trend = TrendState.BEARISH
        else:
            trend = TrendState.FLAT

        iv_rank = self._usable(features, "iv_rank_252d")
        if iv_rank is None:
            volatility = VolatilityRegime.UNKNOWN
        elif iv_rank >= self.config.high_iv_rank:
            volatility = VolatilityRegime.HIGH
        elif iv_rank <= self.config.low_iv_rank:
            volatility = VolatilityRegime.LOW
        else:
            volatility = VolatilityRegime.NORMAL

        spread = self._usable(features, "spread_bps")
        if spread is None:
            liquidity = LiquidityRegime.UNKNOWN
        elif spread <= self.config.tight_spread_bps:
            liquidity = LiquidityRegime.GOOD
        elif spread >= self.config.stressed_spread_bps:
            liquidity = LiquidityRegime.STRESSED
        else:
            liquidity = LiquidityRegime.NORMAL

        missing = tuple(
            name
            for name, value in (
                ("trend", trend),
                ("volatility", volatility),
                ("liquidity", liquidity),
            )
            if value.value == "unknown"
        )
        credit = features.categories.get("credit_regime")
        risk_off = liquidity is LiquidityRegime.STRESSED or (
            credit is not None
            and any(token in credit.lower() for token in ("crisis", "repricing"))
        )
        known_dimensions = 3 - len(missing)
        if risk_off:
            label = RegimeLabel.RISK_OFF
        elif known_dimensions < self.config.min_known_dimensions:
            label = RegimeLabel.UNKNOWN
        elif trend is TrendState.BULLISH:
            label = RegimeLabel.TREND_UP
        elif trend is TrendState.BEARISH:
            label = RegimeLabel.TREND_DOWN
        elif trend is TrendState.FLAT:
            label = RegimeLabel.MEAN_REVERTING
        else:
            label = RegimeLabel.MIXED

        eligible = {
            RegimeLabel.TREND_UP: (
                OpportunityFamily.TREND_CONTINUATION,
                OpportunityFamily.MEAN_REVERSION,
            ),
            RegimeLabel.TREND_DOWN: (
                OpportunityFamily.TREND_CONTINUATION,
                OpportunityFamily.MEAN_REVERSION,
            ),
            RegimeLabel.MEAN_REVERTING: (OpportunityFamily.MEAN_REVERSION,),
            RegimeLabel.MIXED: (OpportunityFamily.MEAN_REVERSION,),
            RegimeLabel.RISK_OFF: (OpportunityFamily.MEAN_REVERSION,),
            RegimeLabel.UNKNOWN: (),
        }[label]
        quality_inputs = [
            features.metadata[name].quality_score
            for name in ("vwap_zscore", "vwap_slope", "iv_rank_252d", "spread_bps")
            if self._usable(features, name) is not None
        ]
        quality = (
            sum(quality_inputs) / len(quality_inputs) * (known_dimensions / 3)
            if quality_inputs
            else 0.0
        )
        reasons = (
            f"trend={trend.value}",
            f"volatility={volatility.value}",
            f"liquidity={liquidity.value}",
        )
        return RegimeAssessment(
            features.as_of,
            label,
            trend,
            volatility,
            liquidity,
            quality,
            missing,
            reasons,
            eligible,
            self.config.version,
        )

    @staticmethod
    def _usable(features: FeatureRecord, name: str) -> float | None:
        value = features.values.get(name)
        metadata = features.metadata.get(name)
        if value is None or metadata is None:
            return None
        if metadata.status not in {
            MetricStatus.OK,
            MetricStatus.DEGRADED,
            MetricStatus.PARTIAL,
        }:
            return None
        return float(value)


class ScreeningEngine:
    _unsupported: ClassVar[dict[str, str]] = {
        OpportunityFamily.BREAKOUT.value: "separate breakout evidence needs point-in-time historical normalization",
        OpportunityFamily.FUNDAMENTAL_VALUE.value: "canonical point-in-time fundamental features are not in FeatureRecord yet",
        OpportunityFamily.OPTIONS_VOLATILITY.value: "options analytics exist but strategy lifecycle/payoff eligibility is not canonical yet",
    }

    def __init__(self, config: ScreenConfig | None = None) -> None:
        self.config = config or ScreenConfig()

    def run(
        self,
        candidates: tuple[CandidateInput, ...],
        regime: RegimeAssessment,
        *,
        input_snapshot_refs: Mapping[str, str] | None = None,
    ) -> ScreenResult:
        snapshot_refs = dict(input_snapshot_refs or {})
        ranked: list[ScreenCandidate] = []
        exclusions: dict[str, tuple[str, ...]] = {}
        for candidate in candidates:
            if candidate.features.as_of != regime.as_of:
                raise ValueError(
                    "candidate features and regime must share one as-of timestamp"
                )
            _reject_future_metadata(candidate.features)
            results: list[ScreenCandidate] = []
            reasons: list[str] = []
            if OpportunityFamily.TREND_CONTINUATION in regime.eligible_families:
                result, reason = self._trend(candidate, regime)
                if result is not None:
                    results.append(result)
                elif reason:
                    reasons.append(reason)
            if OpportunityFamily.MEAN_REVERSION in regime.eligible_families:
                result, reason = self._mean_reversion(candidate, regime)
                if result is not None:
                    results.append(result)
                elif reason:
                    reasons.append(reason)
            if not regime.eligible_families:
                reasons.append("regime has no eligible opportunity family")
            ranked.extend(results)
            if not results:
                exclusions[candidate.features.symbol] = tuple(
                    reasons or ("no qualifying setup",)
                )

        ranked.sort(
            key=lambda item: (-item.ranking_score, item.symbol, item.family.value)
        )
        screen_id = content_identity(
            {
                "as_of": regime.as_of,
                "regime": regime,
                "candidates": tuple(ranked),
                "exclusions": exclusions,
                "unsupported": self._unsupported,
                "input_snapshot_refs": snapshot_refs,
                "version": self.config.version,
            }
        )
        return ScreenResult(
            regime.as_of,
            regime,
            tuple(ranked),
            exclusions,
            self._unsupported,
            snapshot_refs,
            self.config.version,
            screen_id,
        )

    def _trend(
        self, candidate: CandidateInput, regime: RegimeAssessment
    ) -> tuple[ScreenCandidate | None, str | None]:
        features = candidate.features
        signals = {
            "vwap_zscore": self._signal(
                features, "vwap_zscore", lambda value: tanh(value / 2)
            ),
            "book_imbalance_l5": self._signal(
                features, "book_imbalance_l5", self._clip_signed
            ),
            "distance_weighted_imbalance": self._signal(
                features, "distance_weighted_imbalance", self._clip_signed
            ),
        }
        available = {
            name: value for name, value in signals.items() if value is not None
        }
        if len(available) / len(signals) < self.config.min_feature_coverage:
            return None, "trend continuation lacks minimum feature coverage"
        direction_value = sum(available.values()) / len(available)
        if abs(direction_value) < 0.1:
            return None, "trend continuation evidence is directionally weak"
        direction = Direction.LONG if direction_value > 0 else Direction.SHORT
        sign = 1.0 if direction is Direction.LONG else -1.0
        components = [
            ScoreComponent(name, 50 * (1 + sign * value), 1.0, 0.0, (name,))
            for name, value in available.items()
        ]
        components = self._with_legacy(components, candidate.legacy_scores, direction)
        components, score = self._normalize_components(components)
        if score < self.config.min_ranking_score:
            return None, "trend continuation ranking score is below threshold"
        return self._candidate(
            candidate,
            regime,
            OpportunityFamily.TREND_CONTINUATION,
            direction,
            score,
            components,
            tuple(available),
        ), None

    def _mean_reversion(
        self, candidate: CandidateInput, regime: RegimeAssessment
    ) -> tuple[ScreenCandidate | None, str | None]:
        features = candidate.features
        zscore = self._value(features, "vwap_zscore")
        confluence = self._value(features, "nearest_confluence_score")
        spread = self._value(features, "spread_bps")
        available_count = sum(
            value is not None for value in (zscore, confluence, spread)
        )
        if available_count / 3 < self.config.min_feature_coverage:
            return None, "mean reversion lacks minimum feature coverage"
        if zscore is None or abs(zscore) < 0.5:
            return None, "mean reversion needs a material VWAP deviation"
        direction = Direction.SHORT if zscore > 0 else Direction.LONG
        components: list[ScoreComponent] = [
            ScoreComponent(
                "vwap_extension",
                min(abs(zscore) / 3, 1.0) * 100,
                1.0,
                0.0,
                ("vwap_zscore",),
            )
        ]
        if confluence is not None:
            components.append(
                ScoreComponent(
                    "confluence",
                    self._clip_100(confluence),
                    1.0,
                    0.0,
                    ("nearest_confluence_score",),
                )
            )
        if spread is not None:
            components.append(
                ScoreComponent(
                    "liquidity",
                    max(0.0, 100 - min(spread / 20, 1.0) * 100),
                    1.0,
                    0.0,
                    ("spread_bps",),
                )
            )
        components = self._with_legacy(components, candidate.legacy_scores, direction)
        components, score = self._normalize_components(components)
        if score < self.config.min_ranking_score:
            return None, "mean reversion ranking score is below threshold"
        return self._candidate(
            candidate,
            regime,
            OpportunityFamily.MEAN_REVERSION,
            direction,
            score,
            components,
            ("vwap_zscore", "nearest_confluence_score", "spread_bps"),
        ), None

    def _candidate(
        self,
        candidate: CandidateInput,
        regime: RegimeAssessment,
        family: OpportunityFamily,
        direction: Direction,
        score: float,
        components: list[ScoreComponent],
        used_features: tuple[str, ...],
    ) -> ScreenCandidate:
        metadata = [
            candidate.features.metadata[name]
            for name in used_features
            if name in candidate.features.metadata
            and candidate.features.values.get(name) is not None
        ]
        quality = (
            sum(item.quality_score for item in metadata) / len(metadata)
            if metadata
            else 0.0
        )
        warnings = tuple(
            f"{name}:{candidate.features.metadata[name].status.value}"
            for name in used_features
            if name in candidate.features.metadata
            and candidate.features.metadata[name].status is not MetricStatus.OK
        )
        return ScreenCandidate(
            candidate.features.symbol,
            direction,
            family,
            candidate.features.as_of,
            score,
            tuple(components),
            candidate.features.values,
            regime.label,
            quality,
            warnings,
            tuple(f"{family.value}:{component.name}" for component in components),
            candidate.legacy_scores,
            self.config.version,
        )

    def _with_legacy(
        self,
        components: list[ScoreComponent],
        legacy_scores: Mapping[str, float],
        direction: Direction,
    ) -> list[ScoreComponent]:
        if not legacy_scores:
            return components
        value = sum(legacy_scores.values()) / len(legacy_scores)
        if direction is Direction.SHORT:
            value = 100 - value
        return [
            *components,
            ScoreComponent(
                "legacy_research",
                value,
                self.config.legacy_weight,
                0.0,
                tuple(sorted(f"legacy:{name}" for name in legacy_scores)),
            ),
        ]

    @staticmethod
    def _normalize_components(
        components: list[ScoreComponent],
    ) -> tuple[list[ScoreComponent], float]:
        base = [
            component for component in components if component.name != "legacy_research"
        ]
        legacy = [
            component for component in components if component.name == "legacy_research"
        ]
        legacy_weight = legacy[0].weight if legacy else 0.0
        base_weight = (1.0 - legacy_weight) / len(base)
        normalized: list[ScoreComponent] = []
        for component in base:
            contribution = component.value * base_weight
            normalized.append(
                ScoreComponent(
                    component.name,
                    component.value,
                    base_weight,
                    contribution,
                    component.source_features,
                )
            )
        if legacy:
            contribution = legacy[0].value * legacy_weight
            normalized.append(
                ScoreComponent(
                    legacy[0].name,
                    legacy[0].value,
                    legacy_weight,
                    contribution,
                    legacy[0].source_features,
                )
            )
        return normalized, sum(component.contribution for component in normalized)

    @staticmethod
    def _signal(features: FeatureRecord, name: str, transform) -> float | None:
        value = ScreeningEngine._value(features, name)
        return None if value is None else float(transform(value))

    @staticmethod
    def _value(features: FeatureRecord, name: str) -> float | None:
        value = features.values.get(name)
        metadata = features.metadata.get(name)
        if (
            value is None
            or metadata is None
            or metadata.status
            not in {MetricStatus.OK, MetricStatus.DEGRADED, MetricStatus.PARTIAL}
        ):
            return None
        return float(value)

    @staticmethod
    def _clip_signed(value: float) -> float:
        return max(-1.0, min(1.0, value))

    @staticmethod
    def _clip_100(value: float) -> float:
        return max(0.0, min(100.0, value))


class ThesisBuilder:
    def build(
        self,
        candidate: ScreenCandidate,
        screen: ScreenResult,
        *,
        suggested_notional: float = 10_000.0,
        intended_horizon: str = "swing",
    ) -> TradeThesis:
        if candidate not in screen.candidates:
            raise ValueError("candidate does not belong to the supplied screen")
        price = candidate.raw_features.get("midprice")
        if price is None or price <= 0:
            raise ValueError(
                "current midpoint is unavailable; cannot create position request"
            )
        evidence = tuple(
            f"feature:{name}@{candidate.as_of.isoformat()}"
            for component in candidate.score_components
            for name in component.source_features
            if not name.startswith("legacy:")
        )
        core = {
            "screen_id": screen.screen_id,
            "symbol": candidate.symbol,
            "direction": candidate.direction,
            "family": candidate.family,
            "as_of": candidate.as_of,
            "evidence": evidence,
        }
        thesis_id = content_identity(core)
        request = PositionRequest(
            candidate.symbol,
            candidate.direction,
            float(price),
            suggested_notional,
            1.0,
            candidate.as_of,
        )
        observed = (
            f"ranking_score={candidate.ranking_score:.4f}",
            f"regime={candidate.regime.value}",
            f"midprice={float(price):.6f}",
        )
        calculations = tuple(
            f"{component.name}={component.value:.4f} weight={component.weight:.4f} contribution={component.contribution:.4f}"
            for component in candidate.score_components
        )
        return TradeThesis(
            thesis_id,
            1,
            candidate.as_of,
            candidate.as_of,
            screen.screen_id,
            candidate.symbol,
            candidate.direction,
            candidate.family,
            intended_horizon,
            candidate.regime,
            observed,
            calculations,
            (
                "ranking score is a deterministic ordering metric, not a probability of profit",
                "displayed midpoint is a research reference and not an executable fill",
            ),
            (f"{candidate.family.value} evidence is directionally aligned",),
            (
                f"screen:{screen.screen_id}",
                *(
                    f"snapshot:{name}:{identity}"
                    for name, identity in sorted(screen.input_snapshot_refs.items())
                ),
                *evidence,
            ),
            ("re-evaluate the same evidence at entry time",),
            ("invalidate when required evidence becomes stale or unavailable",),
            ("exit logic remains strategy-specific and must be approved separately",),
            None,
            None,
            candidate.warnings,
            (
                "expected move is unavailable without a matched horizon and supported current reference",
            ),
            candidate.data_quality,
            request,
        )


class RiskEngine:
    def __init__(self, policy: RiskPolicy | None = None) -> None:
        self.policy = policy or RiskPolicy()

    def decide(
        self,
        request: PositionRequest,
        portfolio: PortfolioState,
        risk_context: PortfolioRiskContext | None = None,
    ) -> RiskDecision:
        requested_quantity = request.requested_notional / request.price
        if portfolio.as_of > request.as_of:
            return self._closed(
                request,
                portfolio,
                requested_quantity,
                RiskDecisionStatus.UNAVAILABLE,
                "portfolio state is from the future relative to the request",
            )
        if request.as_of - portfolio.as_of > self.policy.max_state_age:
            return self._closed(
                request,
                portfolio,
                requested_quantity,
                RiskDecisionStatus.UNAVAILABLE,
                "portfolio state is stale",
            )
        if request.symbol in self.policy.restricted_symbols:
            return self._closed(
                request,
                portfolio,
                requested_quantity,
                RiskDecisionStatus.REJECTED,
                "instrument is restricted by risk policy",
            )
        if request.direction is Direction.SHORT and not self.policy.allow_short:
            return self._closed(
                request,
                portfolio,
                requested_quantity,
                RiskDecisionStatus.REJECTED,
                "short positions are disabled by risk policy",
            )

        context_error = self._validate_risk_context(request, portfolio, risk_context)
        if context_error is not None:
            return self._closed(
                request,
                portfolio,
                requested_quantity,
                RiskDecisionStatus.UNAVAILABLE,
                context_error,
            )

        positions = list(portfolio.positions)
        pending = list(portfolio.pending_orders)
        current_symbol = sum(
            abs(item.notional) for item in positions if item.symbol == request.symbol
        )
        current_symbol += sum(
            abs(item.signed_notional)
            for item in pending
            if item.symbol == request.symbol
        )
        gross = sum(abs(item.notional) for item in positions) + sum(
            abs(item.signed_notional) for item in pending
        )
        net = sum(item.notional for item in positions) + sum(
            item.signed_notional for item in pending
        )
        pending_buy_commitment = sum(max(0.0, item.signed_notional) for item in pending)
        single_room = max(
            0.0,
            portfolio.equity * self.policy.max_single_name_fraction - current_symbol,
        )
        gross_room = max(0.0, portfolio.equity * self.policy.max_gross_fraction - gross)
        cash_room = max(
            0.0,
            portfolio.cash
            - pending_buy_commitment
            - portfolio.equity * self.policy.min_cash_fraction,
        )
        if request.direction is Direction.LONG:
            net_room = max(0.0, portfolio.equity * self.policy.max_net_fraction - net)
        else:
            net_room = max(0.0, portfolio.equity * self.policy.max_net_fraction + net)
            cash_room = request.requested_notional
        rooms = {
            "single_name_cap": single_room,
            "gross_exposure_cap": gross_room,
            "net_exposure_cap": net_room,
            "cash_reserve": cash_room,
        }
        if risk_context is not None:
            try:
                rooms.update(
                    self._advanced_rooms(
                        request,
                        portfolio,
                        risk_context,
                        positions,
                        pending,
                    )
                )
            except ValueError as exc:
                return self._closed(
                    request,
                    portfolio,
                    requested_quantity,
                    RiskDecisionStatus.UNAVAILABLE,
                    str(exc),
                )
        approved_limit = min(request.requested_notional, *rooms.values())
        raw_quantity = approved_limit / request.price
        quantity = floor(raw_quantity / request.lot_size) * request.lot_size
        quantity = max(0.0, quantity)
        approved_notional = quantity * request.price
        binding = tuple(
            name
            for name, room in rooms.items()
            if room <= approved_limit + request.price * request.lot_size
        )
        before = self._exposure(
            portfolio.equity, gross, net, current_symbol, portfolio.cash
        )
        signed = (
            approved_notional
            if request.direction is Direction.LONG
            else -approved_notional
        )
        after = self._exposure(
            portfolio.equity,
            gross + approved_notional,
            net + signed,
            current_symbol + approved_notional,
            portfolio.cash - approved_notional
            if request.direction is Direction.LONG
            else portfolio.cash,
        )
        if quantity <= 0:
            status = RiskDecisionStatus.REJECTED
            reasons = (
                "no quantity fits the configured risk constraints after lot rounding",
            )
            expiry = None
        elif approved_notional + 1e-9 < request.requested_notional:
            status = RiskDecisionStatus.RESIZED
            reasons = (
                "requested allocation was resized to satisfy binding constraints",
            )
            expiry = request.as_of + self.policy.approval_ttl
        else:
            status = RiskDecisionStatus.APPROVED
            reasons = ("requested allocation satisfies current risk constraints",)
            expiry = request.as_of + self.policy.approval_ttl
        decision_id = content_identity(
            {
                "request": request,
                "portfolio": portfolio,
                "policy_version": self.policy.version,
                "approved_notional": approved_notional,
                "status": status,
            }
        )
        return RiskDecision(
            decision_id,
            status,
            request.symbol,
            requested_quantity,
            quantity,
            request.requested_notional,
            approved_notional,
            binding,
            before,
            after,
            request.as_of,
            portfolio.as_of,
            self.policy.version,
            reasons,
            expiry,
        )

    def _validate_risk_context(
        self,
        request: PositionRequest,
        portfolio: PortfolioState,
        context: PortfolioRiskContext | None,
    ) -> str | None:
        advanced = any(
            value is not None
            for value in (
                self.policy.max_sector_fraction,
                self.policy.max_correlated_fraction,
                self.policy.max_annualized_volatility,
            )
        )
        if not advanced:
            return None
        if context is None:
            return "advanced portfolio constraints require point-in-time risk context"
        if context.as_of > request.as_of:
            return "portfolio risk context is from the future relative to the request"
        if request.as_of - context.as_of > self.policy.max_risk_data_age:
            return "portfolio risk context is stale"

        exposed_symbols = {
            item.symbol for item in portfolio.positions if item.notional != 0
        } | {
            item.symbol
            for item in portfolio.pending_orders
            if item.signed_notional != 0
        }
        exposed_symbols.add(request.symbol)
        if self.policy.max_sector_fraction is not None:
            missing = sorted(exposed_symbols - context.sector_by_symbol.keys())
            if missing:
                return f"sector mapping is unavailable for {missing[0]}"

        needs_returns = self.policy.max_annualized_volatility is not None or (
            self.policy.max_correlated_fraction is not None
            and bool(exposed_symbols - {request.symbol})
        )
        if not needs_returns:
            return None
        for symbol in exposed_symbols:
            observations = context.returns_by_symbol.get(symbol)
            if observations is None:
                return f"trailing return history is unavailable for {symbol}"
            usable = [item for item in observations if item.as_of <= request.as_of]
            if len(usable) < self.policy.min_risk_observations:
                return f"insufficient trailing return history for {symbol}"
            if request.as_of - usable[-1].as_of > self.policy.max_risk_data_age:
                return f"trailing return history is stale for {symbol}"
        return None

    def _advanced_rooms(
        self,
        request: PositionRequest,
        portfolio: PortfolioState,
        context: PortfolioRiskContext,
        positions: list[PositionState],
        pending: list[PendingOrderState],
    ) -> dict[str, float]:
        rooms: dict[str, float] = {}
        current_by_symbol: dict[str, float] = {}
        for item in positions:
            if item.notional != 0:
                current_by_symbol[item.symbol] = (
                    current_by_symbol.get(item.symbol, 0.0) + item.notional
                )
        for pending_order in pending:
            if pending_order.signed_notional != 0:
                current_by_symbol[pending_order.symbol] = (
                    current_by_symbol.get(pending_order.symbol, 0.0)
                    + pending_order.signed_notional
                )

        if self.policy.max_sector_fraction is not None:
            sector = context.sector_by_symbol[request.symbol]
            sector_exposure = sum(
                abs(notional)
                for symbol, notional in current_by_symbol.items()
                if context.sector_by_symbol[symbol] == sector
            )
            rooms["sector_concentration_cap"] = max(
                0.0,
                portfolio.equity * self.policy.max_sector_fraction - sector_exposure,
            )

        if self.policy.max_correlated_fraction is not None:
            threshold = self.policy.max_pair_correlation
            if threshold is None:
                threshold = 0.80
            correlated_exposure = 0.0
            for symbol, notional in current_by_symbol.items():
                if symbol == request.symbol or notional == 0:
                    continue
                correlation = self._correlation(
                    request.symbol, symbol, request.as_of, context
                )
                if correlation is None:
                    raise ValueError(
                        f"undefined trailing correlation for {request.symbol}/{symbol}"
                    )
                if abs(correlation) >= threshold:
                    correlated_exposure += abs(notional)
            rooms["correlated_cluster_cap"] = max(
                0.0,
                portfolio.equity * self.policy.max_correlated_fraction
                - correlated_exposure,
            )

        if self.policy.max_annualized_volatility is not None:
            rooms["portfolio_volatility_cap"] = self._volatility_room(
                request, portfolio, context, current_by_symbol
            )
        return rooms

    def _aligned_returns(
        self,
        symbols: tuple[str, ...],
        decision_time,
        context: PortfolioRiskContext,
    ) -> list[tuple[float, ...]]:
        by_symbol = {
            symbol: {
                item.as_of: item.value
                for item in context.returns_by_symbol[symbol]
                if item.as_of <= decision_time
            }
            for symbol in symbols
        }
        common = set.intersection(*(set(values) for values in by_symbol.values()))
        ordered = sorted(common)[-self.policy.risk_lookback :]
        if len(ordered) < self.policy.min_risk_observations:
            raise ValueError("insufficient aligned trailing return history")
        return [
            tuple(by_symbol[symbol][timestamp] for symbol in symbols)
            for timestamp in ordered
        ]

    def _correlation(
        self,
        left: str,
        right: str,
        decision_time,
        context: PortfolioRiskContext,
    ) -> float | None:
        rows = self._aligned_returns((left, right), decision_time, context)
        left_values = [row[0] for row in rows]
        right_values = [row[1] for row in rows]
        left_mean = sum(left_values) / len(left_values)
        right_mean = sum(right_values) / len(right_values)
        left_ss = sum((value - left_mean) ** 2 for value in left_values)
        right_ss = sum((value - right_mean) ** 2 for value in right_values)
        if left_ss == 0 or right_ss == 0:
            return None
        covariance = sum(
            (left_value - left_mean) * (right_value - right_mean)
            for left_value, right_value in zip(left_values, right_values, strict=True)
        )
        return covariance / sqrt(left_ss * right_ss)

    def _volatility_room(
        self,
        request: PositionRequest,
        portfolio: PortfolioState,
        context: PortfolioRiskContext,
        current_by_symbol: dict[str, float],
    ) -> float:
        symbols = tuple(sorted(set(current_by_symbol) | {request.symbol}))
        rows = self._aligned_returns(symbols, request.as_of, context)
        limit = self.policy.max_annualized_volatility
        assert limit is not None
        means = [sum(row[i] for row in rows) / len(rows) for i in range(len(symbols))]
        denominator = len(rows) - 1
        covariances = [
            [
                sum((row[i] - means[i]) * (row[j] - means[j]) for row in rows)
                / denominator
                for j in range(len(symbols))
            ]
            for i in range(len(symbols))
        ]

        def volatility(candidate_notional: float) -> float:
            notionals = dict(current_by_symbol)
            signed = (
                candidate_notional
                if request.direction is Direction.LONG
                else -candidate_notional
            )
            notionals[request.symbol] = notionals.get(request.symbol, 0.0) + signed
            weights = [
                notionals.get(symbol, 0.0) / portfolio.equity for symbol in symbols
            ]
            variance = 0.0
            for i, left_weight in enumerate(weights):
                for j, right_weight in enumerate(weights):
                    variance += left_weight * right_weight * covariances[i][j]
            return sqrt(max(0.0, variance) * self.policy.annualization_factor)

        if volatility(0.0) > limit + 1e-12:
            return 0.0
        if volatility(request.requested_notional) <= limit + 1e-12:
            return request.requested_notional
        low, high = 0.0, request.requested_notional
        for _ in range(50):
            midpoint = (low + high) / 2
            if volatility(midpoint) <= limit:
                low = midpoint
            else:
                high = midpoint
        return low

    def _closed(
        self,
        request: PositionRequest,
        portfolio: PortfolioState,
        requested_quantity: float,
        status: RiskDecisionStatus,
        reason: str,
    ) -> RiskDecision:
        gross = sum(abs(item.notional) for item in portfolio.positions) + sum(
            abs(item.signed_notional) for item in portfolio.pending_orders
        )
        net = sum(item.notional for item in portfolio.positions) + sum(
            item.signed_notional for item in portfolio.pending_orders
        )
        symbol = sum(
            abs(item.notional)
            for item in portfolio.positions
            if item.symbol == request.symbol
        )
        symbol += sum(
            abs(item.signed_notional)
            for item in portfolio.pending_orders
            if item.symbol == request.symbol
        )
        before = self._exposure(portfolio.equity, gross, net, symbol, portfolio.cash)
        decision_id = content_identity(
            {
                "request": request,
                "portfolio": portfolio,
                "policy_version": self.policy.version,
                "status": status,
                "reason": reason,
            }
        )
        return RiskDecision(
            decision_id,
            status,
            request.symbol,
            requested_quantity,
            0.0,
            request.requested_notional,
            0.0,
            (),
            before,
            before,
            request.as_of,
            portfolio.as_of,
            self.policy.version,
            (reason,),
            None,
        )

    @staticmethod
    def _exposure(
        equity: float, gross: float, net: float, symbol: float, cash: float
    ) -> dict[str, float]:
        return {
            "gross_fraction": gross / equity,
            "net_fraction": net / equity,
            "single_name_fraction": symbol / equity,
            "cash_fraction": cash / equity,
        }
