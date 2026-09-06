"""Independent bot contracts, captured before moving the legacy runtime."""
import importlib
import json
from types import SimpleNamespace

import pandas as pd
import pytest


@pytest.mark.parametrize('module,limit,allocation,label', [
    ('portfolio', 18, 0.08, 'SCION'),
    ('buffett_portfolio', 12, 0.25, 'OMAHA'),
])
def test_portfolio_contract(module, limit, allocation, label, tmp_path, monkeypatch):
    mod = importlib.import_module(module)
    cls = getattr(mod, 'ScionPortfolioManager' if module == 'portfolio' else 'BuffettPortfolioManager')
    path = tmp_path / 'state.json'
    manager = cls(capital=10000, portfolio_file=str(path))
    assert manager.max_positions == limit
    assert manager.max_position_pct == allocation
    assert label in manager.get_portfolio_summary()
    if module == 'portfolio':
        result = manager.open_position('AAPL', 100, 95, 120, 140)
    else:
        result = manager.open_position('AAPL', 100, intrinsic_value=150)
    assert result['action'] == 'BOUGHT'
    assert result['shares'] == int(10000 * allocation / 100)
    assert manager.cash == 10000 - result['shares'] * 100
    restored = cls(portfolio_file=str(path))
    assert restored.positions == manager.positions
    assert restored.cash == manager.cash
    assert json.loads(path.read_text())['capital'] == 10000
    monkeypatch.setattr(restored, 'get_current_price', lambda symbol: 110)
    assert 'AAPL' in restored.get_portfolio_summary()


@pytest.mark.parametrize('module', ['main', 'buffett_main'])
def test_cli_contract(module, capsys):
    mod = importlib.import_module(module)
    parser = mod.build_parser()
    assert parser.parse_args(['analyze', 'brk.b']).symbol == 'brk.b'
    assert parser.parse_args(['--notify', 'portfolio']).notify is True
    with pytest.raises(SystemExit) as invalid:
        parser.parse_args(['no-such-command'])
    assert invalid.value.code == 2
    with pytest.raises(SystemExit) as help_exit:
        mod.main(['--help'])
    assert help_exit.value.code == 0
    assert 'portfolio' in capsys.readouterr().out


@pytest.mark.parametrize('module,cls_name,expected', [
    ('news_engine', 'NewsEngine', (-100.0, 'THESIS_BREAKING')),
    ('buffett_news_engine', 'BuffettNewsEngine', (-100.0, 'THESIS_BREAKING')),
])
def test_news_strategy_contract(module, cls_name, expected, tmp_path, monkeypatch):
    monkeypatch.setenv('STOCK_ANALYSIS_STATE_ROOT', str(tmp_path))
    mod = importlib.import_module(module)
    engine = getattr(mod, cls_name)(['AAPL'])
    assert engine.score_article('bankruptcy fraud') == expected
    engine.add_to_watchlist('brk.b')
    assert engine.watchlist == ['AAPL', 'BRK.B']
    engine.seen_titles = {'AAPL': {'a title'}}
    engine.save_seen_state()
    assert getattr(mod, cls_name)().seen_titles == engine.seen_titles
    monkeypatch.setattr(mod.yf, 'Ticker', lambda symbol: SimpleNamespace(news=[]))
    assert engine.fetch_news('AAPL') == []


@pytest.mark.parametrize('module,cls_name,filename', [
    ('news_engine', 'NewsEngine', 'news_state.json'),
    ('buffett_news_engine', 'BuffettNewsEngine', 'buffett_news_state.json'),
])
def test_corrupt_news_state_fails_explicitly(module, cls_name, filename, tmp_path, monkeypatch):
    monkeypatch.setenv('STOCK_ANALYSIS_STATE_ROOT', str(tmp_path))
    (tmp_path / filename).write_text('{broken', encoding='utf-8')
    mod = importlib.import_module(module)
    with pytest.raises(ValueError, match='invalid JSON'):
        getattr(mod, cls_name)()


@pytest.mark.parametrize('module,cls_name', [
    ('portfolio', 'ScionPortfolioManager'), ('buffett_portfolio', 'BuffettPortfolioManager'),
])
def test_price_and_corruption_contract(module, cls_name, tmp_path, monkeypatch):
    mod = importlib.import_module(module)
    path = tmp_path / 'portfolio.json'
    cls = getattr(mod, cls_name)
    manager = cls(portfolio_file=str(path))
    monkeypatch.setattr(mod.yf, 'Ticker', lambda symbol: SimpleNamespace(history=lambda **kw: pd.DataFrame()))
    assert manager.get_current_price('AAPL') is None
    path.write_text('{broken', encoding='utf-8')
    with pytest.raises(ValueError):
        cls(portfolio_file=str(path))
