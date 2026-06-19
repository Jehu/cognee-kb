# Plan 007: Preserve the query answer when source-extraction (CHUNKS) fails

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- kb/cognee_io.py tests/test_cognee_io.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `5c096b7`, 2026-06-19
- **Issue**: #7 — https://github.com/Jehu/cognee-kb/issues/7

## Why this matters

`query_with_sources` runs two independent cognee searches: `GRAPH_COMPLETION`
for the answer, then `CHUNKS` purely to extract source ids. If the CHUNKS call
raises (timeout, transient cognee error, a different query-plan failure), the
exception propagates uncaught through `instance_service /query` → FastAPI 500
→ Gateway 502. The user sees a total failure even though the answer was
successfully computed — the answer text is thrown away. Source chips are a
nice-to-have; the answer is the point.

## Current state

`kb/cognee_io.py:124-148`:

```python
124: async def query_with_sources(instance, question, datasets) -> tuple[str, list[str]]:
132:    assert_instance_env(instance)
133:    import cognee
134:    from cognee import SearchType
136:    results = await cognee.search(query_type=SearchType.GRAPH_COMPLETION, ...)
141:    answer = "\n".join(_render(r) for r in results)
143:    chunk_results = await cognee.search(query_type=SearchType.CHUNKS, ...)
148:    return answer, _extract_source_ids(chunk_results)[:_MAX_RELATED_SOURCES]
```

`kb/instance_service.py:71-73` awaits `query_with_sources` with no try/except
→ a CHUNKS failure bubbles to a 500. The MCP proxy path would surface a
readable string, but the gateway path raises `HTTPException(502)`.

## Repo conventions to match

- German comments explaining the why. The module docstring at `cognee_io.py:1`
  documents cognee shape variance — match that voice.
- `print(..., file=sys.stderr)` is the current logging idiom (see
  `worker.py:64`); use it for the warning so it shows in the instance-service
  stderr like worker failures do.

## Commands you will need

| Purpose    | Command                                    | Expected on success |
|------------|--------------------------------------------|---------------------|
| Tests      | `uv run pytest tests/test_cognee_io.py`    | all pass            |
| Full suite | `uv run pytest` (or `make test`)           | all pass            |

## Scope

**In scope**:
- `kb/cognee_io.py` (wrap the CHUNKS search in try/except)
- `tests/test_cognee_io.py` (add a test: CHUNKS fails → answer still returned)

**Out of scope**:
- `instance_service.py`, `gateway.py` (no change — they already handle a
  returned `(answer, [])` fine).
- The GRAPH_COMPLETION call (it must still propagate — a failed answer IS a
  failure).

## Git workflow

- Branch: `advisor/007-query-answer-preservation`
- Commit style: `Return answer with empty sources when CHUNKS search fails`

## Steps

### Step 1: Wrap the CHUNKS search

In `kb/cognee_io.py`, replace lines 143-148 with:

```python
    try:
        chunk_results = await cognee.search(
            query_type=SearchType.CHUNKS,
            query_text=question,
            datasets=datasets,
        )
        source_ids = _extract_source_ids(chunk_results)[:_MAX_RELATED_SOURCES]
    except Exception as e:  # noqa: BLE001 — Quellen sind Komfort, Antwort ist Pflicht
        # CHUNKS ist nur die Herkunfts-Extraktion. Schlägt sie fehl, liefern
        # wir die Antwort ohne Quellen-Chips statt die ganze Query sterben zu
        # lassen (sonst 502 trotz fertiger Antwort).
        print(f"[cognee_io] CHUNKS-Suche fehlgeschlagen: {type(e).__name__}: {e}",
              file=sys.stderr)
        source_ids = []
    return answer, source_ids
```

Add `import sys` at the top if not present (it is not currently imported in
`cognee_io.py` — confirm and add).

**Verify**: `uv run pytest tests/test_cognee_io.py` → existing tests pass.

### Step 2: Add a regression test

In `tests/test_cognee_io.py`, add a test where `cognee.search` is monkeypatched
so the first call (`GRAPH_COMPLETION`) returns a normal answer and the second
call (`CHUNKS`) raises `RuntimeError`. Assert `query_with_sources` returns
`(answer, [])` and does NOT raise. Follow the existing monkeypatch pattern in
that file for how `cognee` / `SearchType` are stubbed (look at how current
tests patch `import cognee` inside the function).

**Verify**: `uv run pytest tests/test_cognee_io.py -k chunks_fail` → passes.

### Step 3: Full suite

**Verify**: `uv run pytest` (or `make test`) → all pass.

## Test plan

- New test: GRAPH_COMPLETION succeeds, CHUNKS raises → returns `(answer, [])`.
- Pattern: existing `tests/test_cognee_io.py` tests (cognee/SearchType stubbing).
- Verification: `uv run pytest tests/test_cognee_io.py` → all pass.

## Done criteria

- [ ] `uv run pytest` exits 0
- [ ] The CHUNKS search is wrapped so its failure returns `(answer, [])`
- [ ] New regression test exists and passes
- [ ] The GRAPH_COMPLETION path still propagates exceptions (not wrapped)
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- `instance_service.py /query` is changed to catch cognee errors itself at
  HEAD — then this plan may be redundant; STOP and check.
- The second `cognee.search` call at HEAD is not the CHUNKS source-extraction
  call (the line numbers shifted) — STOP, re-confirm before editing.

## Maintenance notes

- When structured logging lands (plan 018), swap the `print(..., stderr)` for
  a real log call.
- Reviewers: confirm the test asserts BOTH that the answer is preserved AND
  that no exception escapes.
