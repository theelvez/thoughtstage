from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from threading import RLock


class TTLCache:
    def __init__(
        self,
        capacity: int,
        default_ttl: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity <= 0 or default_ttl <= 0:
            raise ValueError("arguments must be positive")
        self._capacity = capacity
        self._default_ttl = default_ttl
        self._clock = clock
        self._entries: OrderedDict[object, tuple[object, float]] = OrderedDict()
        self._lock = RLock()

    def put(self, key: object, value: object, ttl: float | None = None) -> None:
        lifetime = self._default_ttl if ttl is None else ttl
        if lifetime <= 0:
            raise ValueError("ttl must be positive")
        with self._lock:
            if key not in self._entries and len(self._entries) >= self._capacity:
                self._entries.popitem(last=False)
            self._entries[key] = (value, self._clock() + lifetime)
            self._entries.move_to_end(key)

    def get(self, key: object, default: object = None) -> object:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return default
            value, expires_at = entry
            if self._clock() >= expires_at:
                del self._entries[key]
                return default
            return value

    def delete(self, key: object) -> bool:
        with self._lock:
            return self._entries.pop(key, None) is not None

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
