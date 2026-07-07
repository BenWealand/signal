from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

_lock = threading.Lock()
_entries: dict[str, tuple[float, Any]] = {}


def get_or_set(key: str, ttl_seconds: float, factory: Callable[[], T]) -> T:
    now = time.time()
    with _lock:
        entry = _entries.get(key)
        if entry and entry[0] > now:
            return entry[1]

    value = factory()
    with _lock:
        _entries[key] = (now + ttl_seconds, value)
    return value


def invalidate(prefix: str = "") -> None:
    with _lock:
        if not prefix:
            _entries.clear()
            return
        for key in list(_entries):
            if key.startswith(prefix):
                del _entries[key]
