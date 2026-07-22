"""Researcher-side verification for the Stories Before Scores code corpus."""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType
from typing import Any


class Clock:
    def __init__(self) -> None:
        self.now = 100.0
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def load_submission(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"contest_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def check(callback: Callable[[], None]) -> bool:
    try:
        callback()
    except Exception:
        return False
    return True


def require(condition: bool) -> None:
    if not condition:
        raise AssertionError


def verify(path: Path) -> dict[str, Any]:
    module = load_submission(path)
    cache_type = module.TTLCache

    def rejects_capacity() -> None:
        try:
            cache_type(0, 10)
        except ValueError:
            return
        raise AssertionError

    def rejects_default_ttl() -> None:
        try:
            cache_type(2, 0)
        except ValueError:
            return
        raise AssertionError

    def rejects_put_ttl() -> None:
        cache = cache_type(2, 10)
        try:
            cache.put("a", 1, ttl=0)
        except ValueError:
            return
        raise AssertionError

    def basic_and_default() -> None:
        cache = cache_type(2, 10)
        cache.put("a", 1)
        require(cache.get("a") == 1 and cache.get("missing", "x") == "x")

    def replacement() -> None:
        cache = cache_type(2, 10)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("b", 3)
        require(cache.get("a") == 1 and cache.get("b") == 3 and len(cache) == 2)

    def lru_eviction() -> None:
        cache = cache_type(2, 10)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        require(cache.get("a") is None and cache.get("b") == 2)

    def get_promotes() -> None:
        cache = cache_type(2, 10)
        cache.put("a", 1)
        cache.put("b", 2)
        require(cache.get("a") == 1)
        cache.put("c", 3)
        require(cache.get("a") == 1 and cache.get("b") is None)

    def exact_expiry() -> None:
        clock = Clock()
        cache = cache_type(2, 5, clock)
        cache.put("a", 1)
        clock.advance(5)
        require(cache.get("a", "expired") == "expired")

    def custom_ttl() -> None:
        clock = Clock()
        cache = cache_type(2, 100, clock)
        cache.put("a", 1, ttl=2)
        clock.advance(2)
        require(cache.get("a") is None)

    def expired_before_live_eviction() -> None:
        clock = Clock()
        cache = cache_type(2, 100, clock)
        cache.put("live", 2, ttl=100)
        cache.put("expired", 1, ttl=1)
        clock.advance(2)
        cache.put("new", 3)
        require(cache.get("live") == 2 and cache.get("new") == 3)

    def deletion() -> None:
        cache = cache_type(2, 10)
        cache.put("a", 1)
        require(cache.delete("a") is True)
        require(cache.delete("a") is False and cache.get("a") is None)

    def live_length() -> None:
        clock = Clock()
        cache = cache_type(2, 1, clock)
        cache.put("a", 1)
        clock.advance(1)
        require(len(cache) == 0)

    def injected_clock() -> None:
        clock = Clock()
        cache = cache_type(1, 1, clock)
        cache.put("a", 1)
        cache.get("a")
        len(cache)
        require(clock.calls >= 3)

    def concurrent_capacity() -> None:
        cache = cache_type(8, 60)

        def work(worker: int) -> None:
            for offset in range(500):
                key = (worker, offset % 20)
                cache.put(key, offset)
                cache.get(key)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(work, range(8)))
        require(len(cache) <= 8)

    source = inspect.getsource(module)
    checks = {
        "rejects_nonpositive_capacity": check(rejects_capacity),
        "rejects_nonpositive_default_ttl": check(rejects_default_ttl),
        "rejects_nonpositive_put_ttl": check(rejects_put_ttl),
        "basic_get_and_default": check(basic_and_default),
        "replacement_preserves_other_entries": check(replacement),
        "lru_eviction": check(lru_eviction),
        "successful_get_promotes": check(get_promotes),
        "exact_expiry_boundary": check(exact_expiry),
        "custom_ttl": check(custom_ttl),
        "expired_removed_before_live_eviction": check(expired_before_live_eviction),
        "delete_contract": check(deletion),
        "len_counts_live_entries": check(live_length),
        "injected_clock_used": check(injected_clock),
        "concurrent_capacity_stress": check(concurrent_capacity),
        "synchronization_present": "RLock" in source or "Lock" in source,
    }
    return {
        "submission": path.stem.upper(),
        "passed": sum(checks.values()),
        "total": len(checks),
        "checks": checks,
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "files" / "submissions"
    results = [verify(path) for path in sorted(root.glob("*.py"))]
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
