from __future__ import annotations

import json

import pytest

from backtest_engine.experiment_index import ExperimentIndex
from backtest_engine.reproducibility import RunManifest


def _manifest(run_id: str, identity_hash: str, *, strategy: str = "sma") -> RunManifest:
    return RunManifest.from_parts(
        stable={
            "strategy": {"name": strategy},
            "engine": "vectorbt",
            "data": {"content_sha256": "data-hash"},
            "params": {"fast": 5},
        },
        provenance={"run_id": run_id, "created_at": "2026-01-01T00:00:00Z"},
        identity_hash=identity_hash,
    )


def test_index_appends_looks_up_filters_and_discovers_comparisons(tmp_path):
    index = ExperimentIndex(tmp_path / "experiments.jsonl")
    index.append(_manifest("r1", "one"))
    index.append(_manifest("r2", "two"))
    index.append(_manifest("r3", "three", strategy="rsi"))
    index.append(_manifest("r1", "one"))

    assert index.get("r1")["identity_hash"] == "one"
    assert [item["run_id"] for item in index.filter(engine="vectorbt", strategy="rsi")] == ["r3"]
    assert [item["run_id"] for item in index.comparisons("r1")] == ["r2"]
    assert len((tmp_path / "experiments.jsonl").read_text().splitlines()) == 3


def test_index_rejects_conflicting_run_id(tmp_path):
    index = ExperimentIndex(tmp_path / "experiments.jsonl")
    index.append(_manifest("r1", "one"))

    with pytest.raises(ValueError, match="run_id r1"):
        index.append(_manifest("r1", "different"))


def test_index_reports_corrupt_line_number(tmp_path):
    path = tmp_path / "experiments.jsonl"
    path.write_text(json.dumps({"run_id": "ok"}) + "\n{broken\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"experiments.jsonl:2"):
        ExperimentIndex(path).get("ok")
