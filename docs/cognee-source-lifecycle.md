# Cognee source lifecycle (1.2.2)

Stand: 2026-07-11, geprüft gegen Cognee 1.2.2.

## Ergebnis

Das Gate für quellbezogenes Löschen und erneutes Indexieren ist bestanden.
`kb` nutzt diesen Ablauf inzwischen für Sammlungsänderungen: gewünschte und
erfolgreich indexierte Zuordnungen, Cognee-IDs, Revisionen, transaktionale
Outbox, Queue-Wiederanlauf und sichtbarer Synchronisationsstatus sind
implementiert. Löschen, `add` und `cognify` bilden weiterhin keine
speicherübergreifende Transaktion.

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
- `kb/cognee_io.py` ermittelt und persistiert `data_id` und `dataset_id`
  defensiv, auch wenn `cognee.add` keine vollständige Rückgabe liefert.

Der reale Test liegt als bewusst deaktivierter Cloud-Gate unter
`tests/test_cognee_cloud_gate.py`. Er verwendet ausschließlich synthetische
Inhalte und läuft nur mit `KB_RUN_COGNEE_CLOUD_GATE=1`.

## Konsequenz für Quellenrevisionen und Sammlungen

Eine Änderung schreibt zuerst die gewünschte Zuordnung und eine eindeutige
Outbox-Revision. Der serielle Worker löscht nur die betroffene Cognee-Quelle,
fügt ihre kanonische Rohdatei mit Provenance- und Collection-NodeSets erneut
hinzu und veröffentlicht den indexierten Zustand erst nach erfolgreichem
`cognify`. Ein Fehler lässt den letzten bestätigten Zustand bestehen; ein Retry
ist idempotent. Die Markdown-Rohschicht bleibt der vollständige Wiederaufbau-
und Rollback-Pfad.
