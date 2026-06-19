# Plan 008: Consolidate gateway/MCP/CLI shared helpers (fixes proxy fragility too)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- kb/gateway.py kb/mcp_server.py kb/cli.py kb/config.py tests/test_gateway.py tests/test_mcp_server.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/003-mcp-snippet-title.md (do 003 first; if 003 already
  routed MCP through `build_payload`, skip the classify part of Step 2)
- **Category**: tech-debt
- **Planned at**: commit `5c096b7`, 2026-06-19
- **Issue**: #8 — https://github.com/Jehu/cognee-kb/issues/8

## Why this matters

The same logic is copy-pasted across `gateway.py`, `mcp_server.py`, and
`cli.py`, and the copies have already drifted. `queue_path`/`sources_path` are
byte-identical in three files. The query-proxy block exists twice and has
diverged: the gateway does an unguarded `r.json()` + `body["answer"]` (crashes
on a 200-with-non-JSON or missing-`answer` instance response), while the MCP
server defends both. This is the structural issue behind the MCP title bug
(plan 003) and the gateway proxy crash. Consolidating removes the drift and
makes all three entry points behave identically.

## Current state

Duplicated `queue_path`:
- `kb/gateway.py:34` `def queue_path(instance_name): return get_instance(instance_name).var_dir / "queue.db"`
- `kb/cli.py:32` — identical
- `kb/mcp_server.py:24` — identical

(`sources_path` exists only in `gateway.py:38`.)

Diverged proxy blocks:
- `kb/gateway.py:94-113` — `httpx.AsyncClient` → `POST /query` → on
  `TransportError` raises `HTTPException(502)`; on non-200 raises 502; then
  `body = r.json()` (no try/except) and `body["answer"]` (unguarded).
- `kb/mcp_server.py:42-61` — same skeleton but on `TransportError`/non-200
  returns a readable string; wraps `r.json()` in `try/except ValueError`;
  uses `data.get("answer")`.

`kb/config.py:104-105` already exposes `get_instance`; a `queue_path`/
`sources_path` helper belongs next to it.

## Repo conventions to match

- Keep each file's existing top docstring/role (gateway = cognee-free proxy +
  PWA; mcp = cognee-free stdio; cli = dispatcher). The shared helpers go into
  `config.py` (already the SoT for instance paths) or a new tiny
  `kb/instance_paths.py` — prefer `config.py` since `get_instance` is there.
- German comments explaining the why.
- Gateway raises `HTTPException`; MCP returns a string — keep each caller's
  *return contract*, only share the underlying fetch+normalize logic.

## Commands you will need

| Purpose    | Command                                              | Expected on success |
|------------|------------------------------------------------------|---------------------|
| Tests      | `uv run pytest tests/test_gateway.py tests/test_mcp_server.py tests/test_cli.py` | all pass |
| Full suite | `uv run pytest` (or `make test`)                     | all pass            |

## Scope

**In scope**:
- `kb/config.py` (add `queue_path` + `sources_path`)
- `kb/gateway.py`, `kb/mcp_server.py`, `kb/cli.py` (use the shared helpers;
  share the proxy normalization)
- `tests/test_gateway.py` (add a 200-non-JSON + missing-`answer` regression)

**Out of scope**:
- Do NOT change public HTTP/tool/CLI response shapes.
- Do NOT merge the three files into one.

## Git workflow

- Branch: `advisor/008-proxy-consolidation`
- Commit style: `Share instance path + query-proxy helpers across gateway/mcp/cli`

## Steps

### Step 1: Hoist path helpers into `config.py`

In `kb/config.py`, add near `get_instance`:

```python
def queue_path(instance_name: str) -> Path:
    return get_instance(instance_name).var_dir / "queue.db"


def sources_path(instance_name: str) -> Path:
    return get_instance(instance_name).var_dir / "sources.db"
```

Then in `gateway.py`, `mcp_server.py`, `cli.py`: import these from `kb.config`
and delete the local `queue_path` defs. Update call sites (they already call
`queue_path(...)` so only the import + def removal changes).

**Verify**: `uv run pytest` → green (pure refactor so far).

### Step 2: Extract a shared query-proxy normalizer

Create a function that does the httpx call + normalization and returns a
neutral result, leaving each caller to map it to its own contract. Add to
`kb/config.py` is wrong (no httpx there) — put it in a small new module
`kb/query_proxy.py`:

```python
"""Geteilter Query-Proxy an den Instance Service (Gateway + MCP nutzen das).

Kapselt httpx + Normalisierung, sodass beide Aufrufer dieselbe Defensivität
bekommen (Transportfehler, non-200, non-JSON, fehlender 'answer'-Key).
"""
import httpx
from kb.config import get_instance

QUERY_TIMEOUT = 120.0


class QueryProxyError(RuntimeError):
    """Konnte keine Antwort vom Instance Service erhalten."""


async def proxy_query(instance_name: str, question: str, datasets: list[str]) -> str:
    """Liefert die Antwort oder raises QueryProxyError mit lesbarem Text."""
    inst = get_instance(instance_name)
    try:
        async with httpx.AsyncClient(timeout=QUERY_TIMEOUT) as client:
            r = await client.post(
                f"http://127.0.0.1:{inst.port}/query",
                json={"question": question, "datasets": datasets})
    except httpx.TransportError:
        raise QueryProxyError(
            f"Instance Service '{inst.name}' (Port {inst.port}) nicht erreichbar — "
            f"läuft `kb serve-instance {inst.name}`?") from None
    if r.status_code != 200:
        raise QueryProxyError(f"Instance Service '{inst.name}' antwortete mit {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        raise QueryProxyError(f"Instance Service lieferte keine JSON-Antwort: {r.text[:200]}") from None
    answer = data.get("answer") if isinstance(data, dict) else None
    if not answer:
        raise QueryProxyError(f"Instance Service lieferte keine Antwort: {data}")
    return answer
```

### Step 3: Route gateway + MCP through `proxy_query`

- `gateway.py /query`: call `answer = await proxy_query(v.instance, ...)`,
  catch `QueryProxyError` → `raise HTTPException(502, str(e)) from None`.
  Return `{"vault": v.name, "answer": answer, "sources": []}` (sources stay
  empty at the gateway layer; source enrichment happens in the instance
  service and is already in the JSON it returns — verify the instance service
  returns `{"answer", "sources"}` and pass `data.get("sources", [])` through.
  NOTE: this requires `proxy_query` to optionally return sources too — extend
  the return to `(answer, sources)` and have the instance-service JSON drive
  both. Keep the gateway response shape identical.)
- `mcp_server.py _query`: call `proxy_query`, catch `QueryProxyError` →
  `return str(e)`.

**Verify**: `uv run pytest tests/test_gateway.py tests/test_mcp_server.py` →
existing tests pass (update mocks from `httpx.AsyncClient` to `proxy_query`
where tests stubbed the transport).

### Step 4: Add proxy-robustness regression tests

In `tests/test_gateway.py`: (a) instance returns 200 with non-JSON body →
gateway returns 502 (not 500); (b) instance returns 200 with `{}` (no
`answer`) → 502. In `tests/test_mcp_server.py`: the same two cases return a
readable string. (If a shared `tests/test_query_proxy.py` is cleaner, add the
unit tests there against `proxy_query` directly and keep one integration test
per caller.)

**Verify**: `uv run pytest` → all pass.

## Test plan

- `tests/test_query_proxy.py` (new): TransportError, non-200, non-JSON,
  missing-answer → each raises `QueryProxyError` with the right message.
- `tests/test_gateway.py`: 200-non-JSON → 502; missing-answer → 502.
- `tests/test_mcp_server.py`: both cases → readable string.
- Verification: `uv run pytest` → all pass.

## Done criteria

- [ ] `uv run pytest` exits 0
- [ ] `grep -rn "def queue_path" kb/` returns exactly ONE match (in `config.py`)
- [ ] `grep -rn "AsyncClient" kb/gateway.py kb/mcp_server.py` shows the query
      proxy no longer duplicated (both call `proxy_query`)
- [ ] Gateway no longer crashes on 200-non-JSON or missing `answer` (returns 502)
- [ ] No public response shape changed
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- The gateway response shape depends on fields beyond `answer`/`sources` that
  `proxy_query` would drop — STOP and extend the helper rather than losing data.
- A caller relies on the raw `httpx.Response` (e.g. forwards headers) — STOP;
  the helper abstracts that away.
- Plan 003 already changed `mcp_server.py`'s classify path — reconcile before
  editing (the drift-check will surface this).

## Maintenance notes

- New instance-callers (another transport, an HTTP API) should reuse
  `proxy_query` rather than re-rolling httpx.
- Reviewers: the risk here is changing a response shape. Diff the gateway
  `/query` and MCP `search` outputs before/after and assert byte-identical
  happy-path responses.
