"""Deterministic, point-in-time flat features for research consumers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from typing import Any

from .levels import Level, LevelZone
from .models import (
    AnalyticsSnapshot,
    MetricMetadata,
    MetricResult,
    MetricStatus,
    _require_utc,
)
from .volatility import SkewState, VolatilityState


@dataclass(frozen=True, slots=True)
class FeatureRecord:
    """A flat feature vector with source metadata for every field."""

    symbol: str
    as_of: datetime
    values: Mapping[str, float | None]
    metadata: Mapping[str, MetricMetadata]
    categories: Mapping[str, str | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_utc(self.as_of, "feature record as_of")
        if not self.symbol:
            raise ValueError("feature record symbol must not be empty")
        values = dict(self.values)
        metadata = dict(self.metadata)
        categories = dict(self.categories)
        if set(values) != set(metadata):
            raise ValueError("feature values and metadata keys must match")
        for name, value in values.items():
            if not name:
                raise ValueError("feature names must not be empty")
            if value is not None and (
                not isinstance(value, (int, float)) or not isfinite(value)
            ):
                raise ValueError(f"feature {name} must be finite or None")
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "categories", categories)


def build_feature_record(snapshot: AnalyticsSnapshot) -> FeatureRecord:
    """Flatten a completed snapshot without introducing future information."""

    state = snapshot.volatility
    values: dict[str, float | None] = {}
    metadata: dict[str, MetricMetadata] = {}
    categories: dict[str, str | None] = {}

    def add(name: str, metric: MetricResult[Any] | None) -> None:
        if metric is None:
            add_unavailable(name, "source metric is unavailable")
            return
        _check_not_future(metric.metadata, snapshot.as_of, name)
        value = metric.value
        if value is not None and (
            not isinstance(value, (int, float)) or not isfinite(value)
        ):
            raise ValueError(f"source metric {name} is not finite")
        values[name] = value
        metadata[name] = metric.metadata

    def add_unavailable(name: str, reason: str) -> None:
        values[name] = None
        metadata[name] = MetricMetadata.unavailable(
            as_of=snapshot.as_of,
            provider="feature_exporter",
            dataset="features",
            venue_scope=_venue_scope(snapshot),
            reason=reason,
        )

    if isinstance(state, VolatilityState):
        implied_30 = state.implied_by_horizon.get(30)
        add("atm_iv_30d", implied_30)
        history_30 = state.iv_history.get(30, {}).get(252)
        if history_30 is None:
            for name in ("iv_percentile_252d", "iv_rank_252d", "iv_zscore_252d"):
                add_unavailable(name, "252-session IV history is unavailable")
        else:
            add("iv_percentile_252d", history_30.percentile)
            add("iv_rank_252d", history_30.rank)
            add("iv_zscore_252d", history_30.z_score)
        add("rv_20d", state.realized_by_window.get(20))
        comparison = state.iv_rv.get(30)
        if comparison is None:
            for name in ("iv_rv_spread_30d", "iv_rv_ratio_30d"):
                add_unavailable(name, "30-day IV/RV comparison is unavailable")
        else:
            add("iv_rv_spread_30d", comparison.spread)
            add("iv_rv_ratio_30d", comparison.ratio)
            add("implied_variance_30d", comparison.implied_variance)
            add("realized_variance_30d", comparison.realized_variance)
            add("variance_spread_30d", comparison.variance_spread)
        if comparison is None:
            for name in (
                "implied_variance_30d",
                "realized_variance_30d",
                "variance_spread_30d",
            ):
                add_unavailable(name, "30-day IV/RV comparison is unavailable")
        add("term_7_30", state.term_structure.spreads.get((7, 30)))
        add("term_30_60", state.term_structure.spreads.get((30, 60)))
        skew = _preferred_skew(state)
        if skew is None:
            for name in ("put_skew", "call_skew", "risk_reversal", "butterfly"):
                add_unavailable(name, "no usable 25-delta skew observation")
        else:
            add("put_skew", skew.put_skew)
            add("call_skew", skew.call_skew)
            add("risk_reversal", skew.risk_reversal)
            add("butterfly", skew.butterfly)
        event_premium = state.event.premium_by_pair.get((7, 30))
        add("event_iv_premium", event_premium)
        event_metadata = state.event.metadata
        _check_not_future(event_metadata, snapshot.as_of, "event_volatility")
        values["event_volatility"] = (
            None
            if event_metadata.status is MetricStatus.UNAVAILABLE
            else float(state.event.detected)
        )
        metadata["event_volatility"] = event_metadata
        add("surface_confidence", state.surface_confidence)
    else:
        for name in (
            "atm_iv_30d",
            "iv_percentile_252d",
            "iv_rank_252d",
            "iv_zscore_252d",
            "iv_rv_spread_30d",
            "iv_rv_ratio_30d",
            "implied_variance_30d",
            "realized_variance_30d",
            "variance_spread_30d",
            "term_7_30",
            "term_30_60",
            "put_skew",
            "call_skew",
            "risk_reversal",
            "butterfly",
            "event_iv_premium",
            "surface_confidence",
        ):
            add_unavailable(name, "volatility state is unavailable")
        add_unavailable("rv_20d", "volatility state is unavailable")
        add_unavailable("event_volatility", "volatility state is unavailable")

    _add_level_distances(snapshot, values, metadata, add_unavailable)
    _add_confluence_features(snapshot, values, metadata, add_unavailable)
    _add_credit_features(snapshot, values, metadata, add_unavailable, categories)

    # RND is intentionally deferred until an arbitrage-clean surface design exists.
    add_unavailable("distance_to_rnd_p16", "risk-neutral distribution is deferred")
    add_unavailable("distance_to_rnd_p84", "risk-neutral distribution is deferred")

    return FeatureRecord(
        symbol=snapshot.symbol,
        as_of=snapshot.as_of,
        values=values,
        metadata=metadata,
        categories=categories,
    )


def _preferred_skew(state: VolatilityState) -> SkewState | None:
    if not state.skew_by_expiration:
        return None
    return min(
        state.skew_by_expiration.values(),
        key=lambda item: (
            abs((item.expiration - state.as_of.date()).days - 30),
            item.expiration,
        ),
    )


def _add_level_distances(
    snapshot: AnalyticsSnapshot,
    values: dict[str, float | None],
    metadata: dict[str, MetricMetadata],
    add_unavailable: Any,
) -> None:
    levels = tuple(
        level for level in (snapshot.levels or ()) if isinstance(level, Level)
    )
    upper = _select_level(levels, "1.0sigma_upper", snapshot.as_of)
    lower = _select_level(levels, "1.0sigma_lower", snapshot.as_of)
    if not isinstance(snapshot.volatility, VolatilityState):
        add_unavailable(
            "distance_to_iv_upper_1sigma", "volatility state is unavailable"
        )
        add_unavailable(
            "distance_to_iv_lower_1sigma", "volatility state is unavailable"
        )
        return
    if upper is None:
        add_unavailable(
            "distance_to_iv_upper_1sigma", "1-sigma IV upper band is unavailable"
        )
    else:
        _add_distance("distance_to_iv_upper_1sigma", snapshot, upper, values, metadata)
    if lower is None:
        add_unavailable(
            "distance_to_iv_lower_1sigma", "1-sigma IV lower band is unavailable"
        )
    else:
        _add_distance("distance_to_iv_lower_1sigma", snapshot, lower, values, metadata)


def _select_level(
    levels: tuple[Level, ...], subtype: str, as_of: datetime
) -> Level | None:
    candidates = [
        level
        for level in levels
        if level.source == "iv_band"
        and level.subtype == subtype
        and level.valid_from <= as_of
        and (level.valid_until is None or level.valid_until >= as_of)
    ]
    return (
        min(candidates, key=lambda level: (level.horizon or 0, abs(level.price)))
        if candidates
        else None
    )


def _add_distance(
    name: str,
    snapshot: AnalyticsSnapshot,
    level: Level,
    values: dict[str, float | None],
    metadata: dict[str, MetricMetadata],
) -> None:
    _check_not_future(level.metadata, snapshot.as_of, name)
    values[name] = abs(level.price - snapshot.volatility.spot)
    metadata[name] = level.metadata


def _add_confluence_features(
    snapshot: AnalyticsSnapshot,
    values: dict[str, float | None],
    metadata: dict[str, MetricMetadata],
    add_unavailable: Any,
) -> None:
    zones = tuple(
        zone
        for zone in (snapshot.confluence_zones or ())
        if isinstance(zone, LevelZone)
    )
    if not zones:
        add_unavailable("nearest_confluence_score", "no confluence zone is available")
        add_unavailable(
            "distance_to_nearest_confluence_zone", "no confluence zone is available"
        )
        return
    spot = (
        snapshot.volatility.spot
        if isinstance(snapshot.volatility, VolatilityState)
        else None
    )
    if spot is None:
        add_unavailable("nearest_confluence_score", "spot is unavailable")
        add_unavailable("distance_to_nearest_confluence_zone", "spot is unavailable")
        return
    nearest = min(zones, key=lambda zone: (abs(zone.center - spot), zone.center))
    _check_not_future(nearest.metadata, snapshot.as_of, "nearest_confluence_score")
    values["nearest_confluence_score"] = nearest.score
    metadata["nearest_confluence_score"] = nearest.metadata
    values["distance_to_nearest_confluence_zone"] = abs(nearest.center - spot)
    metadata["distance_to_nearest_confluence_zone"] = nearest.metadata


def _add_credit_features(
    snapshot: AnalyticsSnapshot,
    values: dict[str, float | None],
    metadata: dict[str, MetricMetadata],
    add_unavailable: Any,
    categories: dict[str, str | None],
) -> None:
    credit = snapshot.credit
    if credit is None:
        for name in ("credit_stress_score", "credit_iv_rank", "credit_iv_rv_ratio"):
            add_unavailable(name, "credit context is unavailable")
        categories["credit_regime"] = None
        return
    stress = getattr(credit, "stress", None)
    if stress is None:
        add_unavailable("credit_stress_score", "credit stress state is unavailable")
    else:
        add("credit_stress_score", stress.composite, values, metadata, snapshot.as_of)
    volatility = getattr(credit, "volatility", None)
    if volatility is None:
        add_unavailable("credit_iv_rank", "credit ETF volatility state is unavailable")
        add_unavailable(
            "credit_iv_rv_ratio", "credit ETF volatility state is unavailable"
        )
    else:
        add("credit_iv_rank", volatility.iv_rank, values, metadata, snapshot.as_of)
        add(
            "credit_iv_rv_ratio",
            volatility.iv_rv_ratio,
            values,
            metadata,
            snapshot.as_of,
        )
    regime = getattr(credit, "regime", None)
    categories["credit_regime"] = None if regime is None else str(regime)


def add(
    name: str,
    metric: MetricResult[Any] | None,
    values: dict[str, float | None],
    metadata: dict[str, MetricMetadata],
    as_of: datetime,
) -> None:
    """Add a metric from a nested context while retaining its provenance."""
    if metric is None:
        values[name] = None
        metadata[name] = MetricMetadata.unavailable(
            as_of=as_of,
            provider="feature_exporter",
            dataset="features",
            venue_scope="",
            reason="source metric is unavailable",
        )
        return
    _check_not_future(metric.metadata, as_of, name)
    values[name] = metric.value
    metadata[name] = metric.metadata


def _check_not_future(metadata: MetricMetadata, as_of: datetime, name: str) -> None:
    if metadata.as_of > as_of:
        raise ValueError(f"feature {name} uses metadata from the future")


def _venue_scope(snapshot: AnalyticsSnapshot) -> str:
    data_quality = snapshot.data_quality
    if isinstance(data_quality, Mapping):
        for metric in data_quality.values():
            if isinstance(metric, MetricResult):
                return metric.metadata.venue_scope
    return ""
