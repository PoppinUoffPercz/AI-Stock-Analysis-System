from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from stock_analysis.artifacts import ArtifactRef, ArtifactStore

from .models import _require_utc


@dataclass(frozen=True, slots=True)
class SnapshotEnvelope:
    """One immutable vendor observation with explicit point-in-time availability."""

    symbol: str
    dataset: str
    provider: str
    effective_at: datetime
    observed_at: datetime
    received_at: datetime
    available_at: datetime
    revision_id: str
    payload: Any
    schema_version: int = 1

    def __post_init__(self) -> None:
        for value, label in (
            (self.effective_at, "effective_at"),
            (self.observed_at, "observed_at"),
            (self.received_at, "received_at"),
            (self.available_at, "available_at"),
        ):
            _require_utc(value, label)
        if not self.symbol or not self.dataset or not self.provider:
            raise ValueError("symbol, dataset, and provider must not be empty")
        if not self.revision_id:
            raise ValueError("revision_id must not be empty")
        if self.received_at < self.observed_at:
            raise ValueError("received_at must not precede observed_at")
        if self.available_at < self.observed_at:
            raise ValueError("available_at must not precede observed_at")
        if self.schema_version != 1:
            raise ValueError("unsupported snapshot schema version")

    def identity_value(self) -> dict[str, Any]:
        """Deterministic identity excludes local receipt wall-clock metadata."""
        return {
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "dataset": self.dataset,
            "provider": self.provider,
            "effective_at": self.effective_at,
            "observed_at": self.observed_at,
            "available_at": self.available_at,
            "revision_id": self.revision_id,
            "payload": self.payload,
        }


class PointInTimeStore:
    """Small persisted as-of selector for normalized snapshots and revisions."""

    def __init__(self, root: str | Path, *, mode: str = "research") -> None:
        self.artifacts = ArtifactStore(root, mode=mode)

    def ingest(self, snapshot: SnapshotEnvelope) -> ArtifactRef:
        return self.artifacts.save(
            "snapshots",
            snapshot,
            identity_value=snapshot.identity_value(),
        )

    def as_of(
        self,
        symbol: str,
        dataset: str,
        decision_time: datetime,
    ) -> SnapshotEnvelope | None:
        _require_utc(decision_time, "decision_time")
        candidates = [
            snapshot
            for snapshot in self._load_all()
            if snapshot.symbol == symbol
            and snapshot.dataset == dataset
            and snapshot.available_at <= decision_time
            and snapshot.received_at <= decision_time
        ]
        if not candidates:
            return None
        latest_key = max(
            (item.available_at, item.observed_at, item.received_at)
            for item in candidates
        )
        latest = [
            item
            for item in candidates
            if (item.available_at, item.observed_at, item.received_at) == latest_key
        ]
        if len(latest) != 1:
            raise ValueError(
                "ambiguous point-in-time revision ordering; distinct revisions share "
                "available_at, observed_at, and received_at"
            )
        return latest[0]

    def _load_all(self) -> tuple[SnapshotEnvelope, ...]:
        directory = self.artifacts.root / self.artifacts.mode / "snapshots"
        if not directory.exists():
            return ()
        snapshots: list[SnapshotEnvelope] = []
        for path in sorted(directory.glob("*.json")):
            value = self.artifacts.load_path(path)
            if not isinstance(value, SnapshotEnvelope):
                raise TypeError(f"snapshot artifact has unexpected type: {path.name}")
            snapshots.append(value)
        return tuple(snapshots)
