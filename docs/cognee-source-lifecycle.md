# Cognee source lifecycle (0.3.x)

Stand: 2026-07-11, geprüft gegen die installierte Cognee-Version 0.3.x.

## Ergebnis

Das Gate für atomare Quellenrevisionen ist **nicht bestanden**. `kb` implementiert deshalb vorerst keine automatische Aktivierung geänderter Revisionen.

Cognee stellt zwar `add`, `delete` und `update` bereit, aber `update` führt intern nacheinander `delete`, `add` und `cognify` aus. Scheitert `add` oder `cognify` nach dem Löschen, ist die bisher aktive Quelle bereits aus Graph, Vektor- und relationaler Datenbank entfernt. Eine Transaktion oder ein Rollback über diese drei Speicher ist nicht vorhanden.

## Verifizierte API-Eigenschaften

- `cognee.add(...)` liefert `PipelineRunInfo` mit `dataset_id` und `data_ingestion_info`; die Einträge in `data_ingestion_info` enthalten `data_id`.
- `cognee.delete(data_id, dataset_id, mode)` entfernt Dokument-Subgraph, Vektoren und relationale Zuordnungen.
- `cognee.update(data_id, data, dataset_id, ...)` ruft zuerst `delete`, danach `add` und zuletzt `cognify` auf.
- `kb/cognee_io.py` verwirft die Rückgabe von `cognee.add` derzeit. `SourceRecord` kennt daher weder `data_id` noch `dataset_id`.

## Konsequenz für Plan 029

U8 bleibt gemäß Stop-Bedingung ausgesetzt. Eine sichere Umsetzung benötigt mindestens:

1. Persistenz von Cognee-`data_id` und `dataset_id` beim ersten Ingest.
2. Einen getesteten Rollback, der bei fehlgeschlagenem Update die vorherige Rohdatei erneut einspielt und cognifiziert.
3. Einen Integrationstest mit temporären Cognee-Verzeichnissen, der nach erfolgreichem Update das Verschwinden eines nur in der alten Revision vorkommenden Texts und das Auftauchen eines nur in der neuen Revision vorkommenden Texts belegt.
4. Einen Fehlerfalltest, der nach einem simulierten `add`- oder `cognify`-Fehler die alte Revision wieder als suchbar nachweist.

Bis diese vier Bedingungen erfüllt sind, bleibt die bestehende content-hash-basierte Idempotenz unverändert. Eine bloße Raw-Datei-Historie ohne korrekte abgeleitete Zustände würde Nutzern eine Versionssicherheit vortäuschen, die die Suche nicht einhält.
