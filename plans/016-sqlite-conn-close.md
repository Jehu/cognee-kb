# Plan 016: Close SQLite connections on Instance Service shutdown

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- kb/instance_service.py kb/queue.py kb/sources.py tests/test_instance_service.py`
> If any in-scope file changed since this plan was written, compare excerpts to live code; on mismatch, STOP.

## Status

- **Priority**: P3 | **Effort**: S | **Risk**: LOW | **Depends on**: none
- **Category**: bug | **Planned at**: commit `5c096b7`, 2026-06-19
- **Issue**: #16 — https://github.com/Jehu/cognee-kb/issues/16

## Why this matters

The Instance Service opens `JobQueue` and `SourceStore` connections (stored in
`app.state`) at startup. The lifespan `finally` block cancels the worker task
but never closes either SQLite connection; neither class has a `close()`.
Connections rely on GC. In WAL mode the practical impact is low (SQLite
recovers on next open), but an unclean shutdown under heavy write load can
leave the WAL uncheckpointed — a correctness-adjacent hygiene gap.

## Current state

`kb/instance_service.py:42-63`:
```python
42:        q = JobQueue(inst.var_dir / "queue.db")
43:        store = SourceStore(inst.var_dir / "sources.db")
...
55:        finally:
56:            app.state.shutting_down = True
57:            task.cancel()
58:            try:
59:                await task
60:            except asyncio.CancelledError:
61:                pass
62:            except Exception:  # noqa: BLE001
63:                pass
```

`grep "def close" kb/queue.py kb/sources.py` → no matches (neither class has one).

## Scope

**In scope**: `kb/queue.py`, `kb/sources.py` (add `close()`), `kb/instance_service.py`
(call them in `finally`), `tests/test_instance_service.py` (assert close called).
**Out of scope**: the gateway/MCP (they build per-request connections; out of
scope per the SQLite-thread-bound tradeoff).

## Steps

1. Add `def close(self) -> None: self.conn.close()` to `JobQueue` and `SourceStore`.
2. In the lifespan `finally`, after awaiting the cancelled task, call
   `app.state.q.close()` and `app.state.store.close()` (guard with
   `hasattr`/try in case startup failed before assignment).
3. Add a test using FastAPI's lifespan test pattern that starts + shuts down the
   app and asserts the connections are closed (e.g. monkeypatch `close` to set
   a flag, or assert a subsequent `conn.execute` raises `sqlite3.ProgrammingError`).

## Commands you will need

| Purpose | Command | Expected |
|--------|---------|----------|
| Tests  | `uv run pytest tests/test_instance_service.py` | all pass |
| Full   | `uv run pytest` (or `make test`) | all pass |

## Done criteria

- [ ] `uv run pytest` exits 0; new shutdown test passes
- [ ] Both classes have `close()`; the lifespan `finally` calls them
- [ ] Only in-scope files modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- Closing the connection in `finally` races with an in-flight worker write —
  ensure the worker task is fully awaited BEFORE closing (it is, at line 59);
  if not, STOP.
- A per-request `JobQueue`/`SourceStore` elsewhere relies on GC timing — none
  do today; if found, STOP and report.

## Maintenance notes

- Reviewers: confirm the close happens strictly after `await task` completes.
