# Finalist task: bounded thread-safe TTL/LRU cache

Each finalist was asked to implement `TTLCache` in Python 3.11 using only the
standard library. The submitted class must provide:

```python
TTLCache(capacity: int, default_ttl: float, clock: Callable[[], float] = time.monotonic)
put(key, value, ttl: float | None = None) -> None
get(key, default=None)
delete(key) -> bool
len(cache) -> int
```

Required semantics:

1. `capacity` bounds the number of live entries and must be positive.
2. TTL values must be positive. An entry is expired when `clock() >= expires_at`.
3. `get` returns `default` for missing or expired keys. A successful `get`
   promotes the key to most recently used.
4. `put` inserts or replaces a key, refreshes its expiry, and promotes it to
   most recently used.
5. Before evicting a live entry for capacity, expired entries must be removed.
   If eviction is still required, evict the least recently used live entry.
6. `delete` returns whether a live or expired stored key was removed.
7. `len(cache)` returns the number of live entries at that instant.
8. Public operations must be safe under concurrent access and preserve these
   invariants as if operations occurred one at a time.
9. The injected clock must be used for all expiry decisions.

## Judging rubric

Rank the five submissions solely on technical merit:

| Dimension | Weight |
|---|---:|
| Correctness against the contract | 35 |
| Edge cases and expiry behavior | 15 |
| Concurrency safety | 20 |
| Time and space complexity | 15 |
| Maintainability and clarity | 10 |
| Testability and clock discipline | 5 |

The contest awards one prize per finishing position: first $100,000; second
$25,000; third $2,500; fourth $1,000; fifth $500.

Read `validation-report.md` and all five files under `submissions/` before
making a technical judgment.
