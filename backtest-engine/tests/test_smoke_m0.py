"""M0 smoke tests: validate package imports, settings, CLI plumbing, and that
the heavy engine adapters we'll need in M2/M4/M9 can be imported.

These tests intentionally avoid network / heavy compute: they exist to catch
regressions in the skeleton wiring before we layer logic on top.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

# --- Package ---------------------------------------------------------------


def test_package_imports():
    import backtest_engine

    assert backtest_engine.__version__ == "0.1.0"


def test_submodules_importable():
    for sub in ("config", "cli"):
        importlib.import_module(f"backtest_engine.{sub}")


# --- Settings ---------------------------------------------------------------


def test_settings_defaults():
    from backtest_engine.config import Settings

    s = Settings()
    assert s.default_capital == 100_000.0
    assert s.default_cost == "us_equity_pershare"
    assert s.default_slippage == "linear_impact"
    assert s.annualize_factor == 252


def test_resolve_settings_absoluteizes_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from backtest_engine.config import resolve_settings

    s = resolve_settings()
    assert s.data_dir.is_absolute()
    assert s.raw_dir == tmp_path / "data" / "raw"
    assert s.outputs_dir == tmp_path / "outputs"


def test_settings_forbid_extra():
    from pydantic import ValidationError

    from backtest_engine.config import Settings

    with pytest.raises(ValidationError):
        Settings(bogus_field=True)  # type: ignore[call-arg]


# --- CLI -------------------------------------------------------------------


def test_cli_version(capsys):
    from backtest_engine.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "bte 0.1.0" in out


def test_cli_settings_prints_json(capsys):
    from backtest_engine.cli import main

    rc = main(["settings"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "default_capital" in out


def test_cli_unknown_command_returns_error(capsys):
    # `foo` is never registered; argparse rejects it with SystemExit(2).
    from backtest_engine.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["foo"])
    assert exc.value.code == 2


# --- Heavy engines (the whole point of the hybrid stack) -------------------


@pytest.mark.parametrize("mod", ["vectorbt", "backtrader", "nautilus_trader"])
def test_engine_dependency_importable(mod):
    # NautilusTrader will be needed in M9; confirm now so there are no surprises.
    pytest.importorskip(mod)


# --- Repo structure (catches accidental restructuring) ---------------------


def test_expected_directories_exist():
    here = Path(__file__).resolve().parent.parent
    for sub in [
        "src/backtest_engine",
        "src/backtest_engine/data",
        "src/backtest_engine/strategy",
        "src/backtest_engine/execution",
        "src/backtest_engine/portfolio",
        "src/backtest_engine/validation",
        "src/backtest_engine/metrics",
        "src/backtest_engine/pipeline",
        "tests",
        "data/raw",
        "data/clean",
        "data/universe",
        "outputs",
        "strategies",
    ]:
        assert (here / sub).is_dir(), f"missing dir: {sub}"


def test_pyproject_toml_present_and_parses():
    import tomllib

    here = Path(__file__).resolve().parent.parent
    with (here / "pyproject.toml").open("rb") as f:
        data = tomllib.load(f)
    assert data["project"]["name"] == "backtest-engine"
    assert "bte" in data["project"]["scripts"]


def test_repository_ci_and_optional_dependency_contract():
    import tomllib

    package_root = Path(__file__).resolve().parent.parent
    repository_root = package_root.parent
    workflow = repository_root / ".github" / "workflows" / "backtest-engine-ci.yml"
    assert workflow.is_file()
    assert not (package_root / ".github" / "workflows" / "ci.yml").exists()

    workflow_text = workflow.read_text(encoding="utf-8")
    assert "working-directory: backtest-engine" in workflow_text
    assert "mypy src" in workflow_text
    assert "|| true" not in workflow_text
    for job in (
        "optional-execution:",
        "optional-broker:",
        "optional-statistics:",
        "optional-reporting:",
    ):
        assert job in workflow_text
    for extra in (".[dev,execution]", ".[dev,broker]", ".[dev,statistics]", ".[dev,reporting]"):
        assert extra in workflow_text

    with (package_root / "pyproject.toml").open("rb") as f:
        project = tomllib.load(f)["project"]
    core = project["dependencies"]
    optional = project["optional-dependencies"]

    assert not any(dep.startswith("nautilus_trader") for dep in core)
    assert not any(dep.startswith("alpaca-py") for dep in core)
    assert not any(
        dep.startswith(name) for dep in core for name in ("scipy", "statsmodels", "scikit-learn")
    )
    assert not any(
        dep.startswith(name) for dep in core for name in ("quantstats", "plotly", "matplotlib")
    )
    assert any(dep.startswith("nautilus_trader") for dep in optional["execution"])
    assert any(dep.startswith("alpaca-py") for dep in optional["broker"])
    assert any(dep.startswith("scipy") for dep in optional["statistics"])
    assert any(dep.startswith("quantstats") for dep in optional["reporting"])
    assert any(dep.startswith("pandas-stubs") for dep in optional["dev"])
