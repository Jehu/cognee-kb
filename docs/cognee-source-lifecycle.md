# Cognee source lifecycle (1.2.2)

Stand: 2026-07-11, geprüft gegen Cognee 1.2.2.

## Ergebnis

Das Gate für quellbezogenes Löschen und erneutes Indexieren ist bestanden.
`kb` aktiviert Quellenrevisionen und Collection-Reindexierung trotzdem erst,
wenn Queue-Wiederanlauf, persistierte Cognee-IDs und ein sichtbarer
Synchronisationsstatus gemeinsam implementiert sind. Löschen, `add` und
`cognify` bilden weiterhin keine speicherübergreifende Transaktion.

## Verifizierte API-Eigenschaften

- `cognee.add(..., node_set=...)` akzeptiert weiterhin mehrere NodeSets.
- `cognee.search(..., query_type=CHUNKS, node_name=[...],
  node_name_filter_operator="OR")` filtert native Chunk-Treffer nach NodeSet.
- `cognee.datasets.delete_data(dataset_id, data_id)` entfernt eine einzelne
  Quelle über Cognees Ownership-Ledger.
- Ein realer Wegwerf-Test mit zwei Quellen und einem gemeinsamen Begriff hat
  gezeigt: Nach dem Löschen von Quelle A bleiben Quelle B und der gemeinsame
  Begriff durchsuchbar.
- Erneutes Hinzufügen und Cognifizieren von Quelle A stellt deren Treffer wieder
  her; ein wiederholter identischer Lauf erzeugte keine zusätzlichen Data-Records.
- `kb/cognee_io.py` verwirft die Rückgabe von `cognee.add` derzeit noch.
  `SourceRecord` kennt daher noch keine `data_id` oder `dataset_id`.

Der reale Test liegt als bewusst deaktivierter Cloud-Gate unter
`tests/test_cognee_cloud_gate.py`. Er verwendet ausschließlich synthetische
Inhalte und läuft nur mit `KB_RUN_COGNEE_CLOUD_GATE=1`.

## Konsequenz für Quellenrevisionen und Collections

Eine sichere produktive Umsetzung benötigt weiterhin:

1. Persistenz von Cognee-`data_id` und `dataset_id` beim ersten Ingest.
2. Einen idempotenten Queue-Job für Löschen, erneutes `add` und `cognify`.
3. Getrennte gewünschte und erfolgreich indexierte Zustände, damit fehlgeschlagene
   Reindexierungen keine breitere Suche verursachen.
4. Wiederanlauf und Retry nach einem Fehler zwischen den drei Cognee-Schritten.
5. Einen sichtbaren Status für ausstehende oder fehlgeschlagene Synchronisierung.

Bis diese Bedingungen umgesetzt sind, bleibt die bestehende content-hash-basierte
Idempotenz unverändert. Die Markdown-Rohschicht bleibt der vollständige
Wiederaufbau- und Rollback-Pfad.
