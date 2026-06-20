# Plan 025: Serialize cognee access with an asyncio.Lock (follow-up to spike 020)

> **Status**: TODO (spike conclusion: UNSAFE — see `plans/README.md` Spike notes
> and the comment in `kb/cognee_io.py`). This is the build plan the spike
> recommended. **Not yet executed.**
>
> **Priority**: P2 (it's a latent correctness risk on the core query path)
> **Effort**: S  **Risk**: MED  **Depends on**: —
> **Category**: bug (concurrency)  **Planned at**: commit `c70f9f4`, 2026-06-20

## Why this matters

The 020 spike found that within the Instance Service, the worker's `cognify`
(graph write) and a `/query` handler's `search` (graph read) run concurrently
in two threads on cognee's **single shared Kuzu Connection**
(`shared_kuzu_lock=False` default → `run_in_executor` on a multi-thread pool).
Kuzu Connections aren't safe for concurrent use → races, inconsistent reads, or
lock errors whenever a query arrives during an ingest. Fix: an `asyncio.Lock`
in `cognee_io` so the two paths can't submit concurrent `connection.execute`
jobs.

## Current state

- `kb/cognee_io.py`: `ingest()` and `query_with_sources()` call `cognee.add/cognify/search`
  with no mutual exclusion.
- `instance_service.py`: worker background task + `/query` handler share the
  loop (so they interleave at `await`).

## Steps (sketch — flesh out before execution)

1. Add a module-level `_COGNEE_LOCK = asyncio.Lock()` in `kb/cognee_io.py`.
2. Wrap the cognee calls in `ingest` (`cognee.add` + `cognee.cognify`) and in
   `query_with_sources` (`cognee.search` ×2) in `async with _COGNEE_LOCK:`.
3. Test: two concurrent `query_with_sources` (or ingest+query) calls are
   serialized — assert via mocked cognee that the second doesn't start until
   the first releases (e.g. a gate event). Measure query latency under
   simulated cognify (note the cost in `plans/README.md`).
4. Done: full suite green; the lock is held across cognee calls and released
   on exception (use `async with`).

## STOP / open questions

- If the lock measurably degrades query latency during long cognify, consider
  finer granularity (separate locks?) — but a single lock is correct; only
  revisit on evidence.
- Confirm `cognee.add` + `cognee.cognify` are both loop-bound (they are) so one
  lock spanning both is sufficient.

## Maintenance notes

- This lock is the in-process equivalent of kb's "one writer per wall"
  invariant, extended to cognify-vs-search WITHIN the process.
- If cognee ever switches to per-call connections (thread-safe), the lock can
  go — re-evaluate on a cognee upgrade.
