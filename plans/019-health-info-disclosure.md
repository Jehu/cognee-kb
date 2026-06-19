# Plan 019: Reduce `/api/health` info disclosure (wall names + liveness to unauth callers)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- kb/gateway.py web/src/pages/settings.astro tests/test_gateway.py`
> If any in-scope file changed since this plan was written, compare excerpts to live code; on mismatch, STOP.

## Status

- **Priority**: P3 | **Effort**: S | **Risk**: LOW | **Depends on**: none
- **Category**: security | **Planned at**: commit `5c096b7`, 2026-06-19
- **Issue**: #19 — https://github.com/Jehu/cognee-kb/issues/19

## Why this matters

`/api/health` is intentionally unauthenticated (`gateway.py:154`, comment
"bewusst ohne Token (Monitoring)"), but it returns the full instance map
`{"gateway":"ok","instances":{"local":"ok","cloud":"down"}}`. Combined with
`host="0.0.0.0"` (`cli.py`), anyone reaching port 8800 — not just Tailscale
peers — learns the wall names and their liveness. Low severity (recon only),
but the existence of a `local` wall is itself a privacy signal worth not
broadcasting.

## Current state

`kb/gateway.py:154-164`:
```python
154:    @app.get("/api/health")  # bewusst ohne Token (Monitoring)
155:    async def health() -> dict:
...
161:                instances[name] = "ok" if r.status_code == 200 else "down"
...
164:        return {"gateway": "ok", "instances": instances}
```

`web/src/pages/settings.astro:48` calls `/api/health` unconditionally (no
Authorization header) to render the connection-test panel.

## Scope

**In scope**: `kb/gateway.py` (gate the `instances` map behind the token),
`web/src/pages/settings.astro` (send the token when calling health),
`tests/test_gateway.py` (assert unauth gets only `gateway`, auth gets full).
**Out of scope**: the instance-service `/health` (already 127.0.0.1 only).

## Steps

1. In `/api/health`, return `{"gateway": "ok"}` to unauthenticated callers, and
   the full `{"gateway": "ok", "instances": {...}}` only when a valid bearer is
   present. Reuse `require_token` logic — but since the route is currently
   outside the protected router, accept the header optionally: read
   `authorization`, compare with `secrets.compare_digest` like `require_token`,
   and branch on validity.
2. Update `settings.astro` to send the Authorization header when calling
   `/api/health` so the connection test still shows per-instance liveness when
   a token is set.
3. Tests: (a) unauth `/api/health` → 200 with only `gateway`, no `instances`;
   (b) authed `/api/health` → full map.

## Commands you will need

| Purpose | Command | Expected |
|--------|---------|----------|
| Tests  | `uv run pytest tests/test_gateway.py` | all pass |
| Full   | `uv run pytest` (or `make test`) | all pass |

## Done criteria

- [ ] `uv run pytest` exits 0; new health-disclosure tests pass
- [ ] Unauth `/api/health` returns no `instances` map
- [ ] Settings panel still shows per-instance status when a token is set
- [ ] Only in-scope files modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- An external monitor (e.g. uptime check) relies on the unauth `instances` map
  — if so, keep returning `gateway` only and let the monitor key on that.
- The token-gated branch breaks the settings connection test — ensure the PWA
  sends the header (Step 2) before merging.

## Maintenance notes

- Reviewers: confirm the unauth response contains NO wall names, not even a
  count.
