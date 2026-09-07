"""Focused accounting tests for the Omaha portfolio manager."""

from types import SimpleNamespace

import pytest
import scion_omaha_bots.buffett_portfolio as buffett_portfolio
from buffett_portfolio import BuffettPortfolioManager


def test_buffett_trim_realizes_only_sold_cost_basis(tmp_path):
    manager = BuffettPortfolioManager(
        capital=40_000.0,
        portfolio_file=str(tmp_path / "buffett.json"),
    )
    manager.open_position("TEST", entry_price=100.0)

    partial = manager.trim_position("TEST", price=120.0, pct_to_sell=0.50)
    assert manager.positions["TEST"]["cost_basis"] == pytest.approx(5_000.0)
    assert manager.positions["TEST"]["position_pct"] == pytest.approx(0.125)
    assert manager.trade_log[-1]["realized_pnl"] == pytest.approx(1_000.0)
    final = manager.close_position("TEST", price=130.0)

    assert partial["cost_basis"] == pytest.approx(5_000.0)
    assert partial["realized_pnl"] == pytest.approx(1_000.0)
    assert final["cost_basis"] == pytest.approx(5_000.0)
    assert final["realized_pnl"] == pytest.approx(1_500.0)
    assert partial["realized_pnl"] + final["realized_pnl"] == pytest.approx(2_500.0)


def test_buffett_full_trim_removes_position(tmp_path):
    manager = BuffettPortfolioManager(
        capital=40_000.0,
        portfolio_file=str(tmp_path / "buffett.json"),
    )
    manager.open_position("TEST", entry_price=100.0)

    result = manager.trim_position("TEST", price=110.0, pct_to_sell=1.0)

    assert result["action"] == "TRIMMED"
    assert result["shares_remaining"] == 0
    assert "TEST" not in manager.positions


def test_buffett_rejects_cash_clipped_position_below_minimum(tmp_path):
    manager = BuffettPortfolioManager(
        capital=100_000.0,
        portfolio_file=str(tmp_path / "buffett.json"),
    )
    manager.cash = 4_000.0

    result = manager.open_position("TEST", entry_price=100.0)

    assert result["action"] == "REJECTED"
    assert manager.positions == {}
    assert manager.cash == 4_000.0


def test_buffett_rejects_whole_share_rounding_below_minimum(tmp_path):
    manager = BuffettPortfolioManager(
        capital=100_000.0,
        portfolio_file=str(tmp_path / "buffett.json"),
    )
    manager.cash = 5_000.0

    result = manager.open_position("TEST", entry_price=4_900.0)

    assert result["action"] == "REJECTED"
    assert manager.positions == {}
    assert manager.cash == 5_000.0


def test_buffett_reports_actual_cash_limited_allocation(tmp_path):
    manager = BuffettPortfolioManager(
        capital=100_000.0,
        portfolio_file=str(tmp_path / "buffett.json"),
    )
    manager.cash = 10_000.0

    result = manager.open_position("TEST", entry_price=100.0)

    assert result["action"] == "BOUGHT"
    assert result["allocation_pct"] == pytest.approx(10.0)
    assert manager.positions["TEST"]["position_pct"] == pytest.approx(0.10)


def test_buffett_nonpositive_intrinsic_value_is_not_positive_margin_of_safety(
    tmp_path, monkeypatch
):
    manager = BuffettPortfolioManager(
        capital=100_000.0,
        portfolio_file=str(tmp_path / "buffett.json"),
    )
    monkeypatch.setattr(
        buffett_portfolio.yf,
        "Ticker",
        lambda symbol: SimpleNamespace(
            info={
                "freeCashflow": 1_000_000.0,
                "sharesOutstanding": 1_000_000.0,
                "currentPrice": 100.0,
                "totalDebt": 1_000_000_000.0,
                "totalCash": 0.0,
            }
        ),
    )

    result = manager.estimate_intrinsic_value("TEST")

    assert result is not None
    assert result["intrinsic_value"] <= 0
    assert result["margin_of_safety"] < 0
