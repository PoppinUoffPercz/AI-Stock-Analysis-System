from __future__ import annotations

from datetime import timedelta

import pytest

from stock_analysis.artifacts import ArtifactStore
from stock_analysis.market_analytics.models import TradeEvent
from stock_analysis.market_analytics.providers import CapabilityRegistry
from stock_analysis.market_analytics.replay import ReplayClock, ReplayProvider
from stock_analysis.paper import PaperBroker, PaperOrderStatus
from tests.market_analytics.support import T0


def _trade(seconds: int, trade_id: str, *, price: float = 10.0, size: float = 10.0):
    return TradeEvent(
        "AAA",
        T0 + timedelta(seconds=seconds),
        "fixture",
        "trades",
        price,
        size,
        None,
        trade_id,
    )


def test_replay_provider_sorts_out_of_order_events_stably_and_clock_rejects_backwards():
    first_same_time = _trade(1, "first")
    second_same_time = _trade(1, "second")
    provider = ReplayProvider(
        (_trade(2, "later"), first_same_time, second_same_time, _trade(0, "earlier")),
        CapabilityRegistry(supports_historical_ticks=True),
    )

    assert [event.trade_id for event in provider.events("AAA")] == [
        "earlier",
        "first",
        "second",
        "later",
    ]
    clock = ReplayClock()
    clock.advance(T0 + timedelta(seconds=1))
    with pytest.raises(ValueError, match="backwards"):
        clock.advance(T0)


def test_paper_broker_partial_fill_cancel_duplicate_event_and_rejection_are_deterministic():
    broker = PaperBroker(100.0, fee_per_share=0.1)
    broker.submit_order("buy-1", "AAA", "buy", 5.0, T0)

    first = broker.process_trade(_trade(1, "one", size=2.0))
    duplicate = broker.process_trade(_trade(1, "one", size=2.0))

    assert len(first) == 1
    assert first[0].quantity == 2.0
    assert duplicate == ()
    assert broker.orders["buy-1"].status is PaperOrderStatus.PARTIALLY_FILLED

    broker.cancel_order("buy-1", T0 + timedelta(seconds=2))
    assert broker.process_trade(_trade(3, "two", size=10.0)) == ()
    assert broker.orders["buy-1"].filled_quantity == 2.0
    assert broker.orders["buy-1"].status is PaperOrderStatus.CANCELED

    rejected = broker.submit_order("sell-short", "BBB", "sell", 1.0, T0)
    assert rejected.status is PaperOrderStatus.REJECTED
    assert "short selling" in rejected.rejection_reason


def test_paper_broker_rejects_sells_that_reuse_reserved_shares():
    broker = PaperBroker(1_000.0)
    broker.submit_order("buy", "AAA", "buy", 10.0, T0)
    broker.process_trade(_trade(1, "entry", size=10.0))

    first = broker.submit_order(
        "sell-1", "AAA", "sell", 10.0, T0 + timedelta(seconds=2)
    )
    second = broker.submit_order(
        "sell-2", "AAA", "sell", 1.0, T0 + timedelta(seconds=2)
    )

    assert first.status is PaperOrderStatus.OPEN
    assert second.status is PaperOrderStatus.REJECTED
    assert "available" in second.rejection_reason


def test_paper_broker_cancel_releases_reserved_shares():
    broker = PaperBroker(1_000.0)
    broker.submit_order("buy", "AAA", "buy", 10.0, T0)
    broker.process_trade(_trade(1, "entry", size=10.0))
    broker.submit_order("sell-1", "AAA", "sell", 10.0, T0 + timedelta(seconds=2))
    broker.cancel_order("sell-1", T0 + timedelta(seconds=3))

    replacement = broker.submit_order(
        "sell-2", "AAA", "sell", 10.0, T0 + timedelta(seconds=4)
    )

    assert replacement.status is PaperOrderStatus.OPEN


def test_paper_broker_rolls_back_failed_trade_event(monkeypatch):
    broker = PaperBroker(1_000.0)
    broker.submit_order("buy-1", "AAA", "buy", 1.0, T0)
    broker.submit_order("buy-2", "AAA", "buy", 1.0, T0)
    event = _trade(1, "atomic", size=2.0)
    before = broker.state()
    original_apply_fill = broker._apply_fill
    calls = 0

    def fail_second_fill(fill):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated fill failure")
        original_apply_fill(fill)

    monkeypatch.setattr(broker, "_apply_fill", fail_second_fill)
    with pytest.raises(RuntimeError, match="simulated fill failure"):
        broker.process_trade(event)

    assert broker.state() == before
    monkeypatch.setattr(broker, "_apply_fill", original_apply_fill)
    assert len(broker.process_trade(event)) == 2


def test_paper_broker_accounting_persistence_recovery_and_reconciliation(tmp_path):
    broker = PaperBroker(100.0, fee_per_share=0.1)
    broker.submit_order("buy-1", "AAA", "buy", 2.0, T0)
    broker.process_trade(_trade(1, "buy", price=10.0, size=2.0))
    broker.submit_order("sell-1", "AAA", "sell", 1.0, T0 + timedelta(seconds=2))
    broker.process_trade(_trade(3, "sell", price=12.0, size=1.0))

    account = broker.account({"AAA": 13.0})
    assert account.cash == pytest.approx(91.7)
    assert account.total_fees == pytest.approx(0.3)
    assert account.realized_pnl == pytest.approx(1.7)
    assert account.unrealized_pnl == pytest.approx(3.0)
    assert account.equity == pytest.approx(104.7)
    assert broker.reconcile().ok

    store = ArtifactStore(tmp_path, mode="paper")
    reference = broker.save(store)
    restored = PaperBroker.restore(store, reference)
    assert restored.state() == broker.state()
    assert restored.reconcile().ok

    restored.cash += 1.0
    report = restored.reconcile()
    assert not report.ok
    assert report.actual_cash == pytest.approx(92.7)
    assert report.expected_cash == pytest.approx(91.7)
    assert restored.cash == pytest.approx(92.7)


def test_paper_broker_same_input_produces_identical_state_and_rejects_out_of_order_events():
    def run():
        broker = PaperBroker(1_000.0)
        broker.submit_order("buy-1", "AAA", "buy", 5.0, T0)
        broker.process_trade(_trade(2, "second", price=11.0, size=3.0))
        broker.process_trade(_trade(3, "third", price=12.0, size=3.0))
        return broker

    first = run()
    second = run()
    assert first.state() == second.state()
    assert first.orders["buy-1"].status is PaperOrderStatus.FILLED

    with pytest.raises(ValueError, match="out-of-order"):
        first.process_trade(_trade(1, "old", price=9.0, size=1.0))
