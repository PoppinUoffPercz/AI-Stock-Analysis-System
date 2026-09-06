"""Test the current monorepo sources rather than unrelated editable installs."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BOT_SOURCE = str(ROOT / "scion-omaha-bots" / "src")
sys.path.insert(0, BOT_SOURCE)
os.environ["PYTHONPATH"] = os.pathsep.join(
    [str(ROOT), BOT_SOURCE, str(ROOT / "backtest-engine" / "src"), os.environ.get("PYTHONPATH", "")]
)
