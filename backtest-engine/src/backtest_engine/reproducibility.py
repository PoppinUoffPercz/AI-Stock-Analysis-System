"""Immutable, deterministic provenance for reproducible backtest runs."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np
import pandas as pd

from backtest_engine.execution.costs import get_preset

MANIFEST_SCHEMA_VERSION = 1


def canonical_json(value: object) -> str:
    """Return the single JSON representation used for hashes and persisted records."""
    return json.dumps(
        _thaw(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def dataframe_sha256(frame: pd.DataFrame) -> str:
    """Hash a frame's index, columns, dtypes, and values without path metadata."""
    schema = {
        "columns": [_scalar(column) for column in frame.columns],
        "column_names": [_scalar(name) for name in frame.columns.names],
        "dtypes": [str(dtype) for dtype in frame.dtypes],
        "index_class": type(frame.index).__name__,
        "index_dtype": str(frame.index.dtype),
        "index_dtypes": [str(dtype) for dtype in frame.index.to_frame(index=False).dtypes],
        "index_names": [_scalar(name) for name in frame.index.names],
        "rows": len(frame),
    }
    digest = hashlib.sha256(canonical_json(schema).encode("utf-8"))
    hashes = pd.util.hash_pandas_object(frame, index=True, categorize=False).to_numpy(dtype="<u8")
    digest.update(hashes.tobytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class RunManifest:
    """Deeply immutable stable identity and volatile run provenance."""

    stable: Mapping[str, Any]
    provenance: Mapping[str, Any]
    identity_hash: str
    schema_version: int = MANIFEST_SCHEMA_VERSION

    @classmethod
    def from_parts(
        cls,
        *,
        stable: Mapping[str, Any],
        provenance: Mapping[str, Any],
        identity_hash: str | None = None,
    ) -> RunManifest:
        frozen_stable = _freeze(stable)
        return cls(
            stable=frozen_stable,
            provenance=_freeze(provenance),
            identity_hash=identity_hash
            or hashlib.sha256(canonical_json(frozen_stable).encode("utf-8")).hexdigest(),
        )

    @property
    def run_id(self) -> str:
        return str(self.provenance["run_id"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity_hash": self.identity_hash,
            "stable": _thaw(self.stable),
            "provenance": _thaw(self.provenance),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict()) + "\n"

    @classmethod
    def load(cls, path: Path) -> RunManifest:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in manifest {path}: {exc.msg}") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != MANIFEST_SCHEMA_VERSION
        ):
            raise ValueError(f"unsupported or malformed manifest: {path}")
        try:
            manifest = cls.from_parts(
                stable=payload["stable"],
                provenance=payload["provenance"],
                identity_hash=str(payload["identity_hash"]),
            )
            expected = hashlib.sha256(canonical_json(manifest.stable).encode("utf-8")).hexdigest()
            if manifest.identity_hash != expected:
                raise ValueError(f"manifest identity hash does not match stable fields: {path}")
            return manifest
        except (KeyError, TypeError) as exc:
            raise ValueError(f"malformed manifest {path}: {exc}") from exc


def build_manifest(
    *,
    run_id: str,
    strategy_name: str,
    signal_factory: object | None,
    engine: str,
    params: Mapping[str, Any],
    capital: float,
    cost_model: str,
    universe_ref: str,
    ohlc: pd.DataFrame | None = None,
    signal_ohlc: pd.DataFrame | None = None,
    universe: str | Path | None = None,
    random_seed: int | None = None,
    relevant_args: Mapping[str, Any] | None = None,
    dataset_identity: Mapping[str, Any] | None = None,
) -> RunManifest:
    """Build the manifest after filtering, from exactly the bars sent to an adapter."""
    cost = get_preset(cost_model)
    data = {
        "content_sha256": dataframe_sha256(ohlc) if ohlc is not None else None,
        "rows": len(ohlc) if ohlc is not None else None,
        "identity": dict(dataset_identity or _dataset_identity(ohlc)),
    }
    universe_path = Path(universe) if universe is not None else None
    universe_identity = {
        "reference": universe_path.name if universe_path else _path_identity(universe_ref),
        "content_sha256": _file_sha256(universe_path) if universe_path else None,
    }
    stable = {
        "strategy": {"name": strategy_name, "signal": _callable_identity(signal_factory)},
        "engine": engine,
        "params": dict(params),
        "capital": capital,
        "cost": {"name": cost_model, "config": vars(cost)},
        "data": data,
        "signal_data": (
            {
                "content_sha256": dataframe_sha256(signal_ohlc),
                "rows": len(signal_ohlc),
                "identity": _dataset_identity(signal_ohlc),
            }
            if signal_ohlc is not None
            else None
        ),
        "universe": universe_identity,
        "random_seed": random_seed,
        "args": dict(relevant_args or {}),
        "code": _git_state(),
        "runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "dependencies": _dependency_versions(),
        },
    }
    return RunManifest.from_parts(
        stable=stable,
        provenance={
            "run_id": run_id,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        },
    )


def fallback_manifest(result: Any) -> RunManifest:
    """Create explicit partial provenance for hand-built/legacy result objects."""
    return build_manifest(
        run_id=result.run_id,
        strategy_name=result.strategy_name,
        signal_factory=None,
        engine=result.engine,
        params=result.params,
        capital=result.capital,
        cost_model=result.cost_model,
        universe_ref=result.universe_ref,
        dataset_identity={"status": "unavailable", "reason": "source data not attached"},
    )


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted((_freeze(item) for item in value), key=repr))
    return _scalar(value)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return _scalar(value)


def _scalar(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return value.name
    return value


def _dataset_identity(ohlc: pd.DataFrame | None) -> dict[str, Any]:
    if ohlc is None:
        return {"status": "unavailable", "reason": "source data not attached"}
    identity: dict[str, Any] = {}
    for key in ("symbol", "source", "dataset"):
        if key in ohlc.attrs:
            identity[key] = _scalar(ohlc.attrs[key])
    if len(ohlc):
        identity["start"] = _scalar(ohlc.index[0])
        identity["end"] = _scalar(ohlc.index[-1])
    return identity


def _path_identity(value: str) -> str:
    path = Path(value)
    return path.name if path.is_absolute() else path.as_posix()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _callable_identity(value: object | None) -> str | None:
    if value is None:
        return None
    module = getattr(value, "__module__", type(value).__module__)
    name = getattr(value, "__qualname__", type(value).__qualname__)
    return f"{module}.{name}"


def _git_state() -> dict[str, Any]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
            ).stdout
        )
        return {"revision": revision, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"revision": None, "dirty": None}


def _dependency_versions() -> dict[str, str]:
    versions = {}
    for name in ("backtest-engine", "numpy", "pandas", "vectorbt", "backtrader", "nautilus-trader"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return versions
