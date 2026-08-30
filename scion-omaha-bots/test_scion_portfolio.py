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
    assert manager.trade_log[-1]["realized_pnl"] == pytest.approx(1_000.0)
    final = manager.close_position("TEST", price=130.0)

    assert partial["cost_basis"] == pytest.approx(5_000.0)
    assert partial["realized_pnl"] == pytest.approx(1_000.0)
    assert final["cost_basis"] == pytest.approx(5_000.0)
    assert final["realized_pnl"] == pytest.approx(1_500.0)
    assert partial["realized_pnl"] + final["realized_pnl"] == pytest.approx(2_500.0)
