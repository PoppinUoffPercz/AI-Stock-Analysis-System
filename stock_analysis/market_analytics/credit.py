"""Deterministic credit stress, credit volatility, and regime context."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from statistics import mean
from typing import Any

from .config import AnalyticsConfig
from .models import MetricMetadata, MetricResult, MetricStatus, Provenance, _require_utc
from .volatility import VolatilityState


class CreditAlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class CreditStressLabel(StrEnum):
    BENIGN = "benign"
    ELEVATED = "elevated"
    STRESSED = "stressed"
    CRISIS = "crisis"
    SYSTEMIC = "systemic"
    UNAVAILABLE = "unavailable"


class CreditRegime(StrEnum):
    CALM = "calm"
    COMPLACENCY_DIVERGENCE = "complacency_divergence"
    REPRICING = "repricing"
    CRISIS = "crisis"
    VOLATILITY_ONLY = "volatility_only"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class CreditAlert:
    ticker: str
    title: str
    severity: CreditAlertSeverity
    published_at: datetime
    source: str | None = None

    def __post_init__(self) -> None:
        if not self.ticker or not self.title:
            raise ValueError("credit alert ticker and title are required")
        object.__setattr__(self, "severity", CreditAlertSeverity(self.severity))
        _require_utc(self.published_at, "credit alert published_at")


@dataclass(frozen=True, slots=True)
class CreditObservation:
    as_of: datetime
    provider: str
    two_ten_slope_pct: float | None
    treasury_30y_pct: float | None
    treasury_30y_history: tuple[float, ...] = ()
    hy_spread_bps: float | None = None
    hy_spread_history: tuple[float, ...] = ()
    ig_spread_bps: float | None = None
    ig_spread_history: tuple[float, ...] = ()
    sofr_pct: float | None = None
    private_credit_alerts: tuple[CreditAlert, ...] | None = None
    hy_spread_methodology: str = "HY spread methodology not declared"
    ig_spread_methodology: str = "IG spread methodology not declared"

    @classmethod
    def from_legacy_monitor(
        cls,
        monitor: Any,
        as_of: datetime,
        *,
        provider: str = "credit_monitor",
    ) -> CreditObservation:
        """Adapt the legacy monitor's in-memory state without copying its score.

        The legacy monitor uses fallback scores for missing inputs and its
        news records do not always contain publication timestamps. The typed
        boundary keeps those facts unavailable instead of treating them as
        observed values.
        """
        _require_utc(as_of, "legacy credit observation as_of")
        yields = getattr(monitor, "yields", {}) or {}
        spreads = getattr(monitor, "spreads", {}) or {}
        yield_history = getattr(monitor, "yield_history", {}) or {}
        spread_history = getattr(monitor, "spread_history", {}) or {}

        def yield_value(name: str) -> float | None:
            return _mapping_value(yields.get(name), "value")

        def history_values(source: Any, name: str) -> tuple[float, ...]:
            value = source.get(name) if isinstance(source, Mapping) else None
            if not isinstance(value, (tuple, list)):
                return ()
            result: list[float] = []
            for item in value:
                try:
                    numeric = float(item)
                except (TypeError, ValueError):
                    continue
                if isfinite(numeric):
                    result.append(numeric)
            return tuple(result)

        y2 = yield_value("2Y")
        y10 = yield_value("10Y")
        alerts = _legacy_alerts(getattr(monitor, "private_credit_alerts", ()))
        return cls(
            as_of=as_of,
            provider=provider,
            two_ten_slope_pct=None if y2 is None or y10 is None else y10 - y2,
            treasury_30y_pct=yield_value("30Y"),
            treasury_30y_history=history_values(yield_history, "30Y"),
            hy_spread_bps=_mapping_value(spreads.get("HYG"), "spread_bps"),
            hy_spread_history=history_values(spread_history, "HYG"),
            ig_spread_bps=_mapping_value(spreads.get("LQD"), "spread_bps"),
            ig_spread_history=history_values(spread_history, "LQD"),
            sofr_pct=getattr(monitor, "sofr", None),
            private_credit_alerts=alerts,
            hy_spread_methodology="legacy HYG ETF yield minus IEF yield proxy",
            ig_spread_methodology="legacy LQD ETF yield minus IEF yield proxy",
        )

    def __post_init__(self) -> None:
        _require_utc(self.as_of, "credit observation as_of")
        if not self.provider:
            raise ValueError("credit observation provider is required")
        for value, label in (
            (self.two_ten_slope_pct, "two_ten_slope_pct"),
            (self.treasury_30y_pct, "treasury_30y_pct"),
            (self.hy_spread_bps, "hy_spread_bps"),
            (self.ig_spread_bps, "ig_spread_bps"),
            (self.sofr_pct, "sofr_pct"),
        ):
            if value is not None and not isfinite(value):
                raise ValueError(f"{label} must be finite")
        for history, label in (
            (self.treasury_30y_history, "treasury_30y_history"),
            (self.hy_spread_history, "hy_spread_history"),
            (self.ig_spread_history, "ig_spread_history"),
        ):
            if any(not isfinite(value) for value in history):
                raise ValueError(f"{label} values must be finite")
        object.__setattr__(
            self,
            "private_credit_alerts",
            None
            if self.private_credit_alerts is None
            else tuple(self.private_credit_alerts),
        )


@dataclass(frozen=True, slots=True)
class CreditStressState:
    as_of: datetime
    composite: MetricResult[float]
    label: CreditStressLabel
    components: Mapping[str, MetricResult[float]]
    weights: Mapping[str, float]
    coverage: float
    active_alerts: tuple[CreditAlert, ...]
    metadata: MetricMetadata


@dataclass(frozen=True, slots=True)
class CreditVolatilityState:
    as_of: datetime
    symbol_states: Mapping[str, VolatilityState]
    iv_rank: MetricResult[float]
    iv_rv_ratio: MetricResult[float]
    metadata: MetricMetadata


@dataclass(frozen=True, slots=True)
class CreditRegimeState:
    as_of: datetime
    stress: CreditStressState
    volatility: CreditVolatilityState | None
    regime: CreditRegime
    metadata: MetricMetadata


class CreditStressEngine:
    _names = (
        "yield_curve",
        "treasury_30y",
        "hy_spread",
        "ig_spread",
        "sofr",
        "private_credit",
    )

    def __init__(self, config: AnalyticsConfig) -> None:
        self.config = config

    def calculate(self, observation: CreditObservation) -> CreditStressState:
        c = observation
        components = {
            "yield_curve": self._score_yield_curve(c),
            "treasury_30y": self._score_30y(c),
            "hy_spread": self._score_spread(
                c, c.hy_spread_bps, c.hy_spread_history, c.hy_spread_methodology, "HY"
            ),
            "ig_spread": self._score_spread(
                c, c.ig_spread_bps, c.ig_spread_history, c.ig_spread_methodology, "IG"
            ),
            "sofr": self._score_sofr(c),
            "private_credit": self._score_private_credit(c),
        }
        weights = dict(
            zip(self._names, self.config.credit.component_weights, strict=True)
        )
        available_weight = sum(
            weights[name]
            for name, metric in components.items()
            if metric.value is not None
        )
        if available_weight < self.config.credit.min_weight_coverage:
            composite = self._unavailable(
                c, "credit_stress", "configured credit input coverage is below minimum"
            )
            label = CreditStressLabel.UNAVAILABLE
        else:
            value = (
                sum(
                    weights[name] * metric.value
                    for name, metric in components.items()
                    if metric.value is not None
                )
                / available_weight
            )
            status = (
                MetricStatus.OK
                if available_weight == 1.0
                and all(
                    metric.metadata.status is MetricStatus.OK
                    for metric in components.values()
                )
                else MetricStatus.DEGRADED
            )
            composite = self._metric(
                value,
                c,
                "credit_stress",
                "weighted credit stress composite with available-weight renormalization",
                status=status,
                quality=100.0 if status is MetricStatus.OK else 75.0,
                reason=None
                if status is MetricStatus.OK
                else "one or more credit inputs or histories are incomplete",
            )
            label = self._label(value)
        active = self._active_alerts(c)
        metadata = composite.metadata
        return CreditStressState(
            c.as_of,
            composite,
            label,
            components,
            weights,
            available_weight,
            active,
            metadata,
        )

    def _score_yield_curve(self, observation: CreditObservation) -> MetricResult[float]:
        value = observation.two_ten_slope_pct
        if value is None:
            return self._unavailable(
                observation, "credit_yield_curve", "2s10s slope is unavailable"
            )
        if value < -0.75:
            score = 90.0
        elif value < -0.50:
            score = 75.0
        elif value < -0.25:
            score = 55.0
        elif value < 0:
            score = 40.0
        elif value < 0.50:
            score = 20.0
        elif value < 1.00:
            score = 30.0
        else:
            score = 45.0
        return self._metric(
            score,
            observation,
            "credit_yield_curve",
            "2s10s slope stress score",
            reason=None,
        )

    def _score_30y(self, observation: CreditObservation) -> MetricResult[float]:
        value = observation.treasury_30y_pct
        if value is None:
            return self._unavailable(
                observation, "credit_treasury_30y", "30Y Treasury level is unavailable"
            )
        history = observation.treasury_30y_history
        if history and max(history) > min(history):
            score = 100.0 * (value - min(history)) / (max(history) - min(history))
            return self._metric(
                max(0.0, min(100.0, score)),
                observation,
                "credit_treasury_30y",
                "30Y Treasury historical rank",
                status=MetricStatus.OK,
            )
        if value >= 5.5:
            score = 100.0
        elif value >= 5.0:
            score = 75.0
        elif value >= 4.5:
            score = 50.0
        elif value >= 4.0:
            score = 30.0
        elif value >= 3.5:
            score = 15.0
        else:
            score = 5.0
        return self._metric(
            score,
            observation,
            "credit_treasury_30y",
            "30Y Treasury absolute threshold without historical context",
            status=MetricStatus.DEGRADED,
            quality=75.0,
            reason="30Y Treasury history is unavailable",
        )

    def _score_spread(
        self,
        observation: CreditObservation,
        value: float | None,
        history: tuple[float, ...],
        methodology: str,
        label: str,
    ) -> MetricResult[float]:
        if value is None:
            return self._unavailable(
                observation, "credit_spread", f"{label} spread is unavailable"
            )
        if label == "HY":
            thresholds: tuple[tuple[int, float], ...] = (
                (800, 100),
                (600, 80),
                (500, 65),
                (400, 50),
                (300, 35),
                (200, 20),
            )
        else:
            thresholds = ((300, 100), (200, 70), (150, 45), (100, 25), (75, 15))
        absolute = next(
            (score for cutoff, score in thresholds if value >= cutoff),
            10 if label == "HY" else 8,
        )
        if history and max(history) > min(history):
            percentile = 100.0 * (value - min(history)) / (max(history) - min(history))
            score = absolute * 0.7 + max(0.0, min(100.0, percentile)) * 0.3
            return self._metric(
                score,
                observation,
                "credit_spread",
                f"{methodology}; absolute spread score blended with trailing percentile",
                status=MetricStatus.OK,
            )
        return self._metric(
            float(absolute),
            observation,
            "credit_spread",
            f"{methodology}; absolute spread score only",
            status=MetricStatus.DEGRADED,
            quality=75.0,
            reason="spread history is unavailable",
        )

    def _score_sofr(self, observation: CreditObservation) -> MetricResult[float]:
        value = observation.sofr_pct
        if value is None:
            return self._unavailable(observation, "credit_sofr", "SOFR is unavailable")
        score = 5.0
        for cutoff, candidate in (
            (5.5, 80),
            (5.0, 60),
            (4.0, 40),
            (3.0, 20),
            (2.0, 10),
        ):
            if value >= cutoff:
                score = candidate
                break
        return self._metric(
            float(score),
            observation,
            "credit_sofr",
            "SOFR level stress score",
            reason=None,
        )

    def _score_private_credit(
        self, observation: CreditObservation
    ) -> MetricResult[float]:
        alerts = observation.private_credit_alerts
        if alerts is None:
            return self._unavailable(
                observation,
                "credit_private_news",
                "private credit news input is unavailable",
            )
        active = self._active_alerts(observation)
        if not active:
            return self._metric(
                5.0,
                observation,
                "credit_private_news",
                "no active private-credit alerts in configured publication window",
                reason=None,
            )
        critical = any(
            alert.severity is CreditAlertSeverity.CRITICAL for alert in active
        )
        warning = any(alert.severity is CreditAlertSeverity.WARNING for alert in active)
        count = len(active)
        if critical and count >= 5:
            score = 95.0
        elif critical:
            score = 80.0
        elif warning and count >= 5:
            score = 70.0
        elif warning:
            score = 55.0
        elif count >= 5:
            score = 40.0
        elif count >= 2:
            score = 25.0
        else:
            score = 15.0
        return self._metric(
            score,
            observation,
            "credit_private_news",
            "active private-credit alert severity and count",
            reason=None,
        )

    def _active_alerts(self, observation: CreditObservation) -> tuple[CreditAlert, ...]:
        if observation.private_credit_alerts is None:
            return ()
        max_age = self.config.credit.active_news_days * 24 * 60 * 60
        return tuple(
            alert
            for alert in observation.private_credit_alerts
            if 0 <= (observation.as_of - alert.published_at).total_seconds() <= max_age
        )

    def _label(self, value: float) -> CreditStressLabel:
        if value < 20:
            return CreditStressLabel.BENIGN
        if value < self.config.credit.stressed_threshold:
            return CreditStressLabel.ELEVATED
        if value < self.config.credit.crisis_threshold:
            return CreditStressLabel.STRESSED
        if value < self.config.credit.systemic_threshold:
            return CreditStressLabel.CRISIS
        return CreditStressLabel.SYSTEMIC

    def _metric(
        self,
        value: float,
        observation: CreditObservation,
        dataset: str,
        methodology: str,
        *,
        provider: str | None = None,
        status: MetricStatus = MetricStatus.OK,
        quality: float = 100.0,
        reason: str | None = None,
    ) -> MetricResult[float]:
        return MetricResult(
            value,
            MetricMetadata(
                as_of=observation.as_of,
                provider=provider or observation.provider,
                dataset=dataset,
                venue_scope="macro",
                status=status,
                methodology=methodology,
                quality_score=quality,
                observed_or_modeled=Provenance.DERIVED_FROM_OBSERVED,
                reason=reason,
            ),
        )

    def _unavailable(
        self, observation: CreditObservation, dataset: str, reason: str
    ) -> MetricResult[float]:
        return MetricResult(
            None,
            MetricMetadata.unavailable(
                as_of=observation.as_of,
                provider=observation.provider,
                dataset=dataset,
                venue_scope="macro",
                reason=reason,
            ),
        )


class CreditVolatilityEngine:
    def summarize(
        self,
        symbol_states: Mapping[str, VolatilityState],
        as_of: datetime | None = None,
    ) -> CreditVolatilityState:
        if as_of is not None:
            _require_utc(as_of, "credit volatility as_of")
        if not symbol_states:
            now = as_of or datetime(1970, 1, 1, tzinfo=UTC)
            unavailable = MetricMetadata.unavailable(
                as_of=now,
                provider="analytics",
                dataset="credit_volatility",
                venue_scope="macro",
                reason="no credit ETF volatility states",
            )
            missing: MetricResult[float] = MetricResult(None, unavailable)
            return CreditVolatilityState(now, {}, missing, missing, unavailable)
        cutoff = as_of or max(state.as_of for state in symbol_states.values())
        eligible_states = {
            symbol: state
            for symbol, state in symbol_states.items()
            if state.as_of <= cutoff
        }
        if not eligible_states:
            unavailable = MetricMetadata.unavailable(
                as_of=cutoff,
                provider="analytics",
                dataset="credit_volatility",
                venue_scope="macro",
                reason="all credit ETF volatility states are after the requested as_of",
            )
            missing = MetricResult(None, unavailable)
            return CreditVolatilityState(cutoff, {}, missing, missing, unavailable)
        observation_as_of = max(state.as_of for state in eligible_states.values())
        ranks: list[float] = []
        ratios: list[float] = []
        for state in eligible_states.values():
            contexts = state.iv_history.get(30)
            if contexts is None:
                contexts = next(iter(state.iv_history.values()), {})
            if contexts:
                context = contexts[max(contexts)]
                if (
                    context.rank.value is not None
                    and context.rank.metadata.as_of <= cutoff
                ):
                    ranks.append(context.rank.value)
            comparison = state.iv_rv.get(30) or next(iter(state.iv_rv.values()), None)
            if (
                comparison is not None
                and comparison.ratio.value is not None
                and comparison.ratio.metadata.as_of <= cutoff
            ):
                ratios.append(comparison.ratio.value)
        rank = self._aggregate(
            ranks, observation_as_of, "credit ETF implied-volatility rank"
        )
        ratio = self._aggregate(ratios, observation_as_of, "credit ETF IV/RV ratio")
        metadata = MetricMetadata(
            as_of=observation_as_of,
            provider="analytics",
            dataset="credit_volatility",
            venue_scope="macro",
            status=MetricStatus.OK if ranks or ratios else MetricStatus.UNAVAILABLE,
            methodology="mean across supplied credit ETF volatility states at or before as_of",
            quality_score=100.0
            if ranks and ratios
            else 50.0
            if ranks or ratios
            else 0.0,
            observed_or_modeled=Provenance.DERIVED_FROM_OBSERVED,
            reason=None
            if ranks and ratios
            else "one or more credit ETF volatility aggregates are unavailable",
        )
        return CreditVolatilityState(
            observation_as_of, eligible_states, rank, ratio, metadata
        )

    def _aggregate(
        self, values: list[float], as_of: datetime, methodology: str
    ) -> MetricResult[float]:
        if not values:
            return MetricResult(
                None,
                MetricMetadata.unavailable(
                    as_of=as_of,
                    provider="analytics",
                    dataset="credit_volatility",
                    venue_scope="macro",
                    reason=f"{methodology} has no valid inputs",
                ),
            )
        return MetricResult(
            mean(values),
            MetricMetadata(
                as_of=as_of,
                provider="analytics",
                dataset="credit_volatility",
                venue_scope="macro",
                status=MetricStatus.OK,
                methodology=methodology,
                quality_score=100.0,
                observed_or_modeled=Provenance.DERIVED_FROM_OBSERVED,
            ),
        )


class CreditRegimeEngine:
    def __init__(self, config: AnalyticsConfig) -> None:
        self.config = config

    def classify(
        self, stress: CreditStressState, volatility: CreditVolatilityState | None
    ) -> CreditRegimeState:
        if volatility is not None and volatility.as_of > stress.as_of:
            raise ValueError("credit volatility context is from the future")
        value = stress.composite.value
        if value is None:
            regime = CreditRegime.UNAVAILABLE
        else:
            rank = volatility.iv_rank.value if volatility is not None else None
            ratio = volatility.iv_rv_ratio.value if volatility is not None else None
            high_vol = (
                rank is not None
                and rank >= self.config.credit.repricing_iv_rank_threshold
            ) or (
                ratio is not None and ratio >= self.config.credit.repricing_iv_rv_ratio
            )
            low_vol = (
                rank is not None
                and rank <= self.config.credit.complacency_iv_rank_threshold
            )
            if value >= self.config.credit.crisis_threshold and high_vol:
                regime = CreditRegime.CRISIS
            elif value >= self.config.credit.stressed_threshold and low_vol:
                regime = CreditRegime.COMPLACENCY_DIVERGENCE
            elif value >= self.config.credit.stressed_threshold and high_vol:
                regime = CreditRegime.REPRICING
            elif value < self.config.credit.stressed_threshold and high_vol:
                regime = CreditRegime.VOLATILITY_ONLY
            else:
                regime = CreditRegime.CALM
        metadata = MetricMetadata(
            as_of=stress.as_of,
            provider="analytics",
            dataset="credit_regime",
            venue_scope="macro",
            status=MetricStatus.OK if value is not None else MetricStatus.UNAVAILABLE,
            methodology="credit stress compared with credit ETF volatility state",
            quality_score=stress.composite.metadata.quality_score,
            observed_or_modeled=Provenance.DERIVED_FROM_OBSERVED,
            reason=None
            if value is not None
            else "credit stress composite is unavailable",
        )
        return CreditRegimeState(stress.as_of, stress, volatility, regime, metadata)


def _mapping_value(value: Any, key: str) -> float | None:
    if not isinstance(value, Mapping):
        return None
    candidate = value.get(key)
    if candidate is None:
        return None
    try:
        candidate = float(candidate)
    except (TypeError, ValueError):
        return None
    return candidate if isfinite(candidate) else None


def _legacy_alerts(value: Any) -> tuple[CreditAlert, ...] | None:
    if not value:
        return ()
    converted: list[CreditAlert] = []
    for item in value:
        if isinstance(item, CreditAlert):
            converted.append(item)
            continue
        if not isinstance(item, Mapping):
            return None
        published = item.get("published_at")
        if published is None:
            return None
        if isinstance(published, str):
            try:
                published = datetime.fromisoformat(published)
            except ValueError:
                return None
        if not isinstance(published, datetime) or published.tzinfo is None:
            return None
        try:
            severity = CreditAlertSeverity(str(item.get("severity", "info")).lower())
        except ValueError:
            return None
        converted.append(
            CreditAlert(
                ticker=str(item.get("ticker", "legacy")),
                title=str(item.get("title", "legacy credit alert")),
                severity=severity,
                published_at=published.astimezone(UTC),
                source="credit_monitor",
            )
        )
    return tuple(converted)
