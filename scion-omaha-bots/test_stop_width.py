# ponytail: single self-check for the STOP_WIDTH rule; delete when feedback.py grows real tests
import feedback


def _eng(rows):
    e = object.__new__(feedback.FeedbackEngine)
    e.metrics = {"closed_trades": rows}
    e.recommendations = []
    return e


def _row(pnl, entry, stop):
    return {"pnl_pct": pnl, "entry_price": entry, "stop_loss": stop}


def test_wide_stops_on_winners_trigger_recommendation():
    # avg stop distance on winners 20% (> 12%) over 15 trades -> fires
    engine = _eng([_row(10, 100, 80)] * 15)
    engine.check_stop_width()

    assert len(engine.recommendations) == 1
    assert engine.recommendations[0]["rule"] == "STOP_WIDTH"


def test_narrow_stops_do_not_trigger_recommendation():
    engine = _eng([_row(10, 100, 95)] * 15)
    engine.check_stop_width()

    assert engine.recommendations == []


def test_stop_width_requires_at_least_fifteen_trades():
    engine = _eng([_row(10, 100, 80)] * 8)
    engine.check_stop_width()

    assert engine.recommendations == []


def test_losing_trades_do_not_count_toward_winner_stop_width():
    engine = _eng([_row(-5, 100, 40)] * 15)
    engine.check_stop_width()

    assert engine.recommendations == []
