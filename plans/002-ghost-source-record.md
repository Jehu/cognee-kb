# Plan 002: Fix ghost source record on ingest failure (silent data loss)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- kb/worker.py kb/sources.py tests/test_worker.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plans/001-verification-baseline.md (so `make test` runs the new test)
- **Category**: bug
- **Planned at**: commit `5c096b7`, 2026-06-19

## Why this matters

When `cognee_io.ingest` fails (LLM down, timeout, Kuzu error), the worker has
ALREADY written the raw `.md` file and inserted a `SourceRecord` into SQLite.
The `except` block marks the job `failed` but cleans up nothing. The dedup
check (`find_by_hash`) matches purely on `content_hash + vault` with **no
status filter**, so re-submitting the identical content finds the ghost record
and silently `mark_done`s the job — cognee never receives the body. The
content is permanently invisible to all queries, and the user cannot recover
by re-submitting. This is silent data loss on the core ingest workflow.

## Current state

`kb/worker.py` — `process_one_async` (the relevant span):

```python
41:        content_hash = hashlib.sha256(doc.body.encode("utf-8")).hexdigest()
42:        if store.find_by_hash(content_hash, vault.name) is not None:
43:            print(f"[worker] job {job.id}: Duplikat ... übersprungen", file=sys.stderr)
44:            q.mark_done(job.id)
45:            return True
47:        record = SourceRecord.new(..., raw_md_path="", title=doc.title, content_hash=content_hash)
51:        path, record = rawstore.write_raw(vault.raw_dir, doc.title, doc.body, record)
52:        store.insert(record)
...
57:        await cognee_io.ingest(instance, path, vault.dataset, node_sets=[...])
60:        q.mark_done(job.id)
61:    except Exception as e:  # noqa: BLE001 — Worker darf nie sterben
64:        print(f"[worker] job {job.id} failed: ...", file=sys.stderr)
66:        q.mark_failed(job.id, f"{type(e).__name__}: {e}")
```

`kb/sources.py:101-106` — dedup has no status/success filter:

```python
101:    def find_by_hash(self, content_hash: str, vault: str) -> SourceRecord | None:
102:        """Erste Quelle mit gleichem Body-Hash im selben Vault — für Ingest-Dedup."""
103:        row = self.conn.execute(
104:            f"SELECT {self._COLS} FROM sources WHERE content_hash=? AND vault=? LIMIT 1",
105:            (content_hash, vault)).fetchone()
106:        return SourceRecord(*row) if row else None
```

`SourceStore` has no `delete` method (grep `delete|DELETE|remove|unlink` in
`kb/` returns nothing). `rawstore.write_raw` returns the `path` of the written
file. The happy path and the dedup logic must stay intact; only the
post-failure cleanup is added.

## Repo conventions to match

- German docstrings/comments explaining the *why* (see `worker.py:38-40`,
  `sources.py:10-13` for style). Keep this style.
- Tests use `pytest` with `monkeypatch`/`AsyncMock`; async tests run via
  `asyncio.run` (no `asyncio_mode=auto`). Model new tests on
  `tests/test_worker.py` (the existing `process_one_async` tests patch
  `kb.cognee_io.ingest` and `kb.fetch_web.fetch`).

## Commands you will need

| Purpose    | Command                          | Expected on success |
|------------|----------------------------------|---------------------|
| Tests      | `uv run pytest tests/test_worker.py` | all pass         |
| Full suite | `uv run pytest` (or `make test`) | all pass            |

## Scope

**In scope**:
- `kb/worker.py` (add cleanup in the `except` block)
- `kb/sources.py` (add a `delete(source_id)` method)
- `tests/test_worker.py` (add a characterization + regression test)

**Out of scope**:
- `kb/rawstore.py` (no change needed; the file path is already known via `path`)
- Any change to the happy path, dedup logic, or job status enum.
- Reordering insert-after-ingest (cognee reads the file by path, so the file
  must exist pre-ingest — keep current ordering, just clean up on failure).

## Git workflow

- Branch: `advisor/002-ghost-source-record`
- Commit style: `Clean up source record + raw file when ingest fails` (English
  imperative, matching `git log`).

## Steps

### Step 1: Add `SourceStore.delete`

In `kb/sources.py`, add after `find_by_hash`:

```python
    def delete(self, source_id: str) -> None:
        """Löscht einen Source-Record (Cleanup bei fehlgeschlagenem Ingest)."""
        self.conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
        self.conn.commit()
```

**Verify**: `uv run pytest` → still green (additive only).

### Step 2: Write the characterization test FIRST (it must fail on current code)

In `tests/test_worker.py`, add a test that enqueues a snippet job, makes
`cognee_io.ingest` raise, runs `process_one_async`, then asserts a second
identical job is NOT dedup-skipped. Model the harness on the existing
`process_one_async` tests (look at how they build a `JobQueue`/`SourceStore`
in `tmp_path` and monkeypatch `kb.cognee_io.ingest`). Key assertions:

1. After the failing job: `q.info(job.id)["status"] == "failed"`.
2. After the failing job: `store.find_by_hash(h, vault)` returns `None` (ghost
   record cleaned up).
3. A second identical enqueue re-attempts ingest (mock `cognee_io.ingest` to
   succeed the second time; assert it was awaited and the job ends `done`).

Use a snippet job (`{"text": "x", "title": "t"}`) so no network fetch is
needed. Patch `kb.cognee_io.ingest` with `AsyncMock` whose `side_effect` first
raises `RuntimeError("ollama down")` then returns `None`.

**Verify**: `uv run pytest tests/test_worker.py -k ghost` → the new test
FAILS (assertion 2 or 3) against current code. This is the characterization
gate; capture the failure output.

### Step 3: Add cleanup in the `except` block

In `kb/worker.py`, track the record id + path in locals set before the try, and
clean them up on failure. Concretely, before the `try:` set `record_id = None`
and `raw_path = None`; assign `record_id = record.id` after `store.insert`
(line 52) and `raw_path = path` (line 51). Then in the `except Exception`
block, before `q.mark_failed`, add:

```python
            # Cleanup: Source-Record und Rohdatei wurden VOR cognee angelegt.
            # Ohne Cleanup würde der Dedup-Check (find_by_hash, kein Status-
            # Filter) diesen Inhalt beim nächsten Versuch überspringen —
            # stummer Datenverlust. Nur aufräumen, was wirklich angelegt wurde.
            if record_id is not None:
                store.delete(record_id)
            if raw_path is not None:
                try:
                    raw_path.unlink()
                except OSError:
                    pass
```

Keep the `except Exception as e: # noqa: BLE001` comment/rationale intact.

**Verify**: `uv run pytest tests/test_worker.py -k ghost` → now PASSES.

### Step 4: Run the full suite

**Verify**: `uv run pytest` (or `make test`) → all pass, including the new
test and all existing dedup/happy-path tests unchanged.

## Test plan

- New test `test_process_one_cleans_up_on_ingest_failure_then_reingests` in
  `tests/test_worker.py`, covering: failed-job status, ghost-record cleanup,
  and successful re-ingest of identical content.
- Pattern to follow: the existing `process_one_async` tests in the same file
  (how they construct `JobQueue`/`SourceStore` in `tmp_path`, monkeypatch
  `kb.cognee_io.ingest`).
- Verification: `uv run pytest tests/test_worker.py` → all pass.

## Done criteria

- [ ] `uv run pytest` exits 0
- [ ] New test `test_process_one_cleans_up_on_ingest_failure_then_reingests`
      exists and passes
- [ ] `grep -n "def delete" kb/sources.py` returns a match
- [ ] The worker `except` block calls `store.delete(...)` and unlinks the raw
      file (guarded by `if ... is not None`)
- [ ] Existing dedup + happy-path tests still pass unchanged
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- The characterization test in Step 2 PASSES on current (unmodified) code —
  that means the bug is not reproducible as described; STOP and report.
- `find_by_hash` is found to filter by status somewhere (it does not at
  `5c096b7`) — STOP, the premise has changed.
- A successful cleanup requires touching `rawstore.py` or the dedup query
  itself (out of scope) — report rather than expanding scope.

## Maintenance notes

- If a future change moves `store.insert` to AFTER successful cognee ingest,
  this cleanup becomes unnecessary — revisit then (but cognee reads the file
  by path, so the file still must pre-exist; the raw-file cleanup stays
  relevant).
- Reviewers: confirm the second-enqueue assertion genuinely re-invokes
  `cognee_io.ingest` (not a cached/deduped skip).
