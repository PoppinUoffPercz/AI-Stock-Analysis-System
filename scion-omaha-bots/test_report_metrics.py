from types import SimpleNamespace

import pandas as pd
import pytest
import report_card


def tracker(rows):
    return SimpleNamespace(get_closed_trades=lambda **kw: rows, get_open_positions_summary=lambda: [])


def test_invalid_prices_are_unavailable():
    for entry, exit_price in [(0, 100), (-1, 100), (None, 100), (100, None), (float('nan'), 100)]:
        assert report_card.compute_alpha_for_trade(entry, exit_price, '2026-01-02', '2026-01-05') == (None, None)


def test_report_does_not_treat_missing_trade_as_a_loss(monkeypatch):
    monkeypatch.setattr(report_card, '_fetch_benchmark_return', lambda *args: None)
    rows = [{'entry_price': '100', 'exit_price': '110', 'pnl_pct': '10'}, {'entry_price': '', 'exit_price': '', 'pnl_pct': ''}]
    metrics = report_card.compute_metrics(tracker(rows))
    assert metrics['wins'] == 1
    assert metrics['losses'] == 0
    assert metrics['unavailable_trades'] == 1
    assert metrics['win_rate'] == 100
    assert metrics['total_pnl_pct'] == 10
    assert '_alpha' not in rows[0]


def test_benchmark_never_uses_future_bars(monkeypatch):
    report_card._fetch_benchmark_prices.cache_clear()
    hist = pd.DataFrame({'Close': [100., 110., 200.]}, index=pd.to_datetime(['2026-01-02', '2026-01-05', '2026-01-06']))
    import yfinance
    monkeypatch.setattr(yfinance, 'Ticker', lambda _: SimpleNamespace(history=lambda **kw: hist))
    assert report_card._fetch_benchmark_return('SPY', '2026-01-02', '2026-01-05') == pytest.approx(.1)


def test_report_batches_spy_history_once(monkeypatch):
    report_card._fetch_benchmark_prices.cache_clear()
    calls = []
    hist = pd.DataFrame(
        {'Close': [100., 105., 110.]},
        index=pd.to_datetime(['2026-01-02', '2026-01-05', '2026-01-06']),
    )
    import yfinance

    def history(**kwargs):
        calls.append(kwargs)
        return hist

    monkeypatch.setattr(yfinance, 'Ticker', lambda _: SimpleNamespace(history=history))
    rows = [
        {'entry_price': '100', 'exit_price': '110', 'entry_date': '2026-01-02', 'exit_date': '2026-01-05'},
        {'entry_price': '50', 'exit_price': '55', 'entry_date': '2026-01-05', 'exit_date': '2026-01-06'},
    ]
    metrics = report_card.compute_metrics(tracker(rows))
    assert len(calls) == 1
    assert metrics['alpha_count'] == 2


def test_report_names_arithmetic_aggregates_honestly(tmp_path, monkeypatch):
    monkeypatch.setattr(report_card, '_ensure_vault_dir', lambda: str(tmp_path))
    monkeypatch.setattr(report_card, '_fetch_benchmark_return', lambda *args: None)
    report = report_card.generate_markdown_report(tracker([]))
    assert 'Total Return (Closed)' not in report
    assert 'Cumulative Alpha' not in report
    assert 'portfolio return' in report.lower()
