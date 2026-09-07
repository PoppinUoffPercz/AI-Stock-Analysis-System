from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stock_analysis.market_analytics.serialization import from_jsonable, to_jsonable
from stock_analysis.persistence import atomic_write_json, process_lock
from stock_analysis.validation import validate_identifier

SCHEMA_VERSION = 2
_MODES = {"research", "replay", "paper", "live"}


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    kind: str
    identity: str
    path: Path
    schema_version: int = SCHEMA_VERSION

    def to_record(self) -> dict[str, object]:
        """Return the portable identity fields safe to embed in other artifacts."""
        return {
            "kind": self.kind,
            "identity": self.identity,
            "schema_version": self.schema_version,
        }


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _hash_jsonable(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def content_identity(value: Any) -> str:
    return _hash_jsonable(to_jsonable(value))


class ArtifactStore:
    def __init__(self, root: str | Path, *, mode: str = "research") -> None:
        if mode not in _MODES:
            raise ValueError(f"unsupported artifact mode: {mode}")
        self.root = Path(root)
        self.mode = mode

    def save(
        self,
        kind: str,
        value: Any,
        *,
        identity_value: Any | None = None,
    ) -> ArtifactRef:
        kind = validate_identifier(kind, field_name="artifact kind")
        payload = to_jsonable(value)
        identity_payload = to_jsonable(
            value if identity_value is None else identity_value
        )
        identity = _hash_jsonable(identity_payload)
        path = self.root / self.mode / kind / f"{identity}.json"
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "kind": kind,
            "identity": identity,
            "identity_payload": identity_payload,
            "payload_hash": _hash_jsonable(payload),
            "payload": payload,
        }
        with process_lock(path.with_suffix(".lock")):
            if path.exists():
                self._validate_envelope(
                    json.loads(path.read_text(encoding="utf-8")),
                    kind,
                    expected_identity=identity,
                )
            else:
                atomic_write_json(path, envelope)
        return ArtifactRef(kind, identity, path, SCHEMA_VERSION)

    def load(self, reference: ArtifactRef) -> Any:
        if reference.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported artifact reference schema version")
        envelope = json.loads(reference.path.read_text(encoding="utf-8"))
        self._validate_envelope(
            envelope, reference.kind, expected_identity=reference.identity
        )
        return from_jsonable(envelope["payload"])

    def reference(self, kind: str, identity: str) -> ArtifactRef:
        """Resolve an exact historical identity without selecting a newer artifact."""
        kind = validate_identifier(kind, field_name="artifact kind")
        identity = validate_identifier(identity, field_name="artifact identity")
        reference = ArtifactRef(
            kind,
            identity,
            self.root / self.mode / kind / f"{identity}.json",
            SCHEMA_VERSION,
        )
        if not reference.path.is_file():
            raise FileNotFoundError(f"missing artifact reference: {kind}/{identity}")
        self.load(reference)
        return reference

    def load_path(self, path: str | Path) -> Any:
        target = Path(path)
        envelope = json.loads(target.read_text(encoding="utf-8"))
        self._validate_envelope(
            envelope,
            target.parent.name,
            expected_identity=target.stem,
        )
        return from_jsonable(envelope["payload"])

    @staticmethod
    def _validate_envelope(
        envelope: Any,
        expected_kind: str,
        *,
        expected_identity: str | None = None,
    ) -> None:
        if not isinstance(envelope, dict):
            raise ValueError("artifact envelope must be an object")
        if envelope.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported artifact schema version")
        if envelope.get("kind") != expected_kind:
            raise ValueError("artifact kind mismatch")
        payload = envelope.get("payload")
        if envelope.get("payload_hash") != _hash_jsonable(payload):
            raise ValueError("artifact payload hash does not match payload")
        identity_payload = envelope.get("identity_payload")
        actual_identity = _hash_jsonable(identity_payload)
        stored_identity = envelope.get("identity")
        if stored_identity != actual_identity:
            raise ValueError("artifact identity does not match identity payload")
        if expected_identity is not None and stored_identity != expected_identity:
            raise ValueError("artifact identity does not match reference")
