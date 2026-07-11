# kb — persönliche Knowledge Base mit getrennten Datenschutzbereichen

`kb` sammelt Webseiten, PDFs, YouTube-Transkripte, Dateien und Notizen in thematischen Vaults. Inhalte lassen sich über eine PWA, die CLI oder MCP-Agenten erfassen und abfragen.

Das zentrale Datenschutzprinzip sind getrennte **Walls**:

- `local` verarbeitet private Inhalte ausschließlich lokal mit Ollama.
- `cloud` verwendet ein Cloud-LLM, derzeit über OpenRouter/DeepSeek.

Die aktuelle Konfiguration enthält den lokalen Vault `privat` sowie die Cloud-Vaults `allgemein`, `business-ki` und `business-mwe`. Walls, Vaults und Ports werden zentral in `kb.toml` definiert.

## Schnellstart

### 1. Abhängigkeiten und Zugangsdaten einrichten

```sh
uv sync
cp .env.local.template .env.local       # Ollama konfigurieren
cp .env.cloud.template .env.cloud       # Cloud-API-Key eintragen
cp .env.gateway.template .env.gateway   # KB_API_TOKEN setzen
```

Für die Weboberfläche:

```sh
cd web
npm install
npm run build
cd ..
```

### 2. Dienste starten

```sh
uv run kb up
```

Dieser Befehl startet Gateway, lokale Wall und Cloud-Wall im Hintergrund. Die Prozesse überleben das Terminal.

Status prüfen:

```sh
uv run kb status
```

Die PWA wird vom Gateway auf Port `8800` ausgeliefert. Beim ersten Aufruf den `KB_API_TOKEN` aus `.env.gateway` in den Einstellungen hinterlegen.

## Wissen erfassen

### Über die PWA

Der Capture-Screen nimmt URLs, Text und unterstützte Quellen entgegen. Optional können Metadaten und ein Node-Set angegeben werden. Der Fortschritt des Queue-Jobs wird direkt angezeigt.

Ohne gültigen Gateway-Token bleiben Vault-Auswahl, Capture und Chat gesperrt.

### Über die CLI

```sh
uv run kb ingest <vault> <url-oder-text-oder-datei>
```

Beispiele:

```sh
uv run kb ingest privat "Eine private Notiz"
uv run kb ingest allgemein https://example.com/artikel
uv run kb ingest business-ki ./bericht.pdf
```

Der Inhalt wird zunächst in die serielle Queue gelegt. Der Worker lädt beziehungsweise extrahiert die Quelle, schreibt eine kanonische Markdown-Kopie nach `raw/<vault>/` und übergibt sie anschließend an Cognee.

### Bestehende Markdown-Sammlungen importieren

```sh
uv run kb import <vault> <datei-oder-verzeichnis>
```

Unterstützt werden `.md` und `.txt`. Wichtige Optionen:

```sh
--dry-run
--exclude "drafts/*"
--only-newer-than 2026-01-01
--limit 100
--node-set projekt-a
```

Der Import geht ebenfalls durch die Queue und respektiert damit die Single-Writer-Grenze von Cognee/Ladybug.

### Mobil erfassen

Der Zugriff von unterwegs ist über Tailscale möglich, ohne Port `8800` öffentlich freizugeben. Für das iOS-Teilen-Sheet siehe [ops/ios-kurzbefehl.md](ops/ios-kurzbefehl.md).

## Wissen abfragen

### Chat in der PWA

Der Chat erzeugt Antworten ausschließlich aus zuvor gefundenen Evidenz-Chunks. Die Oberfläche zeigt:

- validierte Belege pro Aussage,
- die zugehörigen Quellen,
- erkennbare Wissenslücken wie fehlende, nicht auflösbare oder veraltete Evidenz.

### Antwort über die CLI

```sh
uv run kb query <vault> "Frage"
```

### Nur Evidenz abrufen

```sh
uv run kb search <vault> "Frage"
```

`search` liefert gerankte Chunks ohne Antwort-Synthese und damit ohne zusätzlichen Synthese-LLM-Aufruf.

### Retrieval diagnostizieren

```sh
uv run kb diagnose-query <vault> "Frage"
```

Die Diagnose zeigt Ränge, Quellenauflösung, Gap-Signale und Laufzeiten. Chunk-Inhalte sind standardmäßig ausgeblendet. Für eine lokale Detailanalyse:

```sh
uv run kb diagnose-query <vault> "Frage" --show-content
```

Die Schwelle für den Hinweis auf veraltete Evidenz wird über `KB_STALE_DAYS` gesetzt; Standard sind 180 Tage.

## Agenten über MCP verbinden

Jede Wall besitzt einen eigenen stdio-MCP-Server. Dadurch kann ein Agent nur die Vaults der registrierten Wall erreichen.

```sh
uv run kb serve-mcp local
uv run kb serve-mcp cloud
```

Der jeweilige Instance Service muss bereits laufen. Die verfügbaren Werkzeuge werden aus `kb.toml` erzeugt:

- `search_<vault>` erzeugt eine evidenzgebundene Antwort.
- `retrieve_<vault>` liefert gerankte Evidenz ohne Synthese.
- `search_all` und `retrieve_all` existieren bei Walls mit mehreren Vaults.
- `ingest` legt Inhalte in die Queue.
- `job_status` prüft einen Queue-Job.

MCP-Server immer im **Project Scope** registrieren:

- local-MCP nur in privaten Projekten,
- cloud-MCP nur in Business-Projekten,
- niemals einen kb-MCP global im User Scope registrieren.

Anleitung und Vorlagen: [ops/mcp-setup.md](ops/mcp-setup.md), [ops/mcp/local.mcp.json](ops/mcp/local.mcp.json) und [ops/mcp/cloud.mcp.json](ops/mcp/cloud.mcp.json).

## Betrieb und Wartung

### Dienste steuern

```sh
uv run kb up                    # alles starten
uv run kb up local              # nur eine Wall starten
uv run kb up gateway            # nur das Gateway starten
uv run kb status                # Ports und PIDs anzeigen
uv run kb logs gateway          # Log live verfolgen
uv run kb restart local         # eine Wall neu starten
uv run kb restart gateway       # Gateway neu starten
uv run kb restart all           # alles neu starten
uv run kb down                  # alles stoppen
```

Logs liegen unter `var/gateway.log` beziehungsweise `var/<wall>/logs/serve.log`.

### Bestandsprüfung

```sh
uv run kb maintain <instance>
```

Ohne `--apply` ist der Befehl strikt read-only. Er meldet unter anderem fehlende oder unzulässige Raw-Pfade, doppelte Inhalte, fehlgeschlagene Jobs und verwaiste temporäre Dateien.

Nur zwei Reparaturen sind derzeit freigegeben:

```sh
uv run kb maintain local --apply stale-jobs
uv run kb maintain local --apply orphan-temp
```

Re-Index, Quellenlöschung und Metadatenumschreibung bleiben absichtlich gesperrt.

## Walls und Vaults konfigurieren

`kb.toml` ist die Single Source of Truth für Walls, Vaults und Ports:

```toml
[walls.local]
mode = "local"
port = 8801

[[vaults]]
name = "privat"
wall = "local"
```

Aus den Namen werden weitere Werte abgeleitet:

- Wall `<name>` verwendet `.env.<name>` und `var/<name>/`.
- Vault `<name>` verwendet das Cognee-Dataset `<name>` und `raw/<name>/`.

Nach Änderungen gelten folgende Neustartregeln:

- Neuer Vault in bestehender Wall: `kb restart <wall>` und `kb restart gateway`.
- Neue Wall: zuerst `.env.<name>` anlegen, danach `kb restart all`.
- Geänderter Port: betroffene Wall und Gateway neu starten.

CLI-Aufrufe lesen `kb.toml` bei jedem Start neu. Laufende Server halten dagegen einen Konfigurations-Schnappschuss.

`kb.toml` wird beim Start validiert. Ungültiges TOML, doppelte Ports oder Vaults mit unbekannter Wall führen zu einem klaren `ConfigError`. Das Umbenennen eines Vaults migriert keine Daten: Dataset und Pfade werden aus dem Namen abgeleitet, daher startet der neue Name leer.

## Datenschutz und Datenfluss

Vor jedem Cognee- oder Synthese-Aufruf prüft ein Guard, ob der konfigurierte LLM-Provider zur Wall passt:

- `local` erlaubt nur `ollama`.
- `cloud` erlaubt nur den konfigurierten Cloud-Provider.
- Embeddings bleiben fest auf `fastembed`, weil ein Wechsel bestehende Vektoren ungültig machen würde.

Eine Abfrage läuft so ab:

1. Cognee `CHUNKS` liefert Evidenz innerhalb der gewählten Wall.
2. `kb` vergibt lokale Evidenz-IDs wie `e1` und `e2`.
3. Das für die Wall erlaubte LLM synthetisiert ausschließlich aus diesen Chunks.
4. Unbekannte oder Cross-Vault-Quellen-IDs werden verworfen.
5. Die Antwort enthält additive Felder für `evidence`, `citations`, `gaps` und `trace`.

Das Gateway auf Port `8800` ist mit einem Bearer-Token geschützt und importiert Cognee nicht. Es proxyt Abfragen an die nur auf `127.0.0.1` erreichbaren Instance Services. `kb` verwendet Cognee 1.2.2 mit dessen Ladybug-basiertem Graph-Stack. Pro Wall gibt es genau einen Worker; alle Cognee-Zugriffe innerhalb des Prozesses werden zusätzlich serialisiert, damit Ingest und Suche dieselbe Instanz nicht gleichzeitig verändern oder lesen.

Die versionierbare Markdown-Rohschicht unter `raw/<vault>/` bleibt der Exit-Pfad aus Cognee. Quellenrevisionen sind noch nicht aktiviert. Cognee 1.2.2 kann einzelne Quellen löschen und neu indexieren; `kb` nutzt diesen nicht-atomaren Ablauf erst, sobald Queue, Wiederanlauf und sichtbarer Synchronisationsstatus gemeinsam umgesetzt sind. Details stehen in [docs/cognee-source-lifecycle.md](docs/cognee-source-lifecycle.md).

## Docker und VPS

Das Ein-Container-Setup startet Gateway und alle konfigurierten Instance Services als getrennte Subprozesse:

```sh
docker compose up -d --build
docker compose logs -f
docker compose restart
docker compose down
```

`kb.toml`, `.env.*` und die Datenverzeichnisse werden gemountet. Änderungen an Topologie oder Token benötigen daher nur einen Neustart, keinen Rebuild. Nur Port `8800` wird veröffentlicht; Instance Services bleiben intern. Docker überwacht `/api/health`.

Ollama läuft nicht im Container. Auf einem reinen Cloud-VPS entweder nur Cloud-Walls in `kb.toml` definieren oder Ollama als separaten Dienst betreiben und `LLM_ENDPOINT` entsprechend setzen.

## Entwicklung

Alle Prüfungen:

```sh
make test
uv run ruff check kb tests
uv run ruff format --check kb tests
uv run mypy kb
cd web && npm run build
```

Einzelne Testbereiche:

```sh
uv run pytest
uv run pytest tests/test_worker.py
cd web && npm test
```

Weiterführende Produkt-, Architektur- und Betriebsdokumente liegen unter `docs/` und `ops/`.
