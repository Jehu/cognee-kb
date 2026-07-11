# Cognee 0.3.9 → 1.2.2: Rebuild und Cutover

Dieses Runbook ist für eine geplante Wartung gedacht. Eine alte Cognee-Ablage
darf niemals mit 1.2.2 in-place geöffnet werden. `raw/<vault>/` und
`var/<wall>/sources.db` sind die Wiederaufbauquelle; historische freie
Node-Set-Namen werden nicht automatisch zu Sammlungen.

## Freigabe und Abbruchkriterien

Jede Wall wird einzeln migriert. Vor dem ersten schreibenden Schritt braucht es
eine ausdrückliche Betreiberfreigabe. Während Backup, Rebuild und Umschaltung
bleiben Gateway, Instance Service und Worker gestoppt. Abbruch und Rollback,
wenn Backup-Prüfung, Provider-Guard, Vault-Isolation, Quellenanzahl, Testfrage
oder ein Reindex-Retry fehlschlägt. Die nächste Wall beginnt erst nach der
zeitlich begrenzten Beobachtung der vorherigen.

## 1. Vorprüfung

```sh
uv sync --frozen
uv run python -c "import cognee; print(cognee.__version__)"
make check
uv run kb status
```

Erwartet wird exakt Cognee `1.2.2`. Quellenanzahl je Vault, freie Plattenkapazität
und Startzeit notieren. Für die Cloud-Wall nur unkritische Smoke-Test-Inhalte
verwenden.

## 2. Wall stoppen und unverändert sichern

```sh
uv run kb down <wall>
uv run kb down gateway
```

Danach `kb.toml`, `.env.<wall>`, `var/<wall>/sources.db`, `queue.db`, alle
`var/<wall>/cognee_*`-Verzeichnisse und die betroffenen `raw/<vault>/` in ein
zeitgestempeltes, schreibgeschütztes Backup kopieren. Das Backup mit einem
SHA-256-Manifest prüfen. Die alten Cognee-Verzeichnisse anschließend nur
umbenennen, nicht löschen, beispielsweise nach `cognee_data.pre-1.2.2`.

## 3. Rebuild auf einem getrennten Ziel

Der Rebuild wird aus den Source-Records und deren `raw_md_path` durchgeführt,
nicht über die normale Dedup-Importstrecke. Jede Quelle wird mit ihrer
unveränderten Source-ID als Provenance-NodeSet und den aktuell gewünschten
`collection:<uuid>`-NodeSets in ein leeres, versioniertes Ziel geschrieben.
`dataset_id` und `data_id` werden in einer Kopie von `sources.db` aktualisiert.

```sh
uv run python ops/rebuild_cognee_store.py local var/migrations/rebuild-local-1.2.2
uv run python ops/rebuild_cognee_store.py cloud var/migrations/rebuild-cloud-1.2.2 --batch-by-vault
```

Ein unterbrochener Vault-Batch kann nach Prüfung des isolierten Ziels
inkrementell fortgesetzt werden:

```sh
uv run python ops/rebuild_cognee_store.py cloud var/migrations/rebuild-cloud-1.2.2 \
  --resume-vault business-ki
```

Niemals die gesicherten 0.3.9-Verzeichnisse als Ziel konfigurieren.

## 4. Prüfen und atomar umschalten

Vor der Umschaltung müssen gelten:

- SQLite `integrity_check` ist `ok`, `foreign_key_check` ist leer.
- Quellenanzahl und unveränderliche Source-Spalten stimmen mit dem Manifest überein.
- Keine verwaisten Zuordnungen; normalisierte Namen sind pro Vault eindeutig.
- Wiederholte Schema-Initialisierung erzeugt keine Änderung.
- Native NodeSet-OR-Suche liefert nur Quellen aus der gewählten Sammlung.
- Provider-Guard und Vault-/Wall-Isolation schlagen bei falschem Scope geschlossen fehl.

Dann die neuen `cognee_*`-Verzeichnisse und die geprüfte `sources.db` innerhalb
desselben Dateisystems auf ihre kanonischen Namen umbenennen. Zuerst nur die
betroffene Instance starten, Health und eine bekannte Testfrage prüfen, danach
Gateway/Worker wieder freigeben.

```sh
uv run kb up <wall>
uv run kb up gateway
uv run kb status
```

Start-, Rebuild- und Prüfzeiten sowie Ergebnis und Backup-Pfad protokollieren.

## 5. Rollback

Bei einem Abbruch sofort Gateway und Wall stoppen, die neuen Verzeichnisse aus
dem kanonischen Pfad nehmen und die unveränderten Backup-Namen atomar
zurückschalten. Der Code unterstützt danach nicht Cognee 0.3.9; ein vollständiger
Rollback umfasst deshalb auch den zuvor gesicherten Code-/Lockfile-Stand. Erst
nach erneuter Prüfung wieder starten. Alte Stores werden erst nach einem
separaten, bestätigten Aufbewahrungszeitraum entfernt.

## Protokoll 2026-07-11

- Backup: `var/migrations/20260711-221527`, 1.638 Dateien, SHA-256 geprüft.
- Local: 2 Quellen, ungefähr 5 Minuten; echter CHUNKS-Service-Smoke-Test grün.
- Cloud: 52 Quellen, ungefähr 7 Minuten im finalen Vault-Batch. Ein vorheriger
  ACL-Lauf wurde ohne Cutover verworfen; zwei hängende Provider-Requests wurden
  im isolierten Ziel abgebrochen und inkrementell erfolgreich fortgesetzt.
- Cognee 1.2.2 aktiviert Multi-Tenant-ACL standardmäßig. Für `kb` ist sie in
  beiden Single-User-Walls explizit deaktiviert: Wall-Trennung ist physisch,
  Vault-Trennung wird durch Dataset-Scope plus vollständige lokale
  Source-Allowlist erzwungen.
- Echte Service-Abfragen nach Prozessneustart bestätigten Local, `allgemein`
  und `business-ki`.
- `kb restart` beendet die vollständige detached Prozessgruppe, damit
  Cognee-DB-Worker keinen Ladybug-Lock über den Neustart hinaus halten.
