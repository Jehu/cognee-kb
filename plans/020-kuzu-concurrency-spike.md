# Plan 020: [investigation] Spike — is cognee's Kuzu access safe under concurrent cognify + search in one loop?

> **Executor instructions**: This is an **investigation/spike** plan, not a
> build plan. The goal is to produce a short written finding (add it to
> `plans/README.md` under a "Spike notes" section, or as a comment in
> `cognee_io.py`) and decide whether a guard is needed. Do NOT add a lock
> blindly. If you cannot reach a confident conclusion, report what's missing.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- kb/instance_service.py kb/cognee_io.py kb/worker.py`
> If any in-scope file changed since this plan was written, compare excerpts to live code; on mismatch, note it in the finding.

## Status

- **Priority**: P3 (investigation)
- **Effort**: M
- **Risk**: MED (only if a lock is later added without measuring latency)
- **Depends on**: none
- **Category**: investigation (correctness/concurrency)
- **Planned at**: commit `5c096b7`, 2026-06-19
- **Issue**: #20 — https://github.com/Jehu/cognee-kb/issues/20

## Why this matters

The "Kuzu is strictly single-writer" rule (CLAUDE.md) is enforced *between
processes* — that's why the custom thin MCP exists instead of the official
`cognee-mcp`. But WITHIN the Instance Service, the worker background task runs
`cognee.cognify()` (a long Kuzu write) in the SAME event loop as `/query`
handlers that `await cognee.search()` (Kuzu reads), with NO mutex, semaphore,
or cognee-level lock between them. Whether this is safe is an **unverified
assumption** depending entirely on cognee's internal connection/transaction
model — which is not visible from this codebase.

If cognee caches a single Kuzu connection per loop, operations effectively
serialize and the only cost is query latency during ingestion (safe). If
cognee opens separate read/write connections or holds a transaction across an
await, concurrent read-during-write could trigger Kuzu lock errors or read
inconsistent graph state.

## Current state

- `kb/instance_service.py:46` launches `worker.run_forever_async` as a
  background task in the FastAPI loop.
- `kb/worker.py:57` → `cognee_io.ingest` → `cognee.cognify()` (write).
- `kb/instance_service.py:72` `/query` → `cognee_io.query_with_sources` →
  `cognee.search()` twice (`cognee_io.py:136,143`) (read).
- No `asyncio.Lock`/`Semaphore` around any cognee call. Only one loop, one
  process, one cognee instance per wall.

## Scope (investigation only — NO production lock change)

1. Read the installed cognee source for the Kuzu connection lifecycle:
   `uv run python -c "import cognee, os; print(os.path.dirname(cognee.__file__))"`
   then inspect how `cognify` and `search` acquire/release the Kuzu engine —
   is there a single shared engine per process? A lock? A transaction scope
   that spans an `await`?
2. Search cognee's repo/issues for "lock", "single writer", "concurrent
   read", "KuzuEngine" to see if concurrency is addressed upstream.
3. Empirically reproduce under load: start the instance service, kick off a
   large cognify (ingest a long doc), and fire concurrent `/query` requests;
   capture any Kuzu/lock errors or inconsistent results in the worker + query
   logs.
4. Reach ONE of these conclusions:
   - **SAFE**: cognee serializes via a single connection → document the
     assumption in a `cognee_io.py` comment, close this finding (no code).
   - **UNSAFE**: conflicts observed → write a follow-up build plan proposing
     an `asyncio.Lock` in `cognee_io` around `ingest` + `query_with_sources`,
     noting the query-latency cost during ingestion.
   - **INCONCLUSIVE**: list exactly what's unknown and what experiment would
     resolve it.

## Commands you will need

| Purpose | Command | Expected |
|--------|---------|----------|
| Find cognee path | `uv run python -c "import cognee, os; print(os.path.dirname(cognee.__file__))"` | a path |
| Tests (regression guard) | `uv run pytest` | all pass |

## Done criteria

- [ ] A written conclusion (SAFE / UNSAFE / INCONCLUSIVE) is recorded in
      `plans/README.md` Spike notes, with the evidence (cognee version, source
      references, load-test observations)
- [ ] If UNSAFE: a follow-up plan stub exists (or a note that one is needed),
      scoped as "add asyncio.Lock in cognee_io + latency measurement"
- [ ] No production code changed in this plan (a guard is a separate decision)
- [ ] `plans/README.md` status row updated

## STOP conditions

- The load test corrupts data — STOP immediately, restore from `raw/` (the
  exit-ramp), and record UNSAFE with the repro.
- cognee's Kuzu internals are opaque and undocumented — report INCONCLUSIVE
  rather than guessing.

## Maintenance notes

- The conclusion feeds any future decision to add concurrency control; do not
  let it sit unrecorded.
- Reviewers: this plan's output is a decision record, not code — judge it on
  evidence quality.
