# Plan 021: [direction] Design — raw-layer re-ingest / Markdown-KB migration

> A **direction spike/design plan**, not a build-everything plan. Goal: define
> the API and open questions for importing an existing Markdown vault, then
> decide whether to build. Grounded in PRD Phase 3 (open) + success criterion #4.
>
> **Executor instructions**: Investigate and produce a short design doc under
> `docs/` (or appended to `plans/README.md` Spike notes). Do NOT build the
> feature in this plan.
>
> **Drift check (run first)**: `git diff --stat 5c096b7..HEAD -- kb/cli.py kb/sources.py kb/rawstore.py docs/prd-multi-vault-knowledge-system.md`

## Status

- **Priority**: P2 (direction) | **Effort**: M (coarse) | **Risk**: MED
- **Depends on**: none | **Category**: direction | **Planned at**: commit `5c096b7`, 2026-06-19

## Why this matters (grounding)

- `docs/prd-multi-vault-knowledge-system.md:69` — "Phase 3 … offen bleibt die
  Migration bestehender Markdown-KB in den passenden Business-Vault."
- Success criterion `prd:76` (#4): "Obsidian-Git-Sync auf iOS ist ersatzlos
  abgeschaltet" — **cannot be met** until an existing Obsidian/Markdown vault
  can be imported.
- The raw exit-ramp is already built (PRD F5/N3, `rawstore.py` writes one
  canonical `.md` per source), and the fetcher/classifier/worker pipeline
  exists — but there is **no re-ingest command** and the gateway exposes only
  `GET /source/{vault}/{source_id}/raw` (`gateway.py:115`); no bulk import.

## Investigation questions to resolve

1. **Source mapping**: how does a legacy `.md` (with arbitrary frontmatter) map
   to a `SourceRecord` (`sources.py:41-52`)? Which frontmatter keys become
   `url`/`video_id`/`locator`/`title`/`node_set`? What's the default `type`
   (`file`? `snippet`?) for migrated content?
2. **Vault routing**: who decides `business-ki` vs `business-mwe` for an
   imported note — a CLI flag, a per-dir mapping, or interactive? (Migration is
   explicitly single-user; keep it simple.)
3. **Dedup vs force-reingest**: should import honor `find_by_hash` dedup
   (plan 002's cleanup-aware version), or force-add because legacy content may
   legitimately duplicate?
4. **Serial constraint (F7)**: import MUST go through the existing serial worker
   (one writer per wall) — not a parallel importer — or it reintroduces the
   cognify race the PRD warns about. Confirm the import path enqueues jobs, not
   direct cognee calls.
5. **Scope of raw files**: should imported `.md` be copied into `raw/<vault>/`
   (preserving the exit-ramp invariant) and re-derived, or referenced in place?

## Proposed surface (to validate, not build)

- `uv run kb import <vault> <dir-or-file> [--node-set X] [--type file]` — walks
  `.md`/`.txt`, builds payloads via the existing `classify`/`build_payload`
  path, enqueues one job per doc into `<vault>`'s queue. Honors the serial
  worker. Optionally a `--dry-run` that reports counts + dedup hits.

## Scope of THIS plan (design only)

- Read `kb/cli.py`, `kb/worker.py`, `kb/sources.py`, `kb/rawstore.py`,
  `kb/classify.py` and the PRD; produce a design doc answering the 5 questions
  + the proposed CLI surface + the dedup/force decision. Do NOT write the
  feature.

## Done criteria

- [ ] A design doc exists (in `docs/` or `plans/README.md` Spike notes)
      answering all 5 questions with code references
- [ ] The doc states whether import enqueues via the worker (it must) and how
      it preserves the serial-write invariant
- [ ] A go/no-go recommendation with the deciding trade-off
- [ ] `plans/README.md` status row updated (direction → either "design done,
      build deferred" or "rejected")

## STOP conditions

- The PRD at HEAD already records migration as done/withdrawn — STOP.
- The existing pipeline can't import without a parallel write — report the
  constraint; do not design around the serial invariant.

## Maintenance notes

- If this becomes a build plan, it depends on plan 002 (so re-import dedup is
  cleanup-safe) and must respect plan 020's Kuzu-concurrency conclusion.
