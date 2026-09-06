"""Vendor-neutral provider contracts for market analytics."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from .models import (
    BarEvent,
    CorporateActionEvent,
    MarketEvent,
    OptionChainEvent,
    QuoteEvent,
    TradeEvent,
)


@dataclass(frozen=True, slots=True)
class CapabilityRegistry:
    supports_l2: bool = False
    supports_mbo: bool = False
    supports_trade_side: bool = False
    supports_options_chain: bool = False
    supports_greeks: bool = False
    supports_open_interest: bool = False
    supports_auction_imbalance: bool = False
    supports_historical_ticks: bool = False
    supports_corporate_actions: bool = False
    supports_iv: bool = False
    supports_option_volume: bool = False
    supports_option_bid_ask: bool = False
    supports_intraday_options: bool = False


class MarketDataProvider(Protocol):
    capabilities: CapabilityRegistry

    def iter_quotes(self, symbol: str) -> Iterable[QuoteEvent]: ...

    def iter_bars(self, symbol: str) -> Iterable[BarEvent]: ...


class DepthDataProvider(Protocol):
    capabilities: CapabilityRegistry

    def iter_depth_events(self, symbol: str) -> Iterable[MarketEvent]: ...


class HistoricalTradesProvider(Protocol):
    capabilities: CapabilityRegistry

    def iter_trades(self, symbol: str) -> Iterable[TradeEvent]: ...


class OptionsDataProvider(Protocol):
    capabilities: CapabilityRegistry

    def iter_option_snapshots(self, symbol: str) -> Iterable[OptionChainEvent]: ...


class CorporateActionsProvider(Protocol):
    capabilities: CapabilityRegistry

    def iter_corporate_actions(self, symbol: str) -> Iterable[CorporateActionEvent]: ...
