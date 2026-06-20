# Plan 026: `kb import` — Markdown/Datei-Migration in einen Vault

> **Status**: TODO (Follow-up aus Direction-Spike 021 → GO). **Nicht ausgeführt.**
> **Priority**: P2  **Effort**: S  **Risk**: LOW  **Depends on**: —
> **Category**: direction (build)  **Planned at**: `88e52a8`, 2026-06-20

## Why
PRD Phase 3 offenes Item + Erfolgskriterium #4 (Obsidian-Git-Sync abschalten).
Pipeline existiert; nur ein Walk+Enqueue fehlt.

## Design (siehe plans/021 für volle Begründung)
- `kb import <vault> <path> [--node-set X] [--dry-run]` — rekursiver Walk über
  `.md`/`.txt`; pro Datei ein `file`-Job via `JobQueue.enqueue` (bestehender
  Worker-`file`-Zweig liest + schreibt Raw-Kopie + ingested).
- Vault-Routing explizit per Arg; Dedup via `find_by_hash`; Serial-Constraint
  gewahrt (nur Enqueue, kein direkter cognee-Call).
- `--dry-run` zählt + zeigt Dedup-Treffer, ohne zu enqueuen.

## Done
- Befehl läuft; Tests (Walk, Dedup-Skip, dry-run); `make check` grün.

## Out of scope (v2)
- Erhaltung von Obsidian-Frontmatter als SourceRecord-Felder.
