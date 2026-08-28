from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass
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
            raise ValueError("arguments must be positive")
        self._capacity = capacity
        self._default_ttl = default_ttl
        self._clock = clock
        self._entries: OrderedDict[K, _Entry[V]] = OrderedDict()

    def _purge(self, now: float) -> None:
        for key in [k for k, entry in self._entries.items() if entry.expires_at <= now]:
            del self._entries[key]

    def put(self, key: K, value: V, ttl: float | None = None) -> None:
        lifetime = self._default_ttl if ttl is None else ttl
        if lifetime <= 0:
            raise ValueError("ttl must be positive")
        now = self._clock()
        self._purge(now)
        self._entries[key] = _Entry(value, now + lifetime)
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)

    def get(self, key: K, default: V | None = None) -> V | None:
        entry = self._entries.get(key)
        if entry is None:
            return default
        if entry.expires_at <= self._clock():
            del self._entries[key]
            return default
        self._entries.move_to_end(key)
        return entry.value

    def delete(self, key: K) -> bool:
        return self._entries.pop(key, None) is not None

    def __len__(self) -> int:
        self._purge(self._clock())
        return len(self._entries)
