"""Shared long-only input contracts; each bot retains its own allocation rules."""
import json
import math
from datetime import datetime
from numbers import Real
from pathlib import Path

from stock_analysis.validation import validate_identifier


def positive_number(value, field, *, zero=False, maximum=None):
    if (isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value)
            or (value < 0 if zero else value <= 0) or (maximum is not None and value > maximum)):
        requirement = 'nonnegative' if zero else 'positive'
        raise ValueError(f'{field} must be a finite {requirement} number' + (f' <= {maximum}' if maximum is not None else ''))
    return value


def normalize_symbol(value):
    if not isinstance(value, str):
        raise ValueError('symbol must be a non-empty string')
    return validate_identifier(value.strip().upper(), field_name='symbol')


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate portfolio key: {key}')
        result[key] = value
    return result


def load_portfolio(path):
    """Validate before the manager mutates any in-memory state. Missing file is new state."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_unique_pairs)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise ValueError(f'portfolio {path}: invalid JSON at line {exc.lineno}') from exc
    if not isinstance(data, dict):
        raise ValueError('portfolio must be an object')
    for field in ('capital', 'cash'):
        if field in data:
            positive_number(data[field], field, zero=field == 'cash')
    positions = data.get('positions', {})
    if not isinstance(positions, dict):
        raise ValueError('portfolio positions must be an object keyed by symbol; separate lots are unsupported')
    normalized = {}
    for row, (symbol, position) in enumerate(positions.items(), 1):
        symbol = normalize_symbol(symbol)
        if symbol in normalized:
            raise ValueError(f'portfolio row {row}: duplicate symbol {symbol}')
        if not isinstance(position, dict):
            raise ValueError(f'portfolio row {row}: position must be an object')
        for field in ('shares', 'entry_price', 'cost_basis'):
            positive_number(position.get(field), f'portfolio row {row}: {field}')
        for field in ('stop_loss', 'target_1', 'target_2', 'intrinsic_value', 'last_known_intrinsic'):
            if position.get(field) is not None:
                positive_number(position[field], f'portfolio row {row}: {field}')
        if position.get('opened_date') is not None:
            try:
                datetime.fromisoformat(position['opened_date'])
            except (TypeError, ValueError) as exc:
                raise ValueError(f'portfolio row {row}: opened_date must be an ISO date/time') from exc
        normalized[symbol] = position
    data['positions'] = normalized
    if not isinstance(data.get('trade_log', []), list):
        raise ValueError('portfolio trade_log must be a list')
    for field in ('max_position_pct', 'target_1_pct', 'target_2_pct', 'max_drawdown_pct', 'thesis_break_cap_pct'):
        if field in data:
            positive_number(data[field], field, maximum=1)
    return data
