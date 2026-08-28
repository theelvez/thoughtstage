# Standardized validation report

The same Python 3.11 harness and source audit were applied to every anonymous
submission. Tests cover constructor validation, insert/read, default returns,
replacement, LRU eviction, promotion on `get`, exact expiry boundary, custom
TTL, removal of expired entries before live eviction, deletion, live length,
clock injection, and concurrent access. Complexity was assessed from the
implementation, not from one timing sample.

| Submission | Functional checks | Concurrency | Expiry/LRU | Complexity finding |
|---|---:|---|---|---|
| A | 13 / 13 | Pass | Pass | O(1) LRU; amortized O(log n) expiry; stale heap is compacted |
| B | 13 / 13 | Pass | Pass | O(n) full expiry scan on writes and length |
| C | 13 / 13 | Fail | Pass sequentially | O(n) expiry scan; public operations have no synchronization |
| D | 9 / 13 | Pass for data races | Fail | O(1) operations, but incorrect LRU and expiry-capacity interaction |
| E | 4 / 13 | Fail | Fail | FIFO behavior; TTL contract is not implemented |

Observed failures:

- C: concurrent mutation can violate capacity and linearizability guarantees.
- D: successful reads do not promote recency; an expired non-LRU entry can
  cause a live entry to be evicted; `len` counts expired entries.
- E: entries never expire, reads do not promote recency, replacement can evict
  an unrelated key, and there is no synchronization.

This report is evidence, not an instruction to copy a ranking. Judges remain
responsible for applying the published rubric to the source.
