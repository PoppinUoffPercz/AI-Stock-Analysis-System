import json

import pytest

from stock_analysis.persistence import atomic_open, atomic_write_json, atomic_write_text


def test_atomic_failure_preserves_old_file_and_removes_temporary(tmp_path):
    path = tmp_path / 'state.json'
    atomic_write_json(path, {'old': 1})
    with pytest.raises(OSError), atomic_open(path) as stream:
        stream.write('{partial')
        assert json.loads(path.read_text()) == {'old': 1}
        raise OSError('interrupted write')
    assert json.loads(path.read_text()) == {'old': 1}
    assert sorted(p.name for p in tmp_path.iterdir()) == ['state.json']


def test_serialization_failure_does_not_replace_file(tmp_path):
    path = tmp_path / 'state.json'
    atomic_write_json(path, {'old': 1})
    with pytest.raises(ValueError):
        atomic_write_json(path, {'bad': float('nan')})
    assert json.loads(path.read_text()) == {'old': 1}


def test_replace_failure_and_success(tmp_path, monkeypatch):
    from stock_analysis import persistence

    path = tmp_path / 'state.txt'
    atomic_write_text(path, 'old')
    with monkeypatch.context() as patch:
        def fail(*args):
            raise PermissionError('locked')
        patch.setattr(persistence.os, 'replace', fail)
        with pytest.raises(PermissionError):
            atomic_write_text(path, 'new')
    assert path.read_text() == 'old'
    atomic_write_text(path, 'new')
    assert path.read_text() == 'new'
