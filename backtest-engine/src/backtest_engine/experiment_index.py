"""Strict append-only JSONL index of completed backtest reports."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from backtest_engine.reproducibility import RunManifest, canonical_json

_LOCK = threading.Lock()


class ExperimentIndex:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def append(
        self,
        manifest: RunManifest,
        *,
        artifacts: dict[str, str] | None = None,
        benchmark: dict[str, Any] | None = None,
    ) -> None:
        record = {
            "run_id": manifest.run_id,
            "identity_hash": manifest.identity_hash,
            "created_at": manifest.provenance.get("created_at"),
            "strategy": manifest.stable.get("strategy", {}).get("name"),
            "engine": manifest.stable.get("engine"),
            "params": manifest.stable.get("params", {}),
            "data_hash": manifest.stable.get("data", {}).get("content_sha256"),
            "artifacts": artifacts or {},
            "benchmark": benchmark,
        }
        line = canonical_json(record) + "\n"
        with _LOCK:
            records = self._read_unlocked()
            existing = next(
                (item for item in records if item.get("run_id") == manifest.run_id), None
            )
            if existing is not None:
                if existing.get("identity_hash") != manifest.identity_hash:
                    raise ValueError(f"run_id {manifest.run_id} already has a different identity")
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())

    def get(self, run_id: str) -> dict[str, Any]:
        matches = self.filter(run_id=run_id)
        if not matches:
            raise KeyError(run_id)
        return matches[0]

    def filter(self, **criteria: object) -> list[dict[str, Any]]:
        with _LOCK:
            records = self._read_unlocked()
        return [
            item
            for item in records
            if all(item.get(key) == value for key, value in criteria.items())
        ]

    def comparisons(self, run_id: str) -> list[dict[str, Any]]:
        target = self.get(run_id)
        return [
            item
            for item in self.filter(strategy=target.get("strategy"))
            if item.get("run_id") != run_id
        ]

    def _read_unlocked(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records = []
        run_id_lines: dict[str, int] = {}
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"malformed experiment index at {self.path}:{line_number}: {exc.msg}"
                ) from exc
            if not isinstance(item, dict) or not isinstance(item.get("run_id"), str):
                raise ValueError(
                    f"malformed experiment index at {self.path}:{line_number}: expected object with run_id"
                )
            run_id = item["run_id"]
            if run_id in run_id_lines:
                raise ValueError(
                    f"malformed experiment index at {self.path}:{line_number}: duplicate run_id "
                    f"{run_id} (first seen on line {run_id_lines[run_id]}); remove the duplicate line"
                )
            run_id_lines[run_id] = line_number
            records.append(item)
        return records
