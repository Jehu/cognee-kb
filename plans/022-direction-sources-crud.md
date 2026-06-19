# Plan 022: [direction] Design — sources management surface (list / delete)

> A **direction spike/design plan**. The core unknown is whether Cognee lets us
> cleanly DELETE a source from its graph/vector stores. Resolve that before
> proposing a build.
>
> **Executor instructions**: Investigate and produce a short design doc. Do NOT
> build the feature.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- kb/gateway.py kb/sources.py kb/cognee_io.py`

## Status

- **Priority**: P3 (direction) | **Effort**: S–M (coarse) | **Risk**: MED
- **Depends on**: none | **Category**: direction | **Planned at**: commit `5c096b7`, 2026-06-19
- **Issue**: #22 — https://github.com/Jehu/cognee-kb/issues/22

## Why this matters (grounding)

Sources are **create** (`POST /api/ingest`) and **read**
(`GET /source/{vault}/{source_id}/raw`, source chips in `chat.astro:137-162`)
only. The gateway has no list/delete/edit route (`grep` `gateway.py` → only the
raw GET), and the PWA has no browse/manage UI. A mistagged or bad ingest is
permanent from the UI's perspective — friction Marco currently works around by
hand. This is CRUD-asymmetry completion, not a new capability.

## Investigation questions to resolve

1. **Cognee deletion**: does `cognee` expose a way to delete a document and its
   derived entities/embeddings by `dataset` + `node_set` + id? Inspect the
   installed cognee API (`import cognee; dir(cognee)`). If deletion only works
   at dataset granularity, per-source delete is not cleanly possible.
2. **Cascade correctness**: deleting the `SourceRecord` + raw file alone is
   insufficient — the source would reappear in queries via Cognee's graph. What
   must be removed in Cognee to make a delete stick? (If nothing, delete is
   cosmetic and the finding is "not worth doing until Cognee supports it".)
3. **List surface**: `SourceStore` (`sources.py`) holds the records; a
   `list_by_vault(vault, limit, offset)` + a `GET /api/sources/{vault}` endpoint
   + a PWA management page is the obvious shape — confirm it fits the existing
   per-request-connection pattern (`gateway.py:120`).
4. **Edit scope**: editing likely means delete + re-ingest (title/node_set
   metadata lives in Cognee). Confirm rather than design an in-place edit.

## Scope of THIS plan (design only)

- Read `kb/sources.py`, `kb/gateway.py`, `kb/cognee_io.py`; inspect cognee's
  deletion API; produce a design doc answering the 4 questions with a go/no-go
  gated on question 1/2.

## Done criteria

- [ ] Design doc records whether per-source delete is feasible in Cognee (with
      the API evidence)
- [ ] If feasible: list + delete endpoint + PWA page sketched, with the cascade
      steps
- [ ] If NOT feasible: explicit "rejected — blocked on Cognee", recorded so it
      isn't re-audited
- [ ] `plans/README.md` status row updated

## STOP conditions

- Cognee has no per-source/per-document deletion API — record as rejected
  (blocked upstream); do not design a half-deletion that leaves the graph dirty.

## Maintenance notes

- If delete becomes possible later, this is the first feature to revisit. The
  list endpoint alone (without delete) may still be worth a small follow-up.
