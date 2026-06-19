# Plan 018: Structured logging + request correlation across the services

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- kb/gateway.py kb/instance_service.py kb/worker.py kb/cognee_io.py`
> If any in-scope file changed since this plan was written, compare excerpts to live code; on mismatch, STOP.

## Status

- **Priority**: P3 | **Effort**: M | **Risk**: LOW-MED | **Depends on**: none
- **Category**: dx | **Planned at**: commit `5c096b7`, 2026-06-19
- **Issue**: #18 — https://github.com/Jehu/cognee-kb/issues/18

## Why this matters

The only runtime diagnostics are bare `print(..., file=sys.stderr)` calls
(`worker.py:43,64`, `instance_service.py:32`, plus the one added by plan 007).
There is no `import logging`/`getLogger` anywhere, no request id threaded from
gateway → instance `/query` → worker job. A failed ingest seen in the PWA as
"job failed" requires manually correlating three processes by eyeballing
unstructured German text lines.

## Current state

- `grep "import logging|getLogger" kb/` → none.
- Gateway proxy (`gateway.py:99-102`) sends no correlation header.
- Worker logs `job.id` and failure type but not vault/dataset/originating request.

## Scope

**In scope**: `kb/gateway.py` (generate + forward request id), `kb/instance_service.py`
/`kb/worker.py`/`kb/cognee_io.py` (use a logger, include request id + job id +
vault). Optionally a tiny `kb/logging_setup.py`.
**Out of scope**: do NOT add a log-shipping/observability backend; structured
stderr (JSON or key=value) is the target.

## Steps

1. Add `kb/logging_setup.py` configuring a stdlib logger with a JSON or
   key=value formatter on stderr (keep zero new deps; stdlib only).
2. In the gateway middleware, generate a request id (uuid4 short) per request,
   add `X-Request-ID` to the response, and forward it as a header on the proxied
   `/query` (`gateway.py:100-102`).
3. In the instance service `/query`, read `X-Request-ID` and attach it to a
   logging `extra`/contextvar so `cognee_io.query_with_sources` can include it.
   In the worker, include `job.id`, vault, dataset, and (if available) the
   request id in every log line. Replace the `print(..., stderr)` calls with
   `logger.info/error`.
4. Add tests asserting (a) the gateway emits an `X-Request-ID` response
   header, (b) a worker failure log line contains the job id + vault (capture
   logs with `caplog`).

## Commands you will need

| Purpose | Command | Expected |
|--------|---------|----------|
| Tests  | `uv run pytest` (or `make test`) | all pass |

## Done criteria

- [ ] `uv run pytest` exits 0; new log/correlation tests pass
- [ ] No `print(..., file=sys.stderr)` remains in `kb/` for diagnostics (grep)
- [ ] Gateway response carries `X-Request-ID`; worker logs include job id + vault
- [ ] No new runtime dependency added
- [ ] Only in-scope files modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- A logger setup breaks cognee's own logging (cognee may configure root logger)
  — isolate to named loggers (`kb.*`), do NOT reconfigure root beyond a handler.
- Threading a request id requires changing the ingest job schema (it would be
  nice but is out of scope) — keep correlation on the query path only.

## Maintenance notes

- Reviewers: confirm logs are emitted under the `kb.*` logger namespace and
  that cognee's own output is not silenced.
