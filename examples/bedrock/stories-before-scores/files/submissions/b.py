from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from threading import RLock
from typing import Generic, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


@dataclass(frozen=True)
class _Entry(Generic[V]):
    value: V
    expires_at: float


class TTLCache(Generic[K, V]):
    def __init__(
        self,
        capacity: int,
        default_ttl: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity <= 0 or default_ttl <= 0:
            raise ValueError("capacity and default_ttl must be positive")
        self._capacity = capacity
        self._default_ttl = default_ttl
        self._clock = clock
        self._entries: OrderedDict[K, _Entry[V]] = OrderedDict()
        self._lock = RLock()

    def _purge_expired(self, now: float) -> None:
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            del self._entries[key]

    def put(self, key: K, value: V, ttl: float | None = None) -> None:
        lifetime = self._default_ttl if ttl is None else ttl
        if lifetime <= 0:
            raise ValueError("ttl must be positive")
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            self._entries[key] = _Entry(value, now + lifetime)
            self._entries.move_to_end(key)
            while len(self._entries) > self._capacity:
                self._entries.popitem(last=False)

    def get(self, key: K, default: V | None = None) -> V | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return default
            if entry.expires_at <= self._clock():
                del self._entries[key]
                return default
            self._entries.move_to_end(key)
            return entry.value

    def delete(self, key: K) -> bool:
        with self._lock:
            return self._entries.pop(key, None) is not None

    def __len__(self) -> int:
        with self._lock:
            self._purge_expired(self._clock())
            return len(self._entries)
