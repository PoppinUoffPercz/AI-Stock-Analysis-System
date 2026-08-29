# ponytail: single self-check for the STOP_WIDTH rule; delete when feedback.py grows real tests
import feedback


def _eng(rows):
    e = object.__new__(feedback.FeedbackEngine)
    e.metrics = {"closed_trades": rows}
    e.recommendations = []
    return e


def row(pnl, entry, stop):
    return {"pnl_pct": pnl, "entry_price": entry, "stop_loss": stop}


# avg stop distance on winners 20% (> 12%) over 15 trades -> fires
e = _eng([row(10, 100, 80)] * 15)
e.check_stop_width()
assert len(e.recommendations) == 1 and e.recommendations[0]["rule"] == "STOP_WIDTH"

# avg stop distance 5% -> no fire
e2 = _eng([row(10, 100, 95)] * 15)
e2.check_stop_width()
assert e2.recommendations == []

# fewer than 15 trades -> no fire
e3 = _eng([row(10, 100, 80)] * 8)
e3.check_stop_width()
assert e3.recommendations == []

# losers don't count toward the average (wide stops on losers = fine)
e4 = _eng([row(-5, 100, 40)] * 15)
e4.check_stop_width()
assert e4.recommendations == []

print("STOP_WIDTH self-check OK")
