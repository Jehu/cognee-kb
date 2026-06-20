# Plan 028: PDF-Source-Connector

> **Status**: TODO (Follow-up aus Direction-Spike 024 → GO für PDF). **Nicht ausgeführt.**
> **Priority**: P3  **Effort**: S  **Risk**: LOW  **Depends on**: 004 (SSRF-Guard)
> **Category**: direction (build)  **Planned at**: `88e52a8`, 2026-06-20

## Why
PDF ist der am häufigsten gewünschte Connector; cognee extrahiert nativ
(`PdfDocument`) → kaum Eigencode. X/LinkedIn bewusst NO-GO (ToS/Fragilität).

## Design (siehe plans/024)
- `classify` erkennt `.pdf`-URL (`^https?://…\.pdf$`) / Datei → neuer Zweig
  `kind="pdf"`.
- `worker._fetch` "pdf"-Zweig: Datei/URL → lokaler Pfad → `cognee.add(path)`
  (cognee übernimmt Text-Extraktion). Bei URL-Fetch Plan 004s SSRF-Guard nutzen.
- `SourceRecord.type` nimmt `"pdf"` auf; PWA-Icon ergänzen.
- `node_set`-Pfad identisch zu web/snippet.

## Done
- PDF via URL + Datei ingestierbar; Tests (classify-Zweig, fetch-Mock);
  `make check` grün.

## Out of scope
- X/Twitter, LinkedIn (NO-GO, siehe Spike).
