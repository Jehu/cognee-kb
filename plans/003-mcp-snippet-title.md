# Plan 003: Fix MCP snippet-title divergence (use `build_payload`)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- kb/mcp_server.py kb/classify.py tests/test_mcp_server.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `5c096b7`, 2026-06-19
- **Issue**: #3 — https://github.com/Jehu/cognee-kb/issues/3

## Why this matters

Snippets ingested through an MCP agent (the documented Phase-3 agent path,
README §Phase 3) get a crude `content[:50]` title — mid-word-truncated, possibly
multiline — while the identical content ingested via the Gateway or CLI gets a
proper word-boundary, heading-aware title (`snippet_title`). The bad title
flows into the raw `.md` filename slug and the `# {title}` H1, and into the
source-chip metadata shown in the PWA. Three ingest entry points, one is
wrong. The root cause is hand-rolled payload logic in `mcp_server.py` that
duplicated (and regressed) what `build_payload` already centralizes.

(Note: plan 008 consolidates the broader copy-paste across gateway/mcp/cli;
this plan is the targeted one-line fix. Doing this first is lower risk than
waiting for the consolidation.)

## Current state

`kb/mcp_server.py:95-106` — the `ingest` tool hand-builds the payload:

```python
95:        payload: dict = {"node_set": node_set} if node_set else {}
96:        # Kein Datei-Pfad-Zweig (wie Gateway) — youtube/web/snippet.
97:        c = classify(content)
98:        if c.kind == "youtube":
99:            payload |= {"url": content.strip(), "video_id": c.video_id}
100:        elif c.kind == "web":
101:            payload |= {"url": content.strip()}
102:        else:
103:            payload |= {"text": content, "title": content[:50]}
104:        q = JobQueue(queue_path(instance_name))
105:        jid = q.enqueue(vault, c.kind, payload)
```

`kb/classify.py:55-66` — `build_payload` is the shared helper Gateway + CLI use:

```python
55: def build_payload(content: str) -> tuple[str, dict]:
61:    c = classify(content)
62:    if c.kind == "youtube":
63:        return c.kind, {"url": content.strip(), "video_id": c.video_id}
64:    if c.kind == "web":
65:        return c.kind, {"url": content.strip()}
66:    return c.kind, {"text": content, "title": snippet_title(content)}
```

`kb/classify.py:38-40` docstring explicitly flags `content[:50]` as the broken
old behavior. `classify` and `build_payload` are both already importable from
`kb.classify` (mcp_server imports `classify` today at line 17).

## Repo conventions to match

- German comments explaining the why; match the existing style at
  `mcp_server.py:96` and `classify.py:34-41`.

## Commands you will need

| Purpose    | Command                                  | Expected on success |
|------------|------------------------------------------|---------------------|
| Tests      | `uv run pytest tests/test_mcp_server.py` | all pass            |
| Full suite | `uv run pytest` (or `make test`)         | all pass            |

## Scope

**In scope**:
- `kb/mcp_server.py` (replace the hand-rolled payload with `build_payload`)
- `tests/test_mcp_server.py` (add a snippet-title assertion)

**Out of scope**:
- Do NOT consolidate `queue_path` or the proxy block here (that is plan 008).
- Do NOT change `classify.py` or `build_payload`.

## Git workflow

- Branch: `advisor/003-mcp-snippet-title`
- Commit style: `Use build_payload for MCP ingest so snippet titles match gateway`

## Steps

### Step 1: Replace the payload block

In `kb/mcp_server.py`:
- Change the import: `from kb.classify import classify` →
  `from kb.classify import build_payload`.
- Replace lines 95-103 with:

```python
        kind, payload = build_payload(content)
        if node_set:
            payload["node_set"] = node_set
```

- Update line 105 `jid = q.enqueue(vault, c.kind, payload)` → use `kind`
  (from `build_payload`) instead of `c.kind`.
- Keep line 106's `return f"queued job {jid} ({kind}) -> {vault}"` using `kind`.

**Verify**: `uv run pytest tests/test_mcp_server.py` → existing tests still
pass (they may assert on `c.kind` text — update only if a test references the
removed `c` variable).

### Step 2: Add a regression test

In `tests/test_mcp_server.py`, add a test that calls the `ingest` tool with a
multi-line snippet (e.g. `"# Mein Titel\n\nErste Zeile mit mehreren Worten die
über fuffzig Zeichen hinausgeht und so weiter und sofort."`) and asserts the
enqueued job's payload `title` equals `snippet_title(content)` (NOT
`content[:50]`). Follow the existing pattern in that file for building the
server / inspecting the queue.

**Verify**: `uv run pytest tests/test_mcp_server.py -k title` → passes. Then
temporarily revert the mcp fix to confirm the test FAILS with `content[:50]`
— this proves the test guards the regression. Re-apply the fix.

## Test plan

- New test asserting MCP ingest enqueues `payload["title"] == snippet_title(...)`
  for a multi-line snippet, modeled on existing `test_mcp_server.py` tests.
- Verification: `uv run pytest tests/test_mcp_server.py` → all pass.

## Done criteria

- [ ] `uv run pytest` exits 0
- [ ] `grep -n "content\[:50\]" kb/` returns NO matches
- [ ] `grep -n "build_payload" kb/mcp_server.py` returns a match (import + call)
- [ ] New regression test exists and passes
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- An existing `test_mcp_server.py` test depends on the exact `content[:50]`
  behavior (unlikely) — report rather than silently weakening it.
- `build_payload`'s signature differs from `(kind, payload)` at HEAD — STOP.

## Maintenance notes

- This plan is a subset of the consolidation in plan 008. If 008 lands first,
  this plan is obsolete (mark REJECTED).
- Reviewers: confirm the new test genuinely fails on `content[:50]` before
  accepting.
