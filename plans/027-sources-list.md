# Plan 027: Sources-Management — List ( + Delete später)

> **Status**: TODO (Follow-up aus Direction-Spike 022). **Nicht ausgeführt.**
> **Priority**: P2  **Effort**: S (List)  **Risk**: LOW  **Depends on**: —
> **Category**: direction (build)  **Planned at**: `88e52a8`, 2026-06-20

## Why
Sources sind heute nur create+read; ein mistagged Ingest ist aus der UI permanent.
List allein ist schon der Hauptnutzen (Aufräumen sehen, node-sets prüfen).

## Design (siehe plans/022)
- **List (dieser Plan):** `SourceStore.list_by_vault(vault, limit, offset)` +
  `GET /api/sources/{vault}` (token-gated, wie andere `/api`) + einfache
  PWA-Seite (Tabelle: Titel, Typ, Datum, node-set). Keine cognee-Abhängigkeit.
- **Delete (separater Folgeplan):** braucht Tracking der cognee-`data_id` beim
  Ingest (cognee.delete existiert, aber kb speichert die ID nicht). Schema-
  Migration bestehender Records → nicht-trivial. Erst angehen, wenn List da ist.

## Done
- List-Endpoint + Seite; Vault-Scoped (kein Cross-Vault-Leak, analog
  `/source/.../raw`); Tests; `make check` grün.
