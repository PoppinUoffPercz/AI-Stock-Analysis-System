from __future__ import annotations

import pytest
from scion_omaha_bots import tracker as tracker_module


def test_failed_exit_ledger_write_preserves_open_position(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tracker_module, "TRADES_FILE", str(tmp_path / "trades.csv"))
    monkeypatch.setattr(tracker_module, "DAILY_PNL_FILE", str(tmp_path / "daily.csv"))
    monkeypatch.setattr(
        tracker_module, "OPEN_POSITIONS_FILE", str(tmp_path / "open_positions.json")
    )
    monkeypatch.setattr(tracker_module, "_check_price_in_day_range", lambda *args: None)

    tracker = tracker_module.Tracker()
    tracker.save_open_positions(
        {
            "AAA": {
                "ticker": "AAA",
                "bot": "scion",
                "entry_date": "2026-09-01",
                "entry_price": 10.0,
                "status": "OPEN",
            }
        }
    )
    blocked_path = tmp_path / "blocked-ledger"
    blocked_path.mkdir()
    tracker.trades_file = str(blocked_path)

    with pytest.raises(OSError):
        tracker.log_exit("AAA", exit_price=11.0)

    assert "AAA" in tracker.load_open_positions()
    assert "LOGGED EXIT" not in capsys.readouterr().out
