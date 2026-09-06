"""Same-directory durable file replacement and OS-backed process locks."""
from __future__ import annotations

import importlib
import json
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TextIO, cast


@contextmanager
def atomic_open(path: str | Path, mode: str = 'w', *, encoding: str = 'utf-8', newline: str | None = None) -> Iterator[TextIO]:
    """Publish only a complete flushed file. Does not serialize read/modify/write."""
    if mode != 'w':
        raise ValueError('atomic_open supports replacement text writes only')
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f'.{target.name}.', suffix='.tmp', dir=target.parent)
    try:
        with os.fdopen(fd, 'w', encoding=encoding, newline=newline) as stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_write_text(path: str | Path, text: str, *, encoding: str = 'utf-8') -> None:
    with atomic_open(path, encoding=encoding) as stream:
        stream.write(text)


def atomic_write_json(path: str | Path, value: Any) -> None:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n'
    atomic_write_text(path, encoded)


@contextmanager
def process_lock(path: str | Path, *, timeout: float = 30.0) -> Iterator[None]:
    """OS releases locks on process exit; sidecar remains to avoid inode races."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt

            if stream.tell() == 0:
                stream.write(b'\0')
                stream.flush()
            deadline = time.monotonic() + timeout
            while True:
                stream.seek(0)
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f'timed out acquiring {target}') from None
                    time.sleep(0.02)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl = cast(Any, importlib.import_module('fcntl'))

            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f'timed out acquiring {target}') from None
                    time.sleep(0.02)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)
