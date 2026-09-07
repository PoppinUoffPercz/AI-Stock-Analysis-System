"""Bounded, replayable streaming-ingestion boundary for normalized market events."""

from __future__ import annotations

import heapq
import json
import os
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from stock_analysis.artifacts import content_identity
from stock_analysis.persistence import process_lock

from .models import MarketEvent, _require_utc
from .serialization import from_jsonable, to_jsonable


class IngestStatus(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    LATE = "late"
    BACKPRESSURE = "backpressure"


@dataclass(frozen=True, slots=True)
class StreamEnvelope:
    event_id: str
    event: MarketEvent
    received_at: datetime

    def __post_init__(self) -> None:
        _require_utc(self.event.timestamp, "stream event timestamp")
        _require_utc(self.received_at, "stream received_at")
        if self.received_at < self.event.timestamp:
            raise ValueError("stream received_at must not precede the event timestamp")


@dataclass(frozen=True, slots=True)
class IngestResult:
    status: IngestStatus
    event_id: str
    buffered: int
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class IngestionHealth:
    buffered: int
    accepted: int
    duplicates: int
    late: int
    backpressure: int
    recovered: int
    closed: bool
    last_emitted_at: datetime | None


class StreamJournal:
    """Append-only local JSONL journal that makes accepted stream input replayable."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, record: dict[str, object]) -> None:
        encoded = json.dumps(
            to_jsonable(record), ensure_ascii=False, sort_keys=True, allow_nan=False
        )
        lock = self.path.with_suffix(self.path.suffix + ".lock")
        with process_lock(lock):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded + "\n")
                stream.flush()
                os.fsync(stream.fileno())

    def records(self) -> tuple[dict[str, object], ...]:
        if not self.path.exists():
            return ()
        records: list[dict[str, object]] = []
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), 1
        ):
            try:
                decoded = from_jsonable(json.loads(line))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"malformed stream journal at {self.path}:{line_number}: {exc}"
                ) from exc
            if not isinstance(decoded, dict):
                raise ValueError(  # noqa: TRY004 - malformed persisted content is a value error.
                    f"malformed stream journal at {self.path}:{line_number}: expected object"
                )
            records.append(decoded)
        return tuple(records)

    def replay(self) -> tuple[StreamEnvelope, ...]:
        accepted: dict[str, tuple[int, StreamEnvelope]] = {}
        for sequence, record in enumerate(self.records()):
            if record.get("action") != "accept":
                continue
            envelope = record.get("envelope")
            if not isinstance(envelope, StreamEnvelope):
                raise ValueError(  # noqa: TRY004 - malformed persisted content is a value error.
                    "stream journal accept record has malformed envelope"
                )
            accepted.setdefault(envelope.event_id, (sequence, envelope))
        return tuple(
            envelope
            for _, envelope in sorted(
                accepted.values(), key=lambda item: (item[1].event.timestamp, item[0])
            )
        )


class StreamingIngestor:
    """Synchronous buffer with explicit backpressure, late-event, and recovery semantics."""

    def __init__(
        self, max_buffer: int, *, journal: StreamJournal | None = None
    ) -> None:
        if (
            isinstance(max_buffer, bool)
            or not isinstance(max_buffer, int)
            or max_buffer <= 0
        ):
            raise ValueError("max_buffer must be a positive integer")
        self.max_buffer = max_buffer
        self.journal = journal
        self._heap: list[tuple[datetime, int, StreamEnvelope]] = []
        self._arrival_sequence = 0
        self._seen: set[str] = set()
        self._closed = False
        self._last_emitted_at: datetime | None = None
        self._accepted = 0
        self._duplicates = 0
        self._late = 0
        self._backpressure = 0
        self._recovered = 0

    @classmethod
    def recover(cls, max_buffer: int, journal: StreamJournal) -> StreamingIngestor:
        ingestor = cls(max_buffer, journal=journal)
        accepted: dict[str, tuple[int, StreamEnvelope]] = {}
        emitted: set[str] = set()
        last_emitted_at: datetime | None = None
        closed = False
        records = journal.records()
        for sequence, record in enumerate(records):
            action = record.get("action")
            if closed:
                raise ValueError("stream journal contains a record after close")
            if action == "accept":
                envelope = record.get("envelope")
                if not isinstance(envelope, StreamEnvelope):
                    raise ValueError(
                        "stream journal accept record has malformed envelope"
                    )
                previous = accepted.get(envelope.event_id)
                if previous is not None and previous[1] != envelope:
                    raise ValueError(
                        "stream journal reuses an event identity with different content"
                    )
                accepted.setdefault(envelope.event_id, (sequence, envelope))
            elif action == "emit":
                event_id = record.get("event_id")
                if not isinstance(event_id, str) or event_id not in accepted:
                    raise ValueError(
                        "stream journal emit record references unknown event"
                    )
                emitted.add(event_id)
                timestamp = accepted[event_id][1].event.timestamp
                if last_emitted_at is not None and timestamp < last_emitted_at:
                    raise ValueError(
                        "stream journal contains out-of-order emitted events"
                    )
                last_emitted_at = timestamp
            elif action == "close":
                closed = True
            else:
                raise ValueError("stream journal contains an unknown action")
        pending = [
            item for event_id, item in accepted.items() if event_id not in emitted
        ]
        if len(pending) > max_buffer:
            raise ValueError("recovered stream buffer exceeds configured max_buffer")
        for sequence, envelope in pending:
            heapq.heappush(
                ingestor._heap, (envelope.event.timestamp, sequence, envelope)
            )
        ingestor._arrival_sequence = len(records)
        ingestor._seen = set(accepted)
        ingestor._last_emitted_at = last_emitted_at
        ingestor._accepted = len(accepted)
        ingestor._recovered = len(pending)
        ingestor._closed = closed
        return ingestor

    def ingest(self, event: MarketEvent, received_at: datetime) -> IngestResult:
        if self._closed:
            raise RuntimeError("stream ingestor is closed")
        envelope = StreamEnvelope(content_identity(event), event, received_at)
        if envelope.event_id in self._seen:
            self._duplicates += 1
            return IngestResult(
                IngestStatus.DUPLICATE,
                envelope.event_id,
                len(self._heap),
                "event identity already seen",
            )
        if (
            self._last_emitted_at is not None
            and event.timestamp < self._last_emitted_at
        ):
            self._late += 1
            return IngestResult(
                IngestStatus.LATE,
                envelope.event_id,
                len(self._heap),
                "event timestamp precedes the emitted watermark",
            )
        if len(self._heap) >= self.max_buffer:
            self._backpressure += 1
            return IngestResult(
                IngestStatus.BACKPRESSURE,
                envelope.event_id,
                len(self._heap),
                "bounded stream buffer is full; caller must retry after draining",
            )
        sequence = self._arrival_sequence
        self._arrival_sequence += 1
        heapq.heappush(self._heap, (event.timestamp, sequence, envelope))
        self._seen.add(envelope.event_id)
        self._accepted += 1
        if self.journal is not None:
            self.journal.append({"action": "accept", "envelope": envelope})
        return IngestResult(IngestStatus.ACCEPTED, envelope.event_id, len(self._heap))

    def drain_until(
        self, watermark: datetime, *, max_events: int | None = None
    ) -> tuple[StreamEnvelope, ...]:
        _require_utc(watermark, "stream watermark")
        if max_events is not None and max_events <= 0:
            raise ValueError("max_events must be positive when provided")
        emitted: list[StreamEnvelope] = []
        while self._heap and self._heap[0][0] <= watermark:
            if max_events is not None and len(emitted) >= max_events:
                break
            _, _, envelope = heapq.heappop(self._heap)
            if (
                self._last_emitted_at is not None
                and envelope.event.timestamp < self._last_emitted_at
            ):
                raise ValueError("stream buffer ordering invariant was violated")
            self._last_emitted_at = envelope.event.timestamp
            emitted.append(envelope)
            if self.journal is not None:
                self.journal.append({"action": "emit", "event_id": envelope.event_id})
        return tuple(emitted)

    def close(self) -> tuple[StreamEnvelope, ...]:
        if self._closed:
            return ()
        drained = (
            self.drain_until(datetime.max.replace(tzinfo=self._heap[0][0].tzinfo))
            if self._heap
            else ()
        )
        self._closed = True
        if self.journal is not None:
            self.journal.append({"action": "close"})
        return drained

    @property
    def health(self) -> IngestionHealth:
        return IngestionHealth(
            len(self._heap),
            self._accepted,
            self._duplicates,
            self._late,
            self._backpressure,
            self._recovered,
            self._closed,
            self._last_emitted_at,
        )
