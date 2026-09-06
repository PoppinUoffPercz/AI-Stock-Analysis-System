import importlib
import json

import pytest


@pytest.fixture(params=['portfolio', 'buffett_portfolio'])
def manager(request, tmp_path):
    module = importlib.import_module(request.param)
    cls = getattr(module, 'ScionPortfolioManager' if request.param == 'portfolio' else 'BuffettPortfolioManager')
    return cls(portfolio_file=str(tmp_path / 'portfolio.json'))


def open_position(manager, symbol='AAPL', price=100):
    if hasattr(manager, 'target_1_pct'):
        return manager.open_position(symbol, price, 90, 120, 140)
    return manager.open_position(symbol, price)


@pytest.mark.parametrize('price', [0, -1, float('nan'), float('inf'), True, '100'])
def test_bad_price_fails_before_state_change(manager, price):
    with pytest.raises(ValueError, match='entry_price'):
        open_position(manager, price=price)
    assert manager.positions == {}
    assert manager.cash == manager.capital


def test_normalized_duplicate_is_rejected(manager):
    assert open_position(manager, 'brk.b')['action'] == 'BOUGHT'
    assert open_position(manager, ' BRK.B ')['action'] == 'REJECTED'
    assert list(manager.positions) == ['BRK.B']


@pytest.mark.parametrize('shares', [0, -1, float('nan'), float('inf'), 'five'])
def test_invalid_loaded_quantity_is_rejected(manager, shares):
    from pathlib import Path
    path = Path(manager.portfolio_file)
    path.write_text(json.dumps({'positions': {'AAPL': {'shares': shares, 'entry_price': 100, 'cost_basis': 100}}}))
    with pytest.raises(ValueError, match='shares'):
        type(manager)(portfolio_file=str(path))


def test_duplicate_json_keys_and_invalid_dates(manager):
    from pathlib import Path
    path = Path(manager.portfolio_file)
    path.write_text('{"positions": {}, "positions": {}}')
    with pytest.raises(ValueError, match='duplicate'):
        type(manager)(portfolio_file=str(path))
    path.write_text(json.dumps({'positions': {'AAPL': {'shares': 1, 'entry_price': 100, 'cost_basis': 100, 'opened_date': 'bad'}}}))
    with pytest.raises(ValueError, match='opened_date'):
        type(manager)(portfolio_file=str(path))
