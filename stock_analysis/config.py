"""Path configuration for the integrated command line interface."""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path

STATE_ROOT_ENV = "STOCK_ANALYSIS_STATE_ROOT"
DATA_ROOT_ENV = "STOCK_ANALYSIS_DATA_ROOT"
OUTPUTS_ROOT_ENV = "STOCK_ANALYSIS_OUTPUTS_ROOT"


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Resolved roots shared by the integrated CLI and legacy modules."""

    project_root: Path
    state_root: Path
    data_root: Path
    outputs_root: Path

    @classmethod
    def from_args(
        cls,
        *,
        project_root: Path,
        state_root: Path | None = None,
        data_root: Path | None = None,
        outputs_root: Path | None = None,
    ) -> AppPaths:
        cwd = Path.cwd()

        def resolve(value: Path | None, default: Path) -> Path:
            path = value if value is not None else default
            return path if path.is_absolute() else cwd / path

        return cls(
            project_root=project_root,
            state_root=resolve(state_root, project_root / "scion-omaha-bots"),
            data_root=resolve(data_root, cwd / "data"),
            outputs_root=resolve(outputs_root, cwd / "outputs"),
        )

    def apply(self, environment: MutableMapping[str, str] | None = None) -> None:
        """Expose roots to flat legacy modules for the lifetime of this process."""
        target = os.environ if environment is None else environment
        target[STATE_ROOT_ENV] = str(self.state_root)
        target[DATA_ROOT_ENV] = str(self.data_root)
        target[OUTPUTS_ROOT_ENV] = str(self.outputs_root)
