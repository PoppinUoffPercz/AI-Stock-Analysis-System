from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_bot_package_imports_from_an_unrelated_directory_without_market_imports(
    tmp_path,
) -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            'import sys; import scion_omaha_bots; assert "yfinance" not in sys.modules',
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_bot_package_exports_stable_runner_seams(monkeypatch) -> None:
    from scion_omaha_bots import runners

    class FakeEntrypoint:
        @staticmethod
        def main(argv):
            return 7 if argv == ["--probe"] else 0

    monkeypatch.setattr(
        runners,
        "_load_legacy_entrypoint",
        lambda filename, module_name: FakeEntrypoint,
    )

    assert runners.scion_main(["--probe"]) == 7
    assert runners.omaha_main(["--probe"]) == 7
