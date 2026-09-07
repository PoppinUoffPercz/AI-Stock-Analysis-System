from __future__ import annotations

from datetime import timedelta

import pytest

from stock_analysis.artifacts import content_identity
from stock_analysis.market_analytics.models import TradeEvent
from stock_analysis.market_analytics.streaming import (
    IngestStatus,
    StreamEnvelope,
    StreamingIngestor,
    StreamJournal,
)
from tests.market_analytics.support import T0


def _trade(seconds: int, trade_id: str) -> TradeEvent:
    timestamp = T0 + timedelta(seconds=seconds)
    return TradeEvent("AAA", timestamp, "fixture", "trades", 100.0, 1.0, None, trade_id)


def _receive(event: TradeEvent):
    return event.timestamp + timedelta(milliseconds=5)


def test_streaming_buffer_orders_events_deduplicates_and_applies_backpressure_and_late_policy():
    ingestor = StreamingIngestor(2)
    later = _trade(2, "later")
    earlier = _trade(1, "earlier")
    newest = _trade(3, "newest")

    assert ingestor.ingest(later, _receive(later)).status is IngestStatus.ACCEPTED
    assert ingestor.ingest(earlier, _receive(earlier)).status is IngestStatus.ACCEPTED
    assert ingestor.ingest(newest, _receive(newest)).status is IngestStatus.BACKPRESSURE

    drained = ingestor.drain_until(earlier.timestamp)
    assert [item.event.trade_id for item in drained] == ["earlier"]
    assert ingestor.ingest(newest, _receive(newest)).status is IngestStatus.ACCEPTED
    assert ingestor.ingest(later, _receive(later)).status is IngestStatus.DUPLICATE

    rest = ingestor.drain_until(newest.timestamp)
    assert [item.event.trade_id for item in rest] == ["later", "newest"]
    late = _trade(0, "late")
    assert ingestor.ingest(late, _receive(late)).status is IngestStatus.LATE
    assert ingestor.health.backpressure == 1
    assert ingestor.health.duplicates == 1
    assert ingestor.health.late == 1


def test_streaming_journal_recovers_pending_events_and_preserves_replayable_input(
    tmp_path,
):
    journal = StreamJournal(tmp_path / "stream.jsonl")
    ingestor = StreamingIngestor(3, journal=journal)
    later = _trade(2, "later")
    earlier = _trade(1, "earlier")
    newest = _trade(3, "newest")
    ingestor.ingest(later, _receive(later))
    ingestor.ingest(earlier, _receive(earlier))
    assert [
        item.event.trade_id for item in ingestor.drain_until(earlier.timestamp)
    ] == ["earlier"]

    recovered = StreamingIngestor.recover(3, journal)

    assert recovered.health.recovered == 1
    assert recovered.ingest(earlier, _receive(earlier)).status is IngestStatus.DUPLICATE
    assert recovered.ingest(newest, _receive(newest)).status is IngestStatus.ACCEPTED
    assert [item.event.trade_id for item in recovered.close()] == ["later", "newest"]
    assert recovered.health.closed
    assert [item.event.trade_id for item in journal.replay()] == [
        "earlier",
        "later",
        "newest",
    ]
    with pytest.raises(RuntimeError, match="closed"):
        recovered.ingest(_trade(4, "after-close"), T0 + timedelta(seconds=5))


def test_streaming_recovery_surfaces_corrupt_journal_instead_of_skipping_it(tmp_path):
    journal = StreamJournal(tmp_path / "stream.jsonl")
    journal.path.write_text("{broken\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"stream.jsonl:1"):
        StreamingIngestor.recover(2, journal)


def test_streaming_recovery_preserves_terminal_close(tmp_path):
    journal = StreamJournal(tmp_path / "stream.jsonl")
    original = StreamingIngestor(2, journal=journal)
    event = _trade(0, "one")
    original.ingest(event, _receive(event))
    original.close()

    recovered = StreamingIngestor.recover(2, journal)

    assert recovered.health.closed
    with pytest.raises(RuntimeError, match="closed"):
        after = _trade(1, "after")
        recovered.ingest(after, _receive(after))


def test_streaming_recovery_assigns_unique_sequence_after_duplicate_accept(tmp_path):
    journal = StreamJournal(tmp_path / "stream.jsonl")
    first = _trade(0, "first")
    second = _trade(0, "second")
    third = _trade(0, "third")
    first_envelope = StreamEnvelope(content_identity(first), first, _receive(first))
    second_envelope = StreamEnvelope(content_identity(second), second, _receive(second))
    journal.append({"action": "accept", "envelope": first_envelope})
    journal.append({"action": "accept", "envelope": first_envelope})
    journal.append({"action": "accept", "envelope": second_envelope})

    recovered = StreamingIngestor.recover(3, journal)
    recovered.ingest(third, _receive(third))

    assert [item.event.trade_id for item in recovered.close()] == [
        "first",
        "second",
        "third",
    ]


def test_streaming_recovery_rejects_journal_records_after_close(tmp_path):
    journal = StreamJournal(tmp_path / "stream.jsonl")
    event = _trade(0, "after-close")
    journal.append({"action": "close"})
    journal.append(
        {
            "action": "accept",
            "envelope": StreamEnvelope(content_identity(event), event, _receive(event)),
        }
    )

    with pytest.raises(ValueError, match="after close"):
        StreamingIngestor.recover(2, journal)
