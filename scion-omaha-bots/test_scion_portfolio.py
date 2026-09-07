"""Focused accounting tests for the Scion portfolio manager."""

import pytest
from portfolio import ScionPortfolioManager


def test_scion_scale_out_realizes_only_sold_cost_basis(tmp_path):
    manager = ScionPortfolioManager(
        capital=125_000.0,
        portfolio_file=str(tmp_path / "scion.json"),
    )
    manager.open_position(
        "TEST",
        entry_price=100.0,
        stop_loss=80.0,
        target_1=120.0,
        target_2=140.0,
        position_pct=0.08,
    )

    partial = manager.scale_out("TEST", price=120.0, pct_to_sell=0.50)
    assert manager.positions["TEST"]["cost_basis"] == pytest.approx(5_000.0)
    assert manager.positions["TEST"]["position_pct"] == pytest.approx(0.04)
    assert manager.trade_log[-1]["realized_pnl"] == pytest.approx(1_000.0)
    final = manager.close_position("TEST", price=130.0)

    assert partial["cost_basis"] == pytest.approx(5_000.0)
    assert partial["realized_pnl"] == pytest.approx(1_000.0)
    assert final["cost_basis"] == pytest.approx(5_000.0)
    assert final["realized_pnl"] == pytest.approx(1_500.0)
    assert partial["realized_pnl"] + final["realized_pnl"] == pytest.approx(2_500.0)


def test_scion_rejects_allocation_above_configured_position_cap(tmp_path):
    manager = ScionPortfolioManager(
        capital=100_000.0,
        portfolio_file=str(tmp_path / "scion.json"),
    )

    result = manager.open_position(
        "TEST",
        entry_price=100.0,
        stop_loss=90.0,
        target_1=120.0,
        target_2=140.0,
        position_pct=0.50,
    )

    assert result["action"] == "REJECTED"
    assert manager.positions == {}
    assert manager.cash == manager.capital


def test_scion_rejects_allocation_below_configured_minimum(tmp_path):
    manager = ScionPortfolioManager(
        capital=100_000.0,
        portfolio_file=str(tmp_path / "scion.json"),
    )

    result = manager.open_position(
        "TEST",
        entry_price=100.0,
        stop_loss=90.0,
        target_1=120.0,
        target_2=140.0,
        position_pct=0.01,
    )

    assert result["action"] == "REJECTED"
    assert manager.positions == {}
    assert manager.cash == manager.capital


def test_scion_rejects_cash_clipped_position_below_minimum(tmp_path):
    manager = ScionPortfolioManager(
        capital=100_000.0,
        portfolio_file=str(tmp_path / "scion.json"),
    )
    manager.cash = 2_000.0

    result = manager.open_position("TEST", 100.0, 90.0, 120.0, 140.0)

    assert result["action"] == "REJECTED"
    assert manager.positions == {}
    assert manager.cash == 2_000.0


def test_scion_rejects_whole_share_rounding_below_minimum(tmp_path):
    manager = ScionPortfolioManager(
        capital=100_000.0,
        portfolio_file=str(tmp_path / "scion.json"),
    )
    manager.cash = 3_000.0

    result = manager.open_position("TEST", 2_900.0, 2_500.0, 3_480.0, 4_060.0)

    assert result["action"] == "REJECTED"
    assert manager.positions == {}
    assert manager.cash == 3_000.0


def test_scion_drawdown_uses_actual_cash_limited_position_size(tmp_path):
    manager = ScionPortfolioManager(
        capital=100_000.0,
        portfolio_file=str(tmp_path / "scion.json"),
    )
    manager.cash = 4_000.0
    manager.positions["OLD"] = {
        "shares": 130,
        "entry_price": 100.0,
        "cost_basis": 13_000.0,
        "stop_loss": 1.0,
        "target_1": 120.0,
        "target_2": 140.0,
        "score": 0,
        "reasons": "fixture",
        "position_pct": 0.13,
        "opened_date": "2026-01-01T00:00:00",
        "status": "OPEN",
        "partial_exit_done": False,
    }

    result = manager.open_position("NEW", 100.0, 50.0, 120.0, 140.0)

    assert result["action"] == "BOUGHT"
    assert result["cost"] == pytest.approx(4_000.0)
    assert manager.positions["NEW"]["position_pct"] == pytest.approx(0.04)


def test_scion_full_scale_out_removes_position(tmp_path):
    manager = ScionPortfolioManager(
        capital=100_000.0,
        portfolio_file=str(tmp_path / "scion.json"),
    )
    manager.open_position("TEST", 100.0, 90.0, 120.0, 140.0)

    result = manager.scale_out("TEST", price=110.0, pct_to_sell=1.0)

    assert result["action"] == "SCALED_OUT"
    assert result["shares_remaining"] == 0
    assert "TEST" not in manager.positions
