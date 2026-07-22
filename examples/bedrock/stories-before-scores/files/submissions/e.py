from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable


class TTLCache:
    def __init__(
        self,
        capacity: int,
        default_ttl: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self.default_ttl = default_ttl
        self.clock = clock
        self.data: OrderedDict[object, object] = OrderedDict()

    def put(self, key: object, value: object, ttl: float | None = None) -> None:
        if len(self.data) >= self.capacity:
            self.data.popitem(last=False)
        self.data[key] = value

    def get(self, key: object, default: object = None) -> object:
        return self.data.get(key, default)

    def delete(self, key: object) -> bool:
        if key not in self.data:
            return False
        del self.data[key]
        return True

    def __len__(self) -> int:
        return len(self.data)
