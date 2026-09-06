"""Modeled option positioning: GEX, DEX, flips, walls, and saturation."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from math import isfinite
from statistics import linear_regression
from zoneinfo import ZoneInfo

from .config import AnalyticsConfig
from .models import (
    CallPut,
    MetricMetadata,
    MetricResult,
    MetricStatus,
    OptionChainEvent,
    Provenance,
    _require_utc,
)
from .options import (
    EuropeanBlackScholes,
    Greeks,
    NormalizedOptionChain,
    OptionChainNormalizer,
    OptionContract,
)


class DealerPositionModel:
    description = "undeclared dealer position model"

    def position_sign(self, contract: OptionContract) -> int:
        raise NotImplementedError


class ClassicOIOProxy(DealerPositionModel):
    description = "classic open-interest proxy: calls +1 and puts -1"

    def position_sign(self, contract: OptionContract) -> int:
        return 1 if contract.call_put is CallPut.CALL else -1


class UnsignedExposure(DealerPositionModel):
    description = "unsigned exposure: positive magnitude for calls and puts"

    def position_sign(self, contract: OptionContract) -> int:
        return 1


@dataclass(frozen=True, slots=True)
class FlipRoot:
    spot: float
    residual: float


@dataclass(frozen=True, slots=True)
class FlipResult:
    all_roots: tuple[FlipRoot, ...]
    nearest_root: FlipRoot | None
    residuals: tuple[float, ...]
    slope_near_spot: float
    metadata: MetricMetadata


@dataclass(frozen=True, slots=True)
class PositioningSnapshot:
    net_gex: MetricResult[float]
    positive_gex: MetricResult[float]
    negative_gex: MetricResult[float]
    gex_by_strike: dict[float, float]
    gex_by_expiration: dict[date, float]
    gamma_flip: FlipResult
    net_dex: MetricResult[float]
    dex_by_strike: dict[float, float]
    dealer_dex_flip: FlipResult
    dealer_hedge_saturation: MetricResult[float]
    call_wall: MetricResult[float]
    put_wall: MetricResult[float]
    metadata: MetricMetadata
    gex_by_dte: dict[str, float] = field(default_factory=dict)
    dex_by_expiration: dict[date, float] = field(default_factory=dict)
    dex_by_dte: dict[str, float] = field(default_factory=dict)


class PositioningEngine:
    def __init__(self, config: AnalyticsConfig) -> None:
        self.config = config
        self.normalizer = OptionChainNormalizer(config)
        self.black_scholes = EuropeanBlackScholes(config)
        self.model = self._make_model(config.options.dealer_model)
        self.provider = "analytics"
        self.dataset = "positioning"

    def analyze(
        self,
        chain: NormalizedOptionChain | OptionChainEvent,
        spot: float,
        as_of: datetime,
    ) -> PositioningSnapshot:
        _require_utc(as_of, "as_of")
        if spot <= 0 or not isfinite(spot):
            raise ValueError("spot must be positive and finite")
        normalized = (
            self.normalizer.normalize(chain)
            if isinstance(chain, OptionChainEvent)
            else chain
        )
        self.provider = normalized.provider
        self.dataset = normalized.dataset
        metadata = self._model_metadata(as_of)
        oi_status, oi_reason = self._oi_status(normalized, as_of)
        if oi_status is not MetricStatus.OK:
            return self._unavailable_snapshot(
                as_of,
                oi_reason,
                metadata,
                status=oi_status,
            )
        values = [
            self._exposure(contract, spot, as_of, for_root=False)
            for contract in normalized.accepted
        ]
        if any(value is None for value in values):
            return self._unavailable_snapshot(
                as_of, "required option Greek is unavailable", metadata
            )
        exposures = [value for value in values if value is not None]
        gex_values = [value[0] for value in exposures]
        dex_values = [value[1] for value in exposures]
        gex_by_strike = self._aggregate_by_strike(normalized, gex_values)
        gex_by_expiration = self._aggregate_by_expiration(normalized, gex_values)
        gex_by_dte = self._aggregate_by_dte(normalized, gex_values, as_of)
        dex_by_strike = self._aggregate_by_strike(normalized, dex_values)
        dex_by_expiration = self._aggregate_by_expiration(normalized, dex_values)
        dex_by_dte = self._aggregate_by_dte(normalized, dex_values, as_of)
        net_gex = sum(gex_values)
        net_dex = sum(dex_values)
        total_abs_gex = sum(abs(value) for value in gex_values)
        snapshot = PositioningSnapshot(
            net_gex=self._metric(
                net_gex,
                as_of,
                metadata,
                "modeled GEX = position sign * gamma * OI * multiplier * spot^2 * 0.01",
            ),
            positive_gex=self._metric(
                sum(value for value in gex_values if value > 0),
                as_of,
                metadata,
                "sum of positive modeled GEX contributions",
            ),
            negative_gex=self._metric(
                sum(value for value in gex_values if value < 0),
                as_of,
                metadata,
                "sum of negative modeled GEX contributions",
            ),
            gex_by_strike=gex_by_strike,
            gex_by_expiration=gex_by_expiration,
            gex_by_dte=gex_by_dte,
            gamma_flip=self._flip(normalized, spot, as_of, "gex"),
            net_dex=self._metric(
                net_dex,
                as_of,
                metadata,
                "modeled DEX = position sign * delta * OI * multiplier * spot",
            ),
            dex_by_strike=dex_by_strike,
            dex_by_expiration=dex_by_expiration,
            dex_by_dte=dex_by_dte,
            dealer_dex_flip=self._flip(normalized, spot, as_of, "dex"),
            dealer_hedge_saturation=self._saturation(
                normalized, spot, as_of, gex_values, dex_values, total_abs_gex
            ),
            call_wall=self._wall(normalized, CallPut.CALL, as_of, metadata),
            put_wall=self._wall(normalized, CallPut.PUT, as_of, metadata),
            metadata=metadata,
        )
        return snapshot

    def _make_model(self, name: str) -> DealerPositionModel:
        if name == "classic_oi_proxy":
            return ClassicOIOProxy()
        if name == "unsigned_exposure":
            return UnsignedExposure()
        raise ValueError(f"unsupported dealer model: {name}")

    def _oi_status(
        self, chain: NormalizedOptionChain, as_of: datetime
    ) -> tuple[MetricStatus, str]:
        if not chain.accepted:
            return MetricStatus.UNAVAILABLE, "no accepted contracts"
        for contract in chain.accepted:
            if contract.open_interest is None or contract.open_interest < 0:
                return MetricStatus.UNAVAILABLE, "open interest is missing"
            if contract.oi_as_of is None:
                return MetricStatus.UNAVAILABLE, "open interest timestamp is missing"
            age = as_of - contract.oi_as_of
            if age > self.config.options.max_quote_age:
                return MetricStatus.STALE, "open interest is stale"
            if age.total_seconds() < 0:
                return MetricStatus.UNAVAILABLE, "open interest is from the future"
        return MetricStatus.OK, ""

    def _exposure(
        self,
        contract: OptionContract,
        spot: float,
        as_of: datetime,
        *,
        for_root: bool,
    ) -> tuple[float, float] | None:
        greeks = self._greeks(contract, spot, as_of, for_root=for_root)
        if greeks is None or contract.open_interest is None:
            return None
        sign = self.model.position_sign(contract)
        gamma = (
            abs(greeks.gamma)
            if isinstance(self.model, UnsignedExposure)
            else greeks.gamma
        )
        delta = (
            abs(greeks.delta)
            if isinstance(self.model, UnsignedExposure)
            else greeks.delta
        )
        scale = contract.open_interest * contract.contract_multiplier
        return sign * gamma * scale * spot**2 * 0.01, sign * delta * scale * spot

    def _greeks(
        self,
        contract: OptionContract,
        spot: float,
        as_of: datetime,
        *,
        for_root: bool,
    ) -> Greeks | None:
        if (
            for_root
            and contract.iv is not None
            and self.config.options.option_model is not None
        ):
            try:
                return self.black_scholes.greeks(spot, contract, contract.iv, as_of)
            except ValueError:
                return None
        if contract.gamma is not None and contract.delta is not None:
            return Greeks(
                contract.mid or contract.last or 0.0,
                contract.delta,
                contract.gamma,
                contract.theta or 0.0,
                contract.vega or 0.0,
            )
        if contract.iv is None or self.config.options.option_model is None:
            return None
        try:
            return self.black_scholes.greeks(spot, contract, contract.iv, as_of)
        except ValueError:
            return None

    def _aggregate_by_strike(
        self, chain: NormalizedOptionChain, values: list[float]
    ) -> dict[float, float]:
        result: dict[float, float] = {}
        for contract, value in zip(chain.accepted, values, strict=True):
            result[contract.strike] = result.get(contract.strike, 0.0) + value
        return result

    def _aggregate_by_expiration(
        self, chain: NormalizedOptionChain, values: list[float]
    ) -> dict[date, float]:
        result: dict[date, float] = {}
        for contract, value in zip(chain.accepted, values, strict=True):
            result[contract.expiration] = result.get(contract.expiration, 0.0) + value
        return result

    def _aggregate_by_dte(
        self,
        chain: NormalizedOptionChain,
        values: list[float],
        as_of: datetime,
    ) -> dict[str, float]:
        result: dict[str, float] = {}
        for contract, value in zip(chain.accepted, values, strict=True):
            bucket = self._dte_bucket(contract.expiration, as_of)
            result[bucket] = result.get(bucket, 0.0) + value
        return result

    def _dte_bucket(self, expiration: date, as_of: datetime) -> str:
        local_date = as_of.astimezone(ZoneInfo(self.config.session.timezone)).date()
        dte = max((expiration - local_date).days, 0)
        if dte == 0:
            return "0DTE"
        if dte <= 7:
            return "1-7"
        if dte <= 30:
            return "8-30"
        if dte <= 60:
            return "31-60"
        return "61+"

    def _flip(
        self,
        chain: NormalizedOptionChain,
        spot: float,
        as_of: datetime,
        exposure: str,
    ) -> FlipResult:
        points = self.config.options.root_grid_points
        low = max(1e-9, spot * (1 - self.config.options.root_grid_pct))
        high = spot * (1 + self.config.options.root_grid_pct)
        grid = [low + (high - low) * index / (points - 1) for index in range(points)]
        values = [self._exposure_sum(chain, value, as_of, exposure) for value in grid]
        roots: list[FlipRoot] = []
        for index, value in enumerate(values):
            if value == 0:
                roots.append(FlipRoot(grid[index], 0.0))
            if index == 0 or value == 0:
                continue
            previous = values[index - 1]
            if previous * value > 0:
                continue
            root_spot, residual = self._solve_root(
                chain, grid[index - 1], grid[index], as_of, exposure
            )
            if abs(residual) <= self.config.options.root_residual_tolerance:
                roots.append(FlipRoot(root_spot, residual))
        unique: list[FlipRoot] = []
        for root in sorted(roots, key=lambda item: item.spot):
            if not unique or abs(root.spot - unique[-1].spot) > 1e-7:
                unique.append(root)
        step = max(spot * 1e-5, 1e-6)
        slope = (
            self._exposure_sum(chain, spot + step, as_of, exposure)
            - self._exposure_sum(chain, max(spot - step, 1e-9), as_of, exposure)
        ) / (2 * step)
        reason = None if unique else "no qualifying sign-change root in configured grid"
        return FlipResult(
            tuple(unique),
            min(unique, key=lambda root: abs(root.spot - spot)) if unique else None,
            tuple(root.residual for root in unique),
            slope,
            MetricMetadata(
                as_of=as_of,
                provider=self.provider,
                dataset=self.dataset,
                venue_scope="",
                status=MetricStatus.OK,
                methodology=(
                    f"modeled {exposure.upper()} evaluated on a sticky-IV spot grid "
                    "with bisection residual verification"
                ),
                quality_score=100.0,
                observed_or_modeled=Provenance.MODELED,
                reason=reason,
            ),
        )

    def _exposure_sum(
        self,
        chain: NormalizedOptionChain,
        spot: float,
        as_of: datetime,
        exposure: str,
    ) -> float:
        values = [
            self._exposure(contract, spot, as_of, for_root=True)
            for contract in chain.accepted
        ]
        valid = [value for value in values if value is not None]
        return sum(value[0 if exposure == "gex" else 1] for value in valid)

    def _solve_root(
        self,
        chain: NormalizedOptionChain,
        low: float,
        high: float,
        as_of: datetime,
        exposure: str,
    ) -> tuple[float, float]:
        low_value = self._exposure_sum(chain, low, as_of, exposure)
        midpoint = (low + high) / 2
        for _ in range(100):
            midpoint = (low + high) / 2
            midpoint_value = self._exposure_sum(chain, midpoint, as_of, exposure)
            if abs(midpoint_value) <= self.config.options.root_residual_tolerance:
                return midpoint, midpoint_value
            if low_value * midpoint_value <= 0:
                high = midpoint
            else:
                low = midpoint
                low_value = midpoint_value
        residual = self._exposure_sum(chain, midpoint, as_of, exposure)
        return midpoint, residual

    def _saturation(
        self,
        chain: NormalizedOptionChain,
        spot: float,
        as_of: datetime,
        gex_values: list[float],
        dex_values: list[float],
        total_abs_gex: float,
    ) -> MetricResult[float]:
        total_oi = sum(contract.open_interest or 0.0 for contract in chain.accepted)
        if total_oi <= 0:
            return self._unavailable(as_of, "zero total open interest")
        high_delta_oi = 0.0
        deltas: list[float] = []
        strikes: list[float] = []
        for contract in chain.accepted:
            greeks = self._greeks(contract, spot, as_of, for_root=False)
            if greeks is None or contract.open_interest is None:
                return self._unavailable(as_of, "delta unavailable for saturation")
            deltas.append(greeks.delta)
            strikes.append(contract.strike)
            if abs(greeks.delta) >= self.config.options.high_delta_threshold:
                high_delta_oi += contract.open_interest
        high_delta_fraction = high_delta_oi / total_oi
        dex_component = abs(sum(dex_values)) / max(
            sum(abs(value) for value in dex_values), 1e-12
        )
        gamma_component = abs(sum(gex_values)) / max(total_abs_gex, 1e-12)
        slope_component = (
            abs(_linear_slope(strikes, dex_values))
            / max(max(abs(value) for value in dex_values), 1e-12)
            if len(strikes) >= 2
            else 0.0
        )
        score = _clip(
            sum(
                weight * component
                for weight, component in zip(
                    self.config.options.saturation_weights,
                    (
                        high_delta_fraction,
                        _clip(dex_component),
                        _clip(gamma_component),
                        _clip(slope_component),
                    ),
                    strict=True,
                )
            )
        )
        metadata = self._model_metadata(as_of)
        return self._metric(
            score,
            as_of,
            metadata,
            "heuristic modeled hedge saturation from high-delta fraction, absolute DEX, absolute GEX, and local DEX slope",
        )

    def _wall(
        self,
        chain: NormalizedOptionChain,
        call_put: CallPut,
        as_of: datetime,
        metadata: MetricMetadata,
    ) -> MetricResult[float]:
        if not isinstance(self.model, ClassicOIOProxy):
            return self._unavailable(
                as_of, "conventional walls require classic OI proxy"
            )
        candidates = [
            contract
            for contract in chain.accepted
            if contract.call_put is call_put and contract.open_interest is not None
        ]
        if not candidates:
            return self._unavailable(as_of, f"no {call_put.value} open interest")
        wall = max(
            candidates,
            key=lambda contract: (contract.open_interest or 0.0, -contract.strike),
        )
        return self._metric(
            wall.strike,
            as_of,
            metadata,
            f"{call_put.value} wall is the highest open-interest strike",
        )

    def _model_metadata(self, as_of: datetime) -> MetricMetadata:
        return MetricMetadata(
            as_of=as_of,
            provider=self.provider,
            dataset=self.dataset,
            venue_scope="",
            methodology=self.model.description,
            quality_score=100.0,
            observed_or_modeled=Provenance.MODELED,
        )

    def _metric(
        self,
        value: float,
        as_of: datetime,
        metadata: MetricMetadata,
        methodology: str,
    ) -> MetricResult[float]:
        return MetricResult(
            value,
            MetricMetadata(
                as_of=as_of,
                provider=metadata.provider,
                dataset=metadata.dataset,
                venue_scope=metadata.venue_scope,
                status=MetricStatus.OK,
                methodology=f"{metadata.methodology}; {methodology}",
                quality_score=metadata.quality_score,
                observed_or_modeled=Provenance.MODELED,
            ),
        )

    def _unavailable(
        self,
        as_of: datetime,
        reason: str,
        *,
        status: MetricStatus = MetricStatus.UNAVAILABLE,
    ) -> MetricResult[float]:
        metadata = MetricMetadata.unavailable(
            as_of=as_of,
            provider=self.provider,
            dataset=self.dataset,
            venue_scope="",
            reason=reason,
            methodology=self.model.description,
        )
        if status is not MetricStatus.UNAVAILABLE:
            metadata = replace(metadata, status=status)
        return MetricResult(None, metadata)

    def _unavailable_snapshot(
        self,
        as_of: datetime,
        reason: str,
        metadata: MetricMetadata,
        *,
        status: MetricStatus = MetricStatus.UNAVAILABLE,
    ) -> PositioningSnapshot:
        unavailable = self._unavailable(as_of, reason, status=status)
        flip_metadata = replace(unavailable.metadata, status=status)
        flip = FlipResult((), None, (), 0.0, flip_metadata)
        return PositioningSnapshot(
            net_gex=unavailable,
            positive_gex=unavailable,
            negative_gex=unavailable,
            gex_by_strike={},
            gex_by_expiration={},
            gex_by_dte={},
            gamma_flip=flip,
            net_dex=unavailable,
            dex_by_strike={},
            dex_by_expiration={},
            dex_by_dte={},
            dealer_dex_flip=flip,
            dealer_hedge_saturation=unavailable,
            call_wall=unavailable,
            put_wall=unavailable,
            metadata=metadata,
        )


def _linear_slope(x_values: list[float], y_values: list[float]) -> float:
    if len(x_values) < 2 or len(set(x_values)) < 2:
        return 0.0
    return linear_regression(x_values, y_values).slope


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))
