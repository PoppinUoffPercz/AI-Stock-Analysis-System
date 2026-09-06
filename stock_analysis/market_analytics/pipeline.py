"""Single-event routing for the offline market analytics components."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .config import AnalyticsConfig
from .credit import (
    CreditObservation,
    CreditRegimeEngine,
    CreditRegimeState,
    CreditStressEngine,
    CreditVolatilityState,
)
from .dom import DOMSnapshot, OrderBookState
from .features import FeatureRecord, build_feature_record
from .levels import LevelAnalysis, LevelContext, LevelEngine
from .models import (
    AnalyticsSnapshot,
    BarEvent,
    BookSnapshotEvent,
    BookUpdateEvent,
    CorporateActionEvent,
    InstrumentSpec,
    MarketEvent,
    MetricMetadata,
    MetricResult,
    MetricStatus,
    OptionChainEvent,
    QuoteEvent,
    SessionTransitionEvent,
    TradeEvent,
    _require_utc,
)
from .options import IVSurfaceAnalyzer, IVSurfaceSnapshot, OptionChainNormalizer
from .order_flow import (
    ExhaustionSnapshot,
    FlowDeltaExhaustionDetector,
    FlowSnapshot,
    FootprintEngine,
)
from .positioning import PositioningEngine, PositioningSnapshot
from .profiles import (
    RollingVolumeProfileEngine,
    TPOEngine,
    VolumeProfileEngine,
    VolumeProfileSnapshot,
)
from .providers import CapabilityRegistry
from .volatility import VolatilityEngine, VolatilityState
from .vwap import SessionClock, VWAPEngine, VWAPSnapshot


class AnalyticsPipeline:
    def __init__(
        self,
        instrument: InstrumentSpec,
        config: AnalyticsConfig,
        capabilities: CapabilityRegistry,
        provider: str = "fixture",
    ) -> None:
        self.instrument = instrument
        self.config = config
        self.capabilities = capabilities
        self.provider = provider
        self.dom = OrderBookState(instrument, config, provider, "depth")
        self.flow = FootprintEngine(
            instrument,
            config,
            provider,
            "trades",
            supports_trade_side=capabilities.supports_trade_side,
        )
        self.exhaustion = FlowDeltaExhaustionDetector(config.flow)
        self.vwap = VWAPEngine(config)
        self.tpo = TPOEngine(instrument, config)
        self.volume = VolumeProfileEngine(instrument, config)
        self.rolling_volume = RollingVolumeProfileEngine(instrument, config)
        self.rolling_volume.provider = provider
        self.option_normalizer = OptionChainNormalizer(config)
        self.iv_surface = IVSurfaceAnalyzer(config)
        self.positioning = PositioningEngine(config)
        self.volatility = VolatilityEngine(config, instrument, provider)
        self.level_engine = LevelEngine(config)
        self.session_clock = SessionClock(config.session)
        self._last_quote: QuoteEvent | None = None
        self._last_options: IVSurfaceSnapshot | None = None
        self._last_positioning: PositioningSnapshot | None = None
        self._last_exhaustion: ExhaustionSnapshot | None = None
        self._last_rolling: dict[int, VolumeProfileSnapshot] | None = None
        self._last_volatility: VolatilityState | None = None
        self._credit_context: CreditRegimeState | None = None
        self._last_spot: float | None = None
        self._last_close: float | None = None
        self._volatility_session_id: str | None = None
        self._active_session_id: str | None = None
        self._last_session_event_at: datetime | None = None

    def consume(self, event: MarketEvent) -> AnalyticsSnapshot:
        _require_utc(event.timestamp, "event timestamp")
        accepted_session = (
            self._prepare_session(event.timestamp)
            if isinstance(event, (TradeEvent, BarEvent))
            else None
        )
        if isinstance(event, QuoteEvent):
            if self.capabilities.supports_l2:
                self.dom.apply(event)
            self._last_quote = event
            self._last_spot = (event.bid + event.ask) / 2.0
            self._last_volatility = self.volatility.observe_spot(
                self._last_spot, event.timestamp
            )
        elif isinstance(event, (BookSnapshotEvent, BookUpdateEvent)):
            if self.capabilities.supports_l2:
                self.dom.apply(event)
        elif isinstance(event, TradeEvent):
            self._last_spot = event.price
            if self.capabilities.supports_l2:
                self.dom.apply(event)
            if accepted_session is not None:
                self._last_close = event.price
                self.flow.consume(event, self._last_quote)
                self.vwap.consume_trade(event)
                self.volume.consume_trade(event)
                self._last_volatility = self.volatility.observe_spot(
                    event.price, event.timestamp
                )
        elif isinstance(event, BarEvent):
            self._last_spot = event.close
            if accepted_session is not None:
                self._last_close = event.close
                self.vwap.consume_bar(event)
                self.tpo.consume_bar(event)
                self.volume.consume_bar(event)
                self._last_exhaustion = self.exhaustion.update(
                    self.flow.bar_summary(event.timestamp, event.close)
                )
                self._last_volatility = self.volatility.observe_spot(
                    event.close, event.timestamp
                )
        elif isinstance(event, OptionChainEvent):
            self._last_spot = event.spot
            if self.capabilities.supports_options_chain:
                normalized = self.option_normalizer.normalize(
                    event, capabilities=self.capabilities
                )
                self._volatility_session_id = self._active_session_id
                self._last_volatility = self.volatility.analyze(
                    normalized,
                    event.spot,
                    event.timestamp,
                    supports_iv=self.capabilities.supports_iv,
                )
                self._last_options = self.iv_surface.analyze(
                    normalized,
                    event.spot,
                    event.timestamp,
                    supports_iv=self.capabilities.supports_iv,
                )
                self._last_positioning = (
                    self.positioning.analyze(normalized, event.spot, event.timestamp)
                    if self.capabilities.supports_greeks
                    and self.capabilities.supports_open_interest
                    else self._empty_positioning(event.timestamp)
                )
        elif isinstance(event, SessionTransitionEvent):
            if not event.is_open:
                self._finalize_session(event.session_id, event.timestamp)
                self._last_volatility = self.volatility.current()
                self._active_session_id = None
                self._last_session_event_at = None
            else:
                if self._active_session_id != event.session_id:
                    self._start_session_local_state(event.session_id)
                self._active_session_id = event.session_id
                self._last_session_event_at = event.timestamp
            self.dom.apply(event)
        elif isinstance(event, CorporateActionEvent):
            pass
        else:
            raise TypeError(f"unsupported analytics event: {type(event).__name__}")
        return self._snapshot(event.timestamp)

    def _prepare_session(self, timestamp: datetime) -> str | None:
        session_id = self.session_clock.session_id(timestamp)
        if session_id is None:
            return None
        if self._active_session_id is None:
            self._start_session_local_state(session_id)
            self._active_session_id = session_id
        elif self._active_session_id != session_id:
            close_time = self._last_session_event_at or timestamp
            self._finalize_session(self._active_session_id, close_time)
            self._start_session_local_state(session_id)
            self._active_session_id = session_id
        self._last_session_event_at = timestamp
        return session_id

    def _reset_session_local_state(self) -> None:
        self.flow.reset()
        self.exhaustion.reset()
        self._last_exhaustion = None
        self._last_close = None

    def _start_session_local_state(self, session_id: str) -> None:
        self._reset_session_local_state()
        self.vwap.start_session(session_id)
        self.tpo.start_session(session_id)
        self.volume.start_session(session_id)

    def finalize(self, as_of: datetime) -> AnalyticsSnapshot:
        _require_utc(as_of, "as_of")
        return self._snapshot(as_of)

    def set_credit_context(self, context: CreditRegimeState | None) -> None:
        if (
            context is not None
            and self._last_session_event_at is not None
            and context.as_of > self._last_session_event_at
        ):
            raise ValueError("credit context is from the future")
        self._credit_context = context

    def set_credit_observation(
        self,
        observation: CreditObservation,
        volatility: CreditVolatilityState | None = None,
    ) -> CreditRegimeState:
        """Attach typed credit context at the observation's point in time."""
        stress = CreditStressEngine(self.config).calculate(observation)
        context = CreditRegimeEngine(self.config).classify(stress, volatility)
        self.set_credit_context(context)
        return context

    def _finalize_session(self, session_id: str, as_of: datetime) -> None:
        volume = self.volume.snapshot(as_of)
        self._last_rolling = dict(
            self.rolling_volume.finalize_session(
                session_id,
                self.volume.histogram,
                exact=volume.exact_or_approximate == "exact",
                as_of=as_of,
            )
        )
        self.tpo.finalize_session(session_id, as_of)
        if self._last_close is not None:
            self.volatility.finalize_session(
                session_id,
                self._last_close,
                as_of,
                include_iv_observation=self._volatility_session_id == session_id,
            )
            self._last_volatility = self.volatility.current()
        self._volatility_session_id = None

    def _snapshot(self, as_of: datetime) -> AnalyticsSnapshot:
        if self._credit_context is not None and self._credit_context.as_of > as_of:
            raise ValueError("credit context is from the future")
        dom = self.dom.snapshot(as_of)
        flow = replace(self.flow.snapshot(as_of), exhaustion=self._last_exhaustion)
        vwap = self.vwap.snapshot(as_of)
        tpo = self.tpo.snapshot(as_of)
        volume = self.volume.snapshot(as_of)
        rolling = self._last_rolling or dict(self.rolling_volume.snapshot(as_of))
        options = self._last_options or self._empty_options(as_of)
        positioning = self._last_positioning or self._empty_positioning(as_of)
        volatility = self._last_volatility or self.volatility.current()
        levels: tuple[object, ...] = ()
        confluence_zones: tuple[object, ...] = ()
        if self._last_spot is not None:
            level_analysis: LevelAnalysis = self.level_engine.calculate(
                LevelContext(
                    instrument=self.instrument,
                    spot=self._last_spot,
                    as_of=as_of,
                    volatility=volatility,
                    vwap=vwap,
                    profiles={
                        "tpo": tpo,
                        "volume": volume,
                        **{str(window): profile for window, profile in rolling.items()},
                    },
                    positioning=positioning,
                    dom=dom,
                    flow=flow,
                    config=self.config,
                )
            )
            levels = level_analysis.levels
            confluence_zones = level_analysis.zones
        data_quality = self._data_quality(
            as_of, dom, flow, vwap, options, positioning, volatility
        )
        snapshot = AnalyticsSnapshot(
            as_of=as_of,
            symbol=self.instrument.symbol,
            dom=dom,
            flow=flow,
            vwap=vwap,
            profiles={"tpo": tpo, "volume": volume, "rolling": rolling},
            options=options,
            positioning=positioning,
            data_quality=data_quality,
            volatility=volatility,
            levels=levels,
            confluence_zones=confluence_zones,
            credit=self._credit_context,
        )
        features: FeatureRecord = build_feature_record(snapshot)
        return replace(snapshot, features=features)

    def _empty_chain(self, as_of: datetime) -> OptionChainEvent:
        return OptionChainEvent(
            self.instrument.symbol,
            as_of,
            self.provider,
            "options",
            1.0,
            (),
        )

    def _empty_options(self, as_of: datetime) -> IVSurfaceSnapshot:
        return self.iv_surface.analyze(self._empty_chain(as_of), 1.0, as_of)

    def _empty_positioning(self, as_of: datetime) -> PositioningSnapshot:
        return self.positioning.analyze(self._empty_chain(as_of), 1.0, as_of)

    def _data_quality(
        self,
        as_of: datetime,
        dom: DOMSnapshot,
        flow: FlowSnapshot,
        vwap: VWAPSnapshot,
        options: IVSurfaceSnapshot,
        positioning: PositioningSnapshot,
        volatility: VolatilityState | None,
    ) -> dict[str, MetricResult[float]]:
        return {
            "dom": self._quality_result(
                as_of, list(dom.metrics.values()), "DOM metric quality"
            ),
            "flow": self._quality_result(
                as_of, [flow.quality], "flow classification quality"
            ),
            "vwap": self._quality_result(
                as_of, [vwap.metrics["session_vwap"]], "VWAP input quality"
            ),
            "options": self._quality_result(
                as_of, [options.atm_iv], "IV surface quality"
            ),
            "positioning": self._quality_result(
                as_of, [positioning.net_gex], "modeled positioning quality"
            ),
            "volatility": self._quality_result(
                as_of,
                [volatility.surface_confidence] if volatility is not None else [],
                "shared volatility quality",
            ),
        }

    def _quality_result(
        self,
        as_of: datetime,
        metrics: list[MetricResult[float]],
        methodology: str,
    ) -> MetricResult[float]:
        available = [
            metric
            for metric in metrics
            if metric.metadata.status is not MetricStatus.UNAVAILABLE
        ]
        value = min(
            (metric.metadata.quality_score for metric in available), default=None
        )
        status = (
            MetricStatus.UNAVAILABLE
            if value is None
            else MetricStatus.OK
            if value >= 100
            else MetricStatus.DEGRADED
        )
        reason = (
            None
            if value is not None and value >= 100
            else "one or more inputs are unavailable or degraded"
        )
        return MetricResult(
            value,
            MetricMetadata(
                as_of=as_of,
                provider=self.provider,
                dataset="data_quality",
                venue_scope=self.instrument.venue,
                status=status,
                methodology=methodology,
                quality_score=value or 0.0,
                reason=reason,
                observed_or_modeled=metrics[0].metadata.observed_or_modeled,
            )
            if value is not None
            else MetricMetadata.unavailable(
                as_of=as_of,
                provider=self.provider,
                dataset="data_quality",
                venue_scope=self.instrument.venue,
                reason=reason or "no quality-bearing inputs",
                methodology=methodology,
            ),
        )
