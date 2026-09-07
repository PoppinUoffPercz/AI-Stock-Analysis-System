from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="requires a Git checkout")
def test_source_manifest_excludes_tracked_runtime_state():
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    forbidden = [path for path in tracked if Path(path).name == "shadow_log.csv"]

    assert forbidden == []
