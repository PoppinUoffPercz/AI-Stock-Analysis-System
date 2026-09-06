"""Ensure tests and spawned workers import this worktree's sources."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = str(ROOT / "src")
MONOREPO_ROOT = str(ROOT.parent)

sys.path.insert(0, SOURCE)
sys.path.insert(0, MONOREPO_ROOT)
os.environ["PYTHONPATH"] = os.pathsep.join(
    [SOURCE, MONOREPO_ROOT, os.environ.get("PYTHONPATH", "")]
)
